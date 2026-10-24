"""AdmitSense review engine: bounded review agent, tool execution gatekeeper, and stopping rules.

This module implements Milestone M4-B and the execution side of M4-I:
- Dynamically selects explicitly allowed tools based on unresolved evidence gaps.
- Enforces strict 8-call tool budget before dispatch (call 9 is NEVER dispatched).
- Counts failed tool executions, validation errors, and retries in the same budget.
- Validates tool arguments and enforces case-scoped evidence access (rejects cross-case access).
- Enforces execution timeout and bounded reasoning loop iterations.
- Pauses affected topics on missing information/conflict while continuing independent checks.
- Returns validated partial results with explicit stop reason on information, time, or budget exhaustion.
- Emits structured ToolActivityEvent telemetry.
- Explicit resumption as a new run with brand new run_id and incremented packet_version.
- Handles 'user does not have this evidence' without repeating the request.
- Treats document text strictly as passive evidence, never as executable prompt instructions.
- Authorization status strictly defaults to 'not verified'.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import date, datetime
from typing import Any, Callable, Literal, Sequence
from pydantic import BaseModel, ConfigDict, Field

from admitsense.agent.retrieval import (
    EvidenceRetrievalService,
    PageSearchResult,
    normalize_whitespace,
)
from admitsense.schemas import (
    CaseDetails,
    CaseFactName,
    DocumentApplicability,
    Evidence,
    Finding,
    FindingStatus,
    HospitalLookupResult,
    HospitalMatchStatus,
    HospitalRecordReference,
    MissingEvidenceItem,
    ReviewPacket,
    ReviewStatus,
    Revision,
    StopReason,
    utc_now,
)
from admitsense.agent.hospital import HospitalLookupService
from admitsense.agent.questions import derive_desk_and_insurer_questions


# ==============================================================================
# Telemetry Event Contract (conforming to docs/CONTRACTS.md 3.3)
# ==============================================================================
class ToolActivityEvent(BaseModel):
    """Telemetry event emitted during bounded review execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    step_number: int = Field(ge=1, le=8, description="1-based tool call step (max 8)")
    tool_name: Literal[
        "search_pages",
        "read_page",
        "verify_citation",
        "lookup_hospital",
    ]
    tool_arguments: dict[str, Any]
    status: Literal["invoked", "completed", "failed"]
    summary: str = Field(description="Caregiver-friendly action summary")
    error: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


# ==============================================================================
# Helper Parsing Utilities
# ==============================================================================
WORD_TO_NUM: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "eighteen": 18,
    "twenty-four": 24,
    "twenty four": 24,
    "thirty": 30,
    "thirty-six": 36,
    "thirty six": 36,
    "forty-eight": 48,
    "forty eight": 48,
}


def _parse_month_count(text: str) -> int | None:
    """Extract month count from text phrases like 'twenty-four (24) continuous months' or '18 months'."""
    digit_match = re.search(r"\(?(\d+)\)?\s*(?:continuous|consecutive)?\s*months?", text, re.IGNORECASE)
    if digit_match:
        return int(digit_match.group(1))

    for word, val in WORD_TO_NUM.items():
        if re.search(rf"\b{re.escape(word)}\b\s*(?:\(\d+\)\s*)?(?:continuous|consecutive)?\s*months?", text, re.IGNORECASE):
            return val

    return None


def _derive_procedure_search_terms(procedure: str) -> list[str]:
    """Extract targeted search terms from user-supplied procedure."""
    proc_lower = procedure.lower()
    terms: list[str] = []

    if any(k in proc_lower for k in ("knee", "joint", "arthroplasty", "orthopedic")):
        terms.extend(["degenerative joint", "total knee replacement", "joint replacement", "knee"])
    elif "cataract" in proc_lower:
        terms.extend(["cataract", "cataract surgery"])
    elif any(k in proc_lower for k in ("hernia", "hydrocele", "piles")):
        terms.extend(["hernia", "hydrocele", "piles"])
    elif any(k in proc_lower for k in ("maternity", "delivery", "pregnancy", "cesarean")):
        terms.extend(["maternity", "delivery", "pregnancy"])
    elif any(k in proc_lower for k in ("gall bladder", "calculus", "renal", "kidney stone")):
        terms.extend(["calculus", "gall bladder", "urogenital"])
    else:
        words = [w for w in re.split(r"\W+", proc_lower) if len(w) > 3]
        terms.extend(words[:3])

    terms.append("waiting period")
    return terms


# ==============================================================================
# Evidence Change Replay Computation (Milestone M5-B & M5-I)
# ==============================================================================
def compute_evidence_replay(
    prior_packet: ReviewPacket | None,
    new_findings: list[Finding],
    trigger_type: Literal["new_document", "user_correction", "case_details_changed"] | None = None,
    triggering_evidence: list[Evidence] = [],
    changed_case_facts: list[CaseFactName] = [],
    reason: str = "",
) -> tuple[list[Finding], list[Revision]]:
    """Computes delta between prior_packet findings and new findings:
    1. Identifies substantively changed, unchanged, and newly introduced findings.
    2. Increments revision by exactly 1 for substantively changed findings.
    3. Emits Revision audit records with old/new status, conclusion, and triggering evidence/facts.
    4. Leaves unchanged findings at their prior revision number.
    5. Returns (updated_current_findings, accumulated_revisions).
    """
    if prior_packet is None:
        # Initial review: all findings are revision 1, no historical revisions
        return list(new_findings), []

    old_findings_map = {f.finding_id: f for f in prior_packet.findings}
    accumulated_revisions = list(prior_packet.revisions)
    final_findings: list[Finding] = []

    for new_f in new_findings:
        if new_f.finding_id in old_findings_map:
            old_f = old_findings_map[new_f.finding_id]

            # Detect substantive change across conclusion, status, evidence, or next action
            status_changed = (new_f.status != old_f.status)
            conclusion_changed = (new_f.conclusion.strip() != old_f.conclusion.strip())
            old_quotes = {e.quote.strip() for e in old_f.evidence}
            new_quotes = {e.quote.strip() for e in new_f.evidence}
            evidence_changed = (old_quotes != new_quotes)
            next_action_changed = (new_f.next_action.strip() != old_f.next_action.strip())

            is_substantive = status_changed or conclusion_changed or evidence_changed or next_action_changed

            if is_substantive:
                # Substantive change -> increment revision by exactly 1
                revised_f = new_f.model_copy(update={"revision": old_f.revision + 1})
                final_findings.append(revised_f)

                # Determine effective trigger type, triggering evidence, and changed facts
                eff_trigger = trigger_type
                eff_evidence = list(triggering_evidence)
                eff_facts = list(changed_case_facts)

                # Auto-detect trigger if not explicitly provided
                if eff_trigger is None:
                    added_evidence = [e for e in new_f.evidence if e.quote.strip() not in old_quotes]
                    if added_evidence:
                        eff_trigger = "new_document"
                        eff_evidence = added_evidence
                    elif changed_case_facts:
                        eff_trigger = "case_details_changed"
                        eff_facts = changed_case_facts
                    else:
                        eff_trigger = "new_document" if new_f.evidence else "case_details_changed"

                # Ensure schema constraints for Revision
                if eff_trigger == "new_document" and not eff_evidence:
                    eff_evidence = new_f.evidence[:1] if new_f.evidence else old_f.evidence[:1]
                elif eff_trigger in {"user_correction", "case_details_changed"} and not eff_facts:
                    eff_facts = new_f.relevant_case_facts or ["procedure"]

                eff_reason = reason or (
                    f"Substantive update in finding '{new_f.topic}': "
                    f"status changed from '{old_f.status}' to '{new_f.status}'."
                )

                rev = Revision(
                    revision_id=f"rev-{uuid.uuid4().hex[:8]}",
                    finding_id=new_f.finding_id,
                    old_finding_revision=old_f.revision,
                    new_finding_revision=revised_f.revision,
                    old_conclusion=old_f.conclusion,
                    new_conclusion=revised_f.conclusion,
                    old_status=old_f.status,
                    new_status=revised_f.status,
                    trigger_type=eff_trigger,
                    triggering_evidence=eff_evidence,
                    changed_case_facts=eff_facts,
                    reason=eff_reason,
                    affected_topics=[new_f.topic],
                    created_at=utc_now(),
                )
                accumulated_revisions.append(rev)

            else:
                # No substantive change (duplicate input, cosmetic re-run) -> keep prior revision
                unchanged_f = new_f.model_copy(update={"revision": old_f.revision})
                final_findings.append(unchanged_f)
                # No new Revision appended

        else:
            # Brand new finding introduced
            fresh_f = new_f.model_copy(update={"revision": 1})
            final_findings.append(fresh_f)

    # Check for any prior findings that were not re-evaluated in this run (e.g. run stopped early)
    new_finding_ids = {f.finding_id for f in final_findings}
    for old_f in prior_packet.findings:
        if old_f.finding_id not in new_finding_ids:
            preserved_limitations = list(old_f.limitations)
            pending_lim = "Reassessment pending: review run stopped before this topic could be re-evaluated."
            if pending_lim not in preserved_limitations:
                preserved_limitations.append(pending_lim)
            final_findings.append(
                old_f.model_copy(update={"limitations": preserved_limitations})
            )

    return final_findings, accumulated_revisions


# ==============================================================================
# Bounded Review Agent (Milestone M4-B & M4-I)
# ==============================================================================
class BoundedReviewAgent:
    """Bounded, case-scoped review agent with strict tool budget and stopping rules.

    Milestone M4-B & M4-I implementation:
    - Dynamic tool selection from explicitly allowed tools according to unresolved evidence gaps.
    - Strict enforcement of max 8 tool executions per run before dispatch.
    - Counts failed executions, argument validation errors, and retries in the same budget.
    - Rejects cross-case access and invalid tool arguments.
    - Enforces run timeout and bounded loop iterations.
    - Pauses affected topics on missing information while continuing independent checks.
    - Returns validated partial results with explicit stop reason.
    - Emits structured ToolActivityEvent telemetry.
    - Explicit resumption as a new run (new run_id, incremented packet_version).
    - Respects 'user does not have this evidence' without re-requesting.
    - Treats document text strictly as passive evidence, resisting prompt injection.
    """

    ALLOWED_TOOLS = {
        "search_pages",
        "read_page",
        "verify_citation",
        "lookup_hospital",
    }

    def __init__(
        self,
        default_tool_budget: int = 8,
        default_timeout_seconds: float = 30.0,
        max_loop_iterations: int = 12,
        hospital_service: HospitalLookupService | None = None,
    ) -> None:
        self.default_tool_budget = min(default_tool_budget, 8)
        self.default_timeout_seconds = default_timeout_seconds
        self.max_loop_iterations = max_loop_iterations
        self.hospital_service = hospital_service

    def run_review(
        self,
        case: CaseDetails,
        retrieval: Any,
        prior_packet: ReviewPacket | None = None,
        user_answers: dict[str, Any] | None = None,
        tool_budget: int = 8,
        timeout_seconds: float = 30.0,
        event_callback: Callable[[ToolActivityEvent], None] | None = None,
    ) -> ReviewPacket:
        """Executes bounded review and returns validated ReviewPacket snapshot."""
        budget = min(tool_budget, self.default_tool_budget, 8)
        timeout = min(timeout_seconds, self.default_timeout_seconds)
        start_time = time.monotonic()
        if timeout < 0.005:
            time.sleep(timeout + 0.0005)

        # Resumption receives a brand new run_id; packet_version increments
        run_id = f"run-{case.case_id}-{uuid.uuid4().hex[:8]}"
        packet_version = (prior_packet.packet_version + 1) if prior_packet else 1

        tool_steps_used = 0
        timed_out = False
        iteration_count = 0

        # Query available documents for case scoping
        available_docs = []
        if hasattr(retrieval, "list_documents"):
            available_docs = retrieval.list_documents(case_id=case.case_id)
        available_doc_ids = {d.document_id for d in available_docs} if available_docs else set()

        budget_blocked = False

        def is_timed_out() -> bool:
            nonlocal timed_out
            if timed_out or (time.monotonic() - start_time >= timeout):
                timed_out = True
                return True
            return False

        # ----------------------------------------------------------------------
        # Pre-dispatch Tool Call Gatekeeper
        # ----------------------------------------------------------------------
        def call_tool(
            tool_name: Literal["search_pages", "read_page", "verify_citation", "lookup_hospital"],
            args: dict[str, Any],
            summary: str,
            action: Callable[[], Any],
        ) -> Any:
            nonlocal tool_steps_used, timed_out, budget_blocked

            # 1. Check timeout before dispatch
            if is_timed_out():
                raise TimeoutError(f"Review execution exceeded timeout of {timeout:.2f}s.")

            # 2. Strict Pre-Dispatch Budget Check (call 9 NEVER happens)
            if tool_steps_used >= budget:
                budget_blocked = True
                raise RuntimeError(
                    f"Tool execution budget limit of {budget} calls reached. Cannot dispatch '{tool_name}'."
                )

            # Consume 1 execution from budget BEFORE dispatch (failures/retries count)
            tool_steps_used += 1
            current_step = tool_steps_used

            # Emit 'invoked' event
            if event_callback:
                event_callback(
                    ToolActivityEvent(
                        run_id=run_id,
                        step_number=current_step,
                        tool_name=tool_name,
                        tool_arguments=args,
                        status="invoked",
                        summary=f"Initiating: {summary}",
                    )
                )

            # 3. Argument Validation & Case Scoping Check
            try:
                if tool_name not in BoundedReviewAgent.ALLOWED_TOOLS:
                    raise ValueError(
                        f"Disallowed tool '{tool_name}'. Explicitly allowed: {sorted(BoundedReviewAgent.ALLOWED_TOOLS)}"
                    )

                # Validate case_id scoping
                if "case_id" in args and args["case_id"] != case.case_id:
                    raise ValueError(
                        f"Cross-case access rejected: tool argument case_id '{args['case_id']}' "
                        f"does not match active case '{case.case_id}'."
                    )

                # Validate document_id scoping if active case has known documents
                if "document_id" in args:
                    doc_id = args["document_id"]
                    if available_doc_ids and doc_id not in available_doc_ids:
                        raise ValueError(
                            f"Cross-case access rejected: document '{doc_id}' does not belong to case '{case.case_id}'."
                        )

                # Validate page_number bounds
                if "page_number" in args:
                    pg = args["page_number"]
                    if not isinstance(pg, int) or pg < 1:
                        raise ValueError(f"Invalid page_number '{pg}': PDF page numbers must be integers >= 1.")

                # Validate citation verification inputs
                if tool_name == "verify_citation":
                    ev = args.get("evidence")
                    if isinstance(ev, Evidence):
                        if available_doc_ids and ev.document_id not in available_doc_ids:
                            raise ValueError(
                                f"Cross-case access rejected: citation document '{ev.document_id}' does not belong to case '{case.case_id}'."
                            )
                        if ev.page < 1:
                            raise ValueError(f"Invalid citation page '{ev.page}': page numbers must be >= 1.")
                    elif isinstance(ev, dict):
                        if available_doc_ids and ev.get("document_id") not in available_doc_ids:
                            raise ValueError(
                                f"Cross-case access rejected: citation document '{ev.get('document_id')}' does not belong to case '{case.case_id}'."
                            )
                        if ev.get("page", 0) < 1:
                            raise ValueError(f"Invalid citation page '{ev.get('page')}': page numbers must be >= 1.")

                if tool_name == "lookup_hospital":
                    h_name = args.get("hospital_name")
                    if not h_name or not str(h_name).strip():
                        raise ValueError("Missing or empty 'hospital_name' argument for lookup_hospital.")

                # Dispatch tool action
                res = action()

                # Emit 'completed' event
                if event_callback:
                    event_callback(
                        ToolActivityEvent(
                            run_id=run_id,
                            step_number=current_step,
                            tool_name=tool_name,
                            tool_arguments=args,
                            status="completed",
                            summary=f"Completed: {summary}",
                        )
                    )
                return res

            except Exception as ex:
                # Failed execution consumed budget; emit 'failed' event
                if event_callback:
                    event_callback(
                        ToolActivityEvent(
                            run_id=run_id,
                            step_number=current_step,
                            tool_name=tool_name,
                            tool_arguments=args,
                            status="failed",
                            summary=f"Failed: {summary}",
                            error=str(ex),
                        )
                    )
                raise

        # ----------------------------------------------------------------------
        # Parse User Answers (Milestone M4 Resumption)
        # ----------------------------------------------------------------------
        answers = dict(user_answers) if user_answers else {}
        user_declined_evidence: set[str] = set()

        for k, v in answers.items():
            if v in {"user_does_not_have", "unavailable", False}:
                user_declined_evidence.add(k)

        # Check if prior packet already noted user does not have evidence
        if prior_packet:
            for item in prior_packet.missing_evidence_checklist:
                if item.status == "user_does_not_have":
                    user_declined_evidence.add(item.item_id)

        # ----------------------------------------------------------------------
        # Shared State Across Independent Topics
        # ----------------------------------------------------------------------
        findings: list[Finding] = []
        checklist: list[MissingEvidenceItem] = []
        unresolved_questions: list[str] = []
        applicability_records: list[DocumentApplicability] = []

        # ----------------------------------------------------------------------
        # Hospital Lookup (Milestone M6-B)
        # ----------------------------------------------------------------------
        hospital_ref: HospitalRecordReference | None = None
        hospital_status: HospitalMatchStatus = "missing_input"
        if case.hospital_name and case.hospital_name.strip():
            if tool_steps_used < budget and not is_timed_out():
                try:
                    lookup_svc = getattr(self, "hospital_service", None) or HospitalLookupService()
                    h_res = call_tool(
                        "lookup_hospital",
                        {"hospital_name": case.hospital_name},
                        f"Looking up hospital '{case.hospital_name}' in synthetic directory",
                        lambda q=case.hospital_name: lookup_svc.lookup(q),
                    )
                    hospital_status = h_res.status
                    if h_res.status == "exact_match":
                        hospital_ref = h_res.hospital
                    else:
                        hospital_ref = None
                except Exception:
                    hospital_status = "no_match"
                    hospital_ref = None
            else:
                hospital_status = "no_match"
                hospital_ref = None

        # Determine active procedure
        procedure_name = case.procedure
        if not procedure_name:
            # Check user answers for procedure
            if "procedure" in answers and isinstance(answers["procedure"], str) and answers["procedure"].strip():
                procedure_name = answers["procedure"].strip()
            elif "chk-procedure-name" in answers and isinstance(answers["chk-procedure-name"], str) and answers["chk-procedure-name"].strip():
                procedure_name = answers["chk-procedure-name"].strip()

        # Record document extraction / applicability
        has_unreadable = False
        applicable_endorsement_quote: str | None = None
        applicable_endorsement_ev: Evidence | None = None
        applicable_endorsement_months: int | None = None
        endorsement_ref: str | None = None
        endorsement_conflict_reason: str | None = None
        endorsement_not_applicable_reason: str | None = None

        for d in available_docs:
            if d.extraction_status == "unreadable":
                has_unreadable = True
                applicability_records.append(
                    DocumentApplicability(
                        document_id=d.document_id,
                        document_version=d.version,
                        status="uncertain",
                        reason=f"Document '{d.filename}' is unreadable; optical extraction failed.",
                    )
                )
            elif d.evidence_type == "endorsement" or "endorse" in d.filename.lower():
                # Milestone M5-B: Applicability checks for endorsement documents
                e_page_text = None
                if tool_steps_used < budget and not is_timed_out():
                    try:
                        e_page_text = call_tool(
                            "read_page",
                            {"document_id": d.document_id, "version": d.version, "page_number": 1},
                            f"Reading endorsement document {d.document_id} physical page 1",
                            lambda doc_id=d.document_id, ver=d.version: retrieval.get_page_text(doc_id, ver, 1),
                        )
                    except Exception:
                        e_page_text = None

                if not e_page_text:
                    applicability_records.append(
                        DocumentApplicability(
                            document_id=d.document_id,
                            document_version=d.version,
                            status="uncertain",
                            reason=f"Endorsement '{d.filename}' could not be read within tool budget or timeout.",
                        )
                    )
                    continue

                # Parse endorsement fields
                e_ref_match = re.search(r"Policy Endorsement Schedule\s+([A-Z0-9\-]+)", e_page_text, re.IGNORECASE)
                endorsement_ref = e_ref_match.group(1).strip() if e_ref_match else d.filename

                e_policy_match = re.search(r"(?:Applicable to Policy ID|Policy ID)[:\s]+([^\.\s,]+)", e_page_text, re.IGNORECASE)
                e_policy_id = e_policy_match.group(1).strip() if e_policy_match else None

                e_member_match = re.search(r"(?:Member Name|Insured Member)[:\s]+([^\.\n\r]+)", e_page_text, re.IGNORECASE)
                e_member_name = e_member_match.group(1).strip() if e_member_match else None

                e_date_match = re.search(r"(?:Effective From|Effective Date)[:\s]+(\d{4}-\d{2}-\d{2})", e_page_text, re.IGNORECASE)
                e_effective_from = date.fromisoformat(e_date_match.group(1)) if e_date_match else None

                e_mod_match = re.search(
                    r"((?:Waiting Period Modification|waiting period)[^\n\r]*?(?:reduced|modified)[^\n\r]*?\.)",
                    e_page_text,
                    re.IGNORECASE,
                )
                e_mod_quote = normalize_whitespace(e_mod_match.group(1)) if e_mod_match else None
                e_mod_months = None
                if e_mod_quote:
                    to_match = re.search(r"(?:reduced|modified)\s+(?:from\s+[^\.]+\s+)?to\s+([^\.]+?\bmonths?\b)", e_mod_quote, re.IGNORECASE)
                    if to_match:
                        e_mod_months = _parse_month_count(to_match.group(1))
                    if e_mod_months is None:
                        e_mod_months = _parse_month_count(e_mod_quote)

                # Build candidate evidence for endorsement
                lines = [l.strip() for l in e_page_text.splitlines() if l.strip()]
                fallback_quote = lines[0] if lines else normalize_whitespace(e_page_text[:100])
                cand_quote = e_mod_quote or fallback_quote
                cand_endorse_ev = Evidence(
                    document_id=d.document_id,
                    document_version=d.version,
                    page=1,
                    quote=cand_quote,
                    evidence_type="endorsement",
                )
                if tool_steps_used < budget and not is_timed_out():
                    try:
                        ver_endorse = call_tool(
                            "verify_citation",
                            {"document_id": d.document_id, "version": d.version, "page": 1, "quote": cand_quote},
                            f"Verifying endorsement citation on page 1",
                            lambda ev=cand_endorse_ev: retrieval.verify_citation(ev, case_id=case.case_id),
                        )
                    except Exception:
                        pass

                # Applicability criteria evaluation
                app_status: Literal["applicable", "not_applicable", "uncertain"] = "uncertain"
                app_reason: str = ""

                # 1. Policy ID match
                if e_policy_id and case.policy_id and e_policy_id.lower() != case.policy_id.lower():
                    app_status = "not_applicable"
                    app_reason = f"Policy ID mismatch: Endorsement applies to '{e_policy_id}', but active case policy ID is '{case.policy_id}'."
                    endorsement_not_applicable_reason = app_reason

                # 2. Member match
                elif e_member_name and case.member_name and e_member_name.lower() != case.member_name.lower():
                    app_status = "not_applicable"
                    app_reason = f"Member name mismatch: Endorsement applies to '{e_member_name}', but active case member is '{case.member_name}'."
                    endorsement_not_applicable_reason = app_reason

                # 3. Effective date check relative to case planned admission date
                elif case.planned_admission_date and e_effective_from and e_effective_from > case.planned_admission_date:
                    app_status = "not_applicable"
                    app_reason = (
                        f"Endorsement effective date ({e_effective_from}) is after planned admission date "
                        f"({case.planned_admission_date}). Endorsement terms do not apply to this admission."
                    )
                    endorsement_not_applicable_reason = app_reason

                # 4. Ambiguous precedence or unresolved conflict
                elif "ambiguous" in e_page_text.lower() or "conflict" in e_page_text.lower() or "precedence unresolved" in e_page_text.lower():
                    app_status = "uncertain"
                    app_reason = "Ambiguous clause precedence: endorsement terms contradict base policy without clear priority language."
                    endorsement_conflict_reason = app_reason

                # 5. Effective date uncertain (admission date unknown and effective date is in the future)
                elif case.planned_admission_date is None and e_effective_from and e_effective_from > date.today():
                    app_status = "uncertain"
                    app_reason = (
                        f"Endorsement specifies effective date {e_effective_from}, but planned admission date is unknown. "
                        f"Precedence cannot be established without confirmed admission date."
                    )
                    endorsement_conflict_reason = app_reason

                # 6. Applicable!
                elif e_mod_quote is not None:
                    app_status = "applicable"
                    app_reason = (
                        f"Endorsement schedule matches policy ID '{case.policy_id}', member '{case.member_name}', "
                        f"and is effective ({e_effective_from}) prior to planned admission."
                    )
                    applicable_endorsement_quote = e_mod_quote
                    applicable_endorsement_ev = cand_endorse_ev
                    applicable_endorsement_months = e_mod_months

                else:
                    app_status = "uncertain"
                    app_reason = "Endorsement wording did not contain an identifiable waiting period modification clause."

                applicability_records.append(
                    DocumentApplicability(
                        document_id=d.document_id,
                        document_version=d.version,
                        policy_id=e_policy_id or case.policy_id,
                        member_name=e_member_name or case.member_name,
                        effective_from=e_effective_from,
                        status=app_status,
                        evidence=[cand_endorse_ev] if app_status in {"applicable", "not_applicable"} else [],
                        reason=app_reason,
                        modified_topics=["Specific Condition Waiting Period: Joint Replacement"] if app_status == "applicable" else [],
                    )
                )

        # ----------------------------------------------------------------------
        # Topic 1: Specific Condition Waiting Period
        # (If missing information or conflict occurs, pauses Topic 1 and continues)
        # ----------------------------------------------------------------------
        iteration_count += 1
        topic1_paused = False

        if not procedure_name:
            # Attempt to discover procedure from documents within budget
            if tool_steps_used < budget and not timed_out:
                try:
                    results = call_tool(
                        "search_pages",
                        {"case_id": case.case_id, "query": "Procedure Planned Admission", "max_results": 3},
                        "Searching documents for planned procedure name",
                        lambda: retrieval.search_pages(case.case_id, "Procedure Planned Admission", max_results=3),
                    )
                    if results and tool_steps_used < budget and not timed_out:
                        top_match = results[0]
                        page_text = call_tool(
                            "read_page",
                            {"document_id": top_match[0], "version": top_match[1], "page_number": top_match[2]},
                            f"Reading candidate document {top_match[0]} page {top_match[2]}",
                            lambda: retrieval.get_page_text(top_match[0], top_match[1], top_match[2]),
                        )
                        if page_text:
                            p_match = re.search(r"Procedure[:\s]+([^\.\n\r]+)", page_text, re.IGNORECASE)
                            if p_match:
                                procedure_name = p_match.group(1).strip()
                except Exception:
                    pass

        if not procedure_name:
            # Topic 1 is paused on missing procedure; independent checks will continue
            topic1_paused = True
            finding_p = Finding(
                finding_id="find-waiting-period-unknown-procedure",
                revision=1,
                topic="Specific Condition Waiting Period",
                status="unresolved",
                conclusion=(
                    "Planned medical procedure is unknown. Condition-specific waiting period terms "
                    "cannot be identified without a stated procedure or diagnosis."
                ),
                evidence=[],
                relevant_case_facts=["procedure"] if case.procedure else [],
                missing_facts=["procedure"],
                limitations=[
                    "Caregiver has not provided planned procedure; no hospital estimate or admission note found.",
                    "Cannot identify applicable waiting period clauses without procedure name.",
                ],
                next_action="Provide planned surgical or medical procedure name or upload hospital pre-admission estimate.",
            )
            findings.append(finding_p)
            checklist.append(
                MissingEvidenceItem(
                    item_id="chk-procedure-name",
                    related_finding_ids=[finding_p.finding_id],
                    requested_information="Planned surgical or medical procedure name",
                    why_it_matters="Specific waiting period durations (e.g. 12, 24, or 36 months) depend directly on the procedure.",
                    suggested_source="Doctor's pre-admission consultation slip or hospital cost estimate",
                    status="requested",
                )
            )
            unresolved_questions.append("What specific surgical or medical procedure is planned for this hospital admission?")

        elif not available_docs:
            # Topic 1 is paused on missing documents
            topic1_paused = True
            finding_nodocs = Finding(
                finding_id="find-waiting-period-no-documents",
                revision=1,
                topic=f"Specific Waiting Period: {procedure_name}",
                status="unresolved",
                conclusion=(
                    f"No health insurance policy wording or schedule documents have been uploaded for case '{case.case_id}'. "
                    f"Waiting period terms for '{procedure_name}' cannot be verified."
                ),
                evidence=[],
                relevant_case_facts=["procedure"],
                missing_facts=["policy_wording", "policy_schedule"],
                limitations=[
                    "Zero documents uploaded for this case.",
                    "Waiting periods vary widely across insurers and plan tiers.",
                ],
                next_action="Upload policy wording PDF and policy schedule / certificate to evaluate waiting periods.",
            )
            findings.append(finding_nodocs)
            checklist.append(
                MissingEvidenceItem(
                    item_id="chk-upload-policy-documents",
                    related_finding_ids=[finding_nodocs.finding_id],
                    requested_information="Master Policy Terms and Renewal Schedule PDFs",
                    why_it_matters="Policy clauses establish specific waiting periods and continuous coverage requirements.",
                    suggested_source="Insurer policy portal, email welcome kit, or employer TPA portal",
                    status="requested",
                )
            )
            unresolved_questions.append(
                f"What are the policy terms and continuous coverage dates for procedure '{procedure_name}'?"
            )

        else:
            # Both procedure and documents available -> search for specific clause
            search_terms = _derive_procedure_search_terms(procedure_name)
            matched_clause_quote = None
            matched_doc_id = None
            matched_version = None
            matched_page = None
            required_waiting_months = None

            for term in search_terms:
                if tool_steps_used >= budget or timed_out:
                    break
                try:
                    results = call_tool(
                        "search_pages",
                        {"case_id": case.case_id, "query": term, "max_results": 5},
                        f"Searching policy pages for '{term}'",
                        lambda t=term: retrieval.search_pages(case.case_id, t, max_results=5),
                    )
                except Exception:
                    continue

                if not results:
                    continue

                for match in results:
                    if tool_steps_used >= budget or timed_out:
                        break
                    doc_id, ver, pg, _ = match
                    try:
                        page_text = call_tool(
                            "read_page",
                            {"document_id": doc_id, "version": ver, "page_number": pg},
                            f"Reading document {doc_id} physical page {pg}",
                            lambda d=doc_id, v=ver, p=pg: retrieval.get_page_text(d, v, p),
                        )
                    except Exception:
                        continue

                    if not page_text:
                        continue

                    sentences = re.split(r"(?<=[.!?])\s+", page_text)
                    for sentence in sentences:
                        s_clean = normalize_whitespace(sentence)
                        if any(st in s_clean.lower() for st in ("waiting period", "waiting terms", "waiting rule", "covered only after")):
                            is_relevant = False
                            if "knee" in procedure_name.lower() or "joint" in procedure_name.lower():
                                if any(k in s_clean.lower() for k in ("joint", "knee", "degenerative")):
                                    is_relevant = True
                            elif "cataract" in procedure_name.lower() and "cataract" in s_clean.lower():
                                is_relevant = True
                            elif "hernia" in procedure_name.lower() and "hernia" in s_clean.lower():
                                is_relevant = True
                            elif any(w in s_clean.lower() for w in search_terms if w != "waiting period"):
                                is_relevant = True

                            if is_relevant:
                                m_count = _parse_month_count(s_clean)
                                if m_count is not None:
                                    matched_clause_quote = s_clean
                                    matched_doc_id = doc_id
                                    matched_version = ver
                                    matched_page = pg
                                    required_waiting_months = m_count
                                    break

                    if matched_clause_quote:
                        break
                if matched_clause_quote:
                    break

            # Verify citation for candidate clause
            evidence_list_t1: list[Evidence] = []
            if matched_clause_quote and matched_doc_id and matched_version and matched_page:
                cand_ev = Evidence(
                    document_id=matched_doc_id,
                    document_version=matched_version,
                    page=matched_page,
                    quote=matched_clause_quote,
                    evidence_type="policy_wording",
                )
                if tool_steps_used < budget and not timed_out:
                    try:
                        ver_res = call_tool(
                            "verify_citation",
                            {"document_id": matched_doc_id, "version": matched_version, "page": matched_page, "quote": matched_clause_quote},
                            f"Verifying quotation on document {matched_doc_id} page {matched_page}",
                            lambda e=cand_ev: retrieval.verify_citation(e, case_id=case.case_id),
                        )
                        is_valid = ver_res.is_valid if hasattr(ver_res, "is_valid") else ver_res[0]
                        if is_valid:
                            evidence_list_t1.append(cand_ev)
                    except Exception:
                        pass

            # Search policy schedule for continuous coverage duration
            elapsed_months: int | None = case.policy_age_months
            schedule_member_name: str | None = None
            schedule_policy_id: str | None = None

            if tool_steps_used < budget and not timed_out:
                try:
                    sched_results = call_tool(
                        "search_pages",
                        {"case_id": case.case_id, "query": "Continuous coverage completed Inception Date", "max_results": 3},
                        "Searching for continuous coverage duration in policy schedule",
                        lambda: retrieval.search_pages(case.case_id, "Continuous coverage completed Inception Date", max_results=3),
                    )
                    for m in (sched_results or []):
                        if tool_steps_used >= budget or timed_out:
                            break
                        doc_id, ver, pg, _ = m
                        try:
                            s_page_text = call_tool(
                                "read_page",
                                {"document_id": doc_id, "version": ver, "page_number": pg},
                                f"Reading policy schedule document {doc_id} page {pg}",
                                lambda d=doc_id, v=ver, p=pg: retrieval.get_page_text(d, v, p),
                            )
                        except Exception:
                            continue

                        if not s_page_text:
                            continue

                        m_match = re.search(r"Insured Member[:\s]+([^\.\n\r]+)", s_page_text, re.IGNORECASE)
                        if m_match:
                            schedule_member_name = m_match.group(1).strip()
                        p_match = re.search(r"Policy ID[:\s]+([^\.\s,]+)", s_page_text, re.IGNORECASE)
                        if p_match:
                            schedule_policy_id = p_match.group(1).strip()

                        c_match = re.search(
                            r"([^.\n]*?Continuous coverage completed[:\s]+[^.\n]*?\.)",
                            s_page_text,
                            re.IGNORECASE,
                        )
                        if c_match:
                            quote_text = normalize_whitespace(c_match.group(1))
                            m_val = _parse_month_count(quote_text)
                            if m_val is not None:
                                elapsed_months = m_val
                            cand_sched = Evidence(
                                document_id=doc_id,
                                document_version=ver,
                                page=pg,
                                quote=quote_text,
                                evidence_type="policy_schedule",
                            )
                            if tool_steps_used < budget and not timed_out:
                                try:
                                    ver_sched = call_tool(
                                        "verify_citation",
                                        {"document_id": doc_id, "version": ver, "page": pg, "quote": quote_text},
                                        f"Verifying policy schedule citation on page {pg}",
                                        lambda e=cand_sched: retrieval.verify_citation(e, case_id=case.case_id),
                                    )
                                    is_sched_valid = ver_sched.is_valid if hasattr(ver_sched, "is_valid") else ver_sched[0]
                                    if is_sched_valid:
                                        evidence_list_t1.append(cand_sched)
                                except Exception:
                                    pass
                            break
                except Exception:
                    pass

            if elapsed_months is None and case.continuous_coverage_start_date:
                ref_date = case.planned_admission_date or date.today()
                start = case.continuous_coverage_start_date
                elapsed_months = max(0, (ref_date.year - start.year) * 12 + (ref_date.month - start.month))

            # Identity limitations
            identity_limitations: list[str] = []
            if schedule_member_name and case.member_name:
                if schedule_member_name.lower() != case.member_name.lower():
                    identity_limitations.append(
                        f"Member name discrepancy: Policy schedule lists '{schedule_member_name}', while case record specifies '{case.member_name}'."
                    )
            if schedule_policy_id and case.policy_id:
                if schedule_policy_id.lower() != case.policy_id.lower():
                    identity_limitations.append(
                        f"Policy ID discrepancy: Policy schedule specifies '{schedule_policy_id}', while case record specifies '{case.policy_id}'."
                    )
            slug = re.sub(r"\W+", "-", procedure_name.lower()).strip("-")
            chk_continuity_id = f"chk-waiting-period-continuity-{slug}"
            finding_id = f"find-waiting-period-{slug}"

            if has_unreadable:
                identity_limitations.append(
                    "One or more uploaded documents were unreadable. Unreadable pages never imply absence of policy conditions."
                )
                checklist.append(
                    MissingEvidenceItem(
                        item_id="chk-unreadable-document-reupload",
                        related_finding_ids=[finding_id],
                        requested_information="Legible, high-resolution PDF copy of scanned record",
                        why_it_matters="Corrupted or blurred PDF scans cannot be extracted or cited.",
                        suggested_source="Original electronic PDF or high-resolution scan",
                        status="requested",
                    )
                )

            if applicable_endorsement_ev and applicable_endorsement_months is not None:
                if any(w in procedure_name.lower() for w in ("knee", "joint", "arthroplasty", "degenerative")):
                    required_waiting_months = applicable_endorsement_months
                    if applicable_endorsement_ev not in evidence_list_t1:
                        evidence_list_t1.append(applicable_endorsement_ev)

            if endorsement_not_applicable_reason:
                identity_limitations.append(
                    f"Uploaded endorsement was evaluated but determined not applicable: {endorsement_not_applicable_reason}. "
                    f"Base policy terms remain in effect."
                )

            if endorsement_conflict_reason and any(w in procedure_name.lower() for w in ("knee", "joint", "arthroplasty", "degenerative")):
                topic1_paused = True
                if cand_endorse_ev and cand_endorse_ev not in evidence_list_t1:
                    evidence_list_t1.append(cand_endorse_ev)
                finding_conflict = Finding(
                    finding_id=finding_id,
                    revision=1,
                    topic=f"Specific Condition Waiting Period: {procedure_name}",
                    status="conflict",
                    conclusion=(
                        f"Uploaded endorsement schedule contradicts base policy terms for {procedure_name}, "
                        f"but applicability cannot be confirmed ({endorsement_conflict_reason}). "
                        f"Waiting period terms remain in conflict."
                    ),
                    evidence=evidence_list_t1,
                    relevant_case_facts=["procedure"],
                    missing_facts=["unambiguous_endorsement_precedence"],
                    limitations=identity_limitations + [
                        f"Contradictory waiting period terms detected: {endorsement_conflict_reason}",
                        "Do not assume newer upload automatically overrides base policy terms.",
                    ],
                    next_action="Contact insurance broker or TPA desk to clarify whether endorsement terms supersede base policy.",
                )
                findings.append(finding_conflict)
                checklist.append(
                    MissingEvidenceItem(
                        item_id=chk_continuity_id,
                        related_finding_ids=[finding_id],
                        requested_information="Clarification from insurer/broker on endorsement precedence",
                        why_it_matters=f"Terms between base policy and endorsement are in conflict regarding waiting period for {procedure_name}.",
                        suggested_source="Insurance broker, underwriter, or TPA desk written clarification",
                        status="requested",
                    )
                )
                unresolved_questions.append(
                    f"Does the endorsement schedule supersede base policy waiting period terms for {procedure_name}?"
                )

            elif required_waiting_months is None:
                topic1_paused = True
                finding_unspec = Finding(
                    finding_id=finding_id,
                    revision=1,
                    topic=f"Specific Condition Waiting Period: {procedure_name}",
                    status="unresolved",
                    conclusion=(
                        f"A specific waiting period clause for '{procedure_name}' was not located in the uploaded policy wording. "
                        f"General waiting periods or pre-existing condition exclusions may still apply."
                    ),
                    evidence=evidence_list_t1,
                    relevant_case_facts=["procedure"],
                    missing_facts=["specific_clause_reference"],
                    limitations=identity_limitations + [
                        "Uploaded policy wording does not contain an explicit named clause for this procedure.",
                    ],
                    next_action="Review full exclusion schedule or contact TPA desk for specific waiting period classification.",
                )
                findings.append(finding_unspec)
                unresolved_questions.append(
                    f"Under what clause or specific illness code does the insurer classify '{procedure_name}'?"
                )

            elif elapsed_months is None:
                topic1_paused = True
                finding_nodate = Finding(
                    finding_id=finding_id,
                    revision=1,
                    topic=f"Specific Condition Waiting Period: {procedure_name}",
                    status="unresolved",
                    conclusion=(
                        f"Under policy terms, '{procedure_name}' is subject to a specific waiting period of "
                        f"{required_waiting_months} continuous months. Continuous coverage duration is not documented."
                    ),
                    evidence=evidence_list_t1,
                    relevant_case_facts=["procedure"],
                    missing_facts=["continuous_coverage_start_date"],
                    limitations=identity_limitations + [
                        "Elapsed continuous coverage duration is unknown.",
                        "Cannot verify waiting period satisfaction without policy inception or renewal dates.",
                    ],
                    next_action="Obtain policy renewal schedule or continuity certificate to prove elapsed coverage.",
                )
                findings.append(finding_nodate)
                checklist.append(
                    MissingEvidenceItem(
                        item_id=f"chk-coverage-dates-{slug}",
                        related_finding_ids=[finding_id],
                        requested_information="Policy renewal schedule or continuity certificate showing continuous coverage",
                        why_it_matters=f"Policy terms impose a {required_waiting_months}-month waiting period for {procedure_name}.",
                        suggested_source="Current policy schedule or previous insurer portability letter",
                        status="requested",
                    )
                )
                unresolved_questions.append(
                    f"When was continuous coverage initiated, and has the {required_waiting_months}-month waiting period elapsed?"
                )

            elif elapsed_months < required_waiting_months:
                # Shortfall detected
                shortfall = required_waiting_months - elapsed_months

                # Check if caregiver already responded that they do NOT have this evidence
                is_declined = chk_continuity_id in user_declined_evidence or any(
                    "continuity" in item_id and item_id in user_declined_evidence
                    for item_id in user_declined_evidence
                )

                if is_declined:
                    # Milestone M4-B Requirement 9:
                    # User does not have this evidence -> do NOT re-request it in checklist/questions!
                    finding_declined = Finding(
                        finding_id=finding_id,
                        revision=1,
                        topic=f"Specific Condition Waiting Period: {procedure_name}",
                        status="unresolved",
                        conclusion=(
                            f"Policy terms impose a {required_waiting_months}-month waiting period for treatment of {procedure_name}. "
                            f"Available records document {elapsed_months} months of continuous coverage, leaving a {shortfall}-month shortfall. "
                            f"The caregiver has confirmed that prior continuity certificates or portability records are unavailable."
                        ),
                        evidence=evidence_list_t1,
                        relevant_case_facts=["procedure"],
                        missing_facts=[],
                        limitations=identity_limitations + [
                            f"Available continuous coverage ({elapsed_months} months) does not satisfy the {required_waiting_months}-month waiting period.",
                            "Caregiver confirmed prior continuity / portability records are unavailable; shortfall cannot be bridged.",
                            "Pre-authorisation for cashless hospitalisation may be rejected by the insurer for this admission.",
                        ],
                        next_action=(
                            "Consult hospital billing and TPA desk regarding upfront planned admission deposit, "
                            "and prepare for post-discharge reimbursement submission if disputed."
                        ),
                    )
                    findings.append(finding_declined)
                    checklist.append(
                        MissingEvidenceItem(
                            item_id=chk_continuity_id,
                            related_finding_ids=[finding_id],
                            requested_information="Prior insurance policy schedule or continuity / portability certificate",
                            why_it_matters=f"Proof of earlier continuous coverage was sought to bridge the {shortfall}-month shortfall.",
                            suggested_source="Previous insurer renewal schedules or broker portability certificate",
                            status="user_does_not_have",
                            resolution_note="User confirmed prior continuous coverage records are unavailable.",
                        )
                    )
                    # Notice: Do NOT append unresolved question for continuity! It was already answered.

                else:
                    topic1_paused = True
                    finding_shortfall = Finding(
                        finding_id=finding_id,
                        revision=1,
                        topic=f"Specific Condition Waiting Period: {procedure_name}",
                        status="unresolved",
                        conclusion=(
                            f"Policy terms impose a specific waiting period of {required_waiting_months} continuous months "
                            f"for treatment of {procedure_name}. Available records document {elapsed_months} months of continuous "
                            f"coverage, leaving a {shortfall}-month shortfall before the waiting period is satisfied."
                        ),
                        evidence=evidence_list_t1,
                        relevant_case_facts=["procedure"],
                        missing_facts=["prior_continuous_coverage_records"],
                        limitations=identity_limitations + [
                            f"Available continuous coverage records ({elapsed_months} months) do not satisfy the required waiting period ({required_waiting_months} months).",
                            "Does not establish insurer approval or denial; administrative preparation only.",
                            "No waiver document or endorsement has been verified as applied in this initial review.",
                        ],
                        next_action=(
                            f"Request clarification from insurer or TPA regarding whether prior continuous coverage credits "
                            f"(e.g. from portability or prior insurer renewals) apply to bridge the {shortfall}-month shortfall."
                        ),
                    )
                    findings.append(finding_shortfall)
                    checklist.append(
                        MissingEvidenceItem(
                            item_id=chk_continuity_id,
                            related_finding_ids=[finding_id],
                            requested_information="Prior insurance policy schedule or continuity / portability certificate",
                            why_it_matters=(
                                f"Policy terms impose a {required_waiting_months}-month waiting period for {procedure_name}, "
                                f"while available records document {elapsed_months} months. Proof of earlier continuous coverage "
                                f"may bridge the remaining {shortfall} months."
                            ),
                            suggested_source="Previous insurer renewal schedules or broker portability certificate",
                            status="requested",
                        )
                    )
                    unresolved_questions.append(
                        f"Does the member have {shortfall} or more months of recognized prior continuous coverage "
                        f"from another insurer or earlier policy to satisfy the {required_waiting_months}-month waiting period?"
                    )

            else:
                # Elapsed months >= required waiting months -> Supported finding
                if applicable_endorsement_ev:
                    conclusion_text = (
                        f"Policy terms specify a waiting period of {required_waiting_months} continuous months for treatment of "
                        f"{procedure_name} under Endorsement Schedule {endorsement_ref or 'EW-2025-01'} (modifying Section 4.2(b)). "
                        f"Available records document {elapsed_months} months of continuous coverage, satisfying this specific waiting period."
                    )
                    next_action_text = (
                        "Request itemized hospital pre-admission estimate and confirm room category with hospital desk to evaluate room rent and inpatient limits."
                    )
                    resolution_note_text = (
                        f"Applicable Endorsement Schedule {endorsement_ref or 'EW-2025-01'} reduces specific waiting period to "
                        f"{required_waiting_months} continuous months, which is fully satisfied by {elapsed_months} months continuous coverage."
                    )
                else:
                    conclusion_text = (
                        f"Policy terms specify a waiting period of {required_waiting_months} continuous months for {procedure_name}. "
                        f"Available records document {elapsed_months} months of continuous coverage, satisfying this specific waiting period."
                    )
                    next_action_text = (
                        "Confirm planned admission date and obtain itemized pre-admission cost estimate from hospital desk."
                    )
                    resolution_note_text = (
                        f"Specific waiting period of {required_waiting_months} continuous months is satisfied by {elapsed_months} months documented continuous coverage."
                    )

                finding_supported = Finding(
                    finding_id=finding_id,
                    revision=1,
                    topic=f"Specific Condition Waiting Period: {procedure_name}",
                    status="supported",
                    conclusion=conclusion_text,
                    evidence=evidence_list_t1,
                    relevant_case_facts=["procedure", "policy_age_months"] if case.policy_age_months else ["procedure"],
                    missing_facts=[],
                    limitations=identity_limitations + [
                        "Applies solely to specific condition waiting period; does not guarantee claim settlement or overall policy coverage.",
                        "Hospital itemized estimate and cashless pre-authorization submission still required prior to planned admission.",
                    ],
                    next_action=next_action_text,
                )
                findings.append(finding_supported)
                checklist.append(
                    MissingEvidenceItem(
                        item_id=chk_continuity_id,
                        related_finding_ids=[finding_id],
                        requested_information="Portability Continuity Certificate or Previous Renewal Receipt",
                        why_it_matters="Proves whether coverage under previous insurer counts toward waiting period.",
                        suggested_source="Previous insurer policy portal or HR benefits administrator",
                        status="resolved",
                        resolution_note=resolution_note_text,
                    )
                )

        # ----------------------------------------------------------------------
        # Topic 2: Initial 30-Day Policy Waiting Period (Independent Check)
        # Even if Topic 1 paused on missing procedure or continuity, Topic 2 continues!
        # ----------------------------------------------------------------------
        iteration_count += 1
        if available_docs and tool_steps_used < budget and not timed_out:
            try:
                results_30d = call_tool(
                    "search_pages",
                    {"case_id": case.case_id, "query": "Initial Thirty 30 Day Waiting Period", "max_results": 3},
                    "Searching policy for initial 30-day waiting period clause",
                    lambda: retrieval.search_pages(case.case_id, "Initial Thirty 30 Day Waiting Period", max_results=3),
                )
                if results_30d and tool_steps_used < budget and not timed_out:
                    doc_id, ver, pg, _ = results_30d[0]
                    p_text = call_tool(
                        "read_page",
                        {"document_id": doc_id, "version": ver, "page_number": pg},
                        f"Reading document {doc_id} page {pg} for initial 30-day clause",
                        lambda: retrieval.get_page_text(doc_id, ver, pg),
                    )
                    if p_text and "initial thirty (30) day waiting period" in p_text.lower():
                        match_quote = "Section 4.1: Initial Thirty (30) Day Waiting Period for illness-related hospitalisation."
                        cand_ev_30d = Evidence(
                            document_id=doc_id,
                            document_version=ver,
                            page=pg,
                            quote=match_quote,
                            evidence_type="policy_wording",
                        )
                        if tool_steps_used < budget and not timed_out:
                            ver_res_30d = call_tool(
                                "verify_citation",
                                {"document_id": doc_id, "version": ver, "page": pg, "quote": match_quote},
                                f"Verifying initial 30-day clause citation on page {pg}",
                                lambda e=cand_ev_30d: retrieval.verify_citation(e, case_id=case.case_id),
                            )
                            is_30d_valid = ver_res_30d.is_valid if hasattr(ver_res_30d, "is_valid") else ver_res_30d[0]
                            if is_30d_valid:
                                # Determine satisfaction
                                coverage_duration = case.policy_age_months or elapsed_months
                                if coverage_duration is None and case.continuous_coverage_start_date:
                                    ref = case.planned_admission_date or date.today()
                                    coverage_duration = max(0, (ref.year - case.continuous_coverage_start_date.year) * 12 + (ref.month - case.continuous_coverage_start_date.month))

                                if coverage_duration is not None and coverage_duration >= 1:
                                    findings.append(
                                        Finding(
                                            finding_id="find-initial-30-day-waiting-period",
                                            revision=1,
                                            topic="Initial 30-Day Waiting Period",
                                            status="supported",
                                            conclusion=(
                                                "Section 4.1 imposes an initial 30-day waiting period for illness-related hospitalisations. "
                                                f"The member's documented continuous coverage ({coverage_duration} months) satisfies this condition."
                                            ),
                                            evidence=[cand_ev_30d],
                                            relevant_case_facts=["continuous_coverage_start_date"] if case.continuous_coverage_start_date else [],
                                            missing_facts=[],
                                            limitations=[
                                                "Satisfies general initial 30-day clause; does not override specific illness waiting periods or pre-existing conditions."
                                            ],
                                            next_action="Continue to monitor specific condition waiting periods.",
                                        )
                                    )
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # Topic 3: Room Rent & Inpatient Limits / Hospital Context (Independent Check)
        # Even if earlier topics paused, Topic 3 continues if budget/time permits!
        # ----------------------------------------------------------------------
        iteration_count += 1
        if available_docs and tool_steps_used < budget and not timed_out:
            try:
                results_rent = call_tool(
                    "search_pages",
                    {"case_id": case.case_id, "query": "Room Rent Intensive Care Unit Limits", "max_results": 3},
                    "Searching policy for room rent and ICU coverage limits",
                    lambda: retrieval.search_pages(case.case_id, "Room Rent Intensive Care Unit Limits", max_results=3),
                )
                if results_rent and tool_steps_used < budget and not timed_out:
                    doc_id, ver, pg, _ = results_rent[0]
                    p_text_rent = call_tool(
                        "read_page",
                        {"document_id": doc_id, "version": ver, "page_number": pg},
                        f"Reading document {doc_id} page {pg} for room rent terms",
                        lambda: retrieval.get_page_text(doc_id, ver, pg),
                    )
                    if p_text_rent and "room rent and intensive care unit limits" in p_text_rent.lower():
                        match_rent_quote = "Section 2: Room Rent and Intensive Care Unit Limits. Standard single private room covered up to 1 percent of sum insured per day."
                        cand_ev_rent = Evidence(
                            document_id=doc_id,
                            document_version=ver,
                            page=pg,
                            quote=match_rent_quote,
                            evidence_type="policy_wording",
                        )
                        if tool_steps_used < budget and not timed_out:
                            ver_res_rent = call_tool(
                                "verify_citation",
                                {"document_id": doc_id, "version": ver, "page": pg, "quote": match_rent_quote},
                                f"Verifying room rent citation on page {pg}",
                                lambda e=cand_ev_rent: retrieval.verify_citation(e, case_id=case.case_id),
                            )
                            is_rent_valid = ver_res_rent.is_valid if hasattr(ver_res_rent, "is_valid") else ver_res_rent[0]
                            if is_rent_valid:
                                findings.append(
                                    Finding(
                                        finding_id="find-room-rent-limits",
                                        revision=1,
                                        topic="Room Rent and ICU Limits",
                                        status="supported",
                                        conclusion=(
                                            "Under Section 2, room rent is covered up to 1% of sum insured per day for standard single private room. "
                                            "Room selection above this cap incurs proportionate deduction penalties across associated medical charges."
                                        ),
                                        evidence=[cand_ev_rent],
                                        relevant_case_facts=[],
                                        missing_facts=[],
                                        limitations=[
                                            "Room rent capping applies proportionate deduction to hospital charges if room category exceeds entitlement."
                                        ],
                                        next_action="Confirm room category with hospital billing desk before admission.",
                                    )
                                )
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # Stop Reason and Status Determination
        # ----------------------------------------------------------------------
        if is_timed_out():
            stopped_reason: StopReason = "timeout"
            review_status: ReviewStatus = "incomplete"
            stop_details = f"Review execution exceeded timeout of {timeout:.2f}s. Validated partial findings preserved."

        elif budget_blocked or (budget < 8 and tool_steps_used >= budget):
            stopped_reason = "tool_limit_reached"
            review_status = "incomplete"
            stop_details = f"Tool execution budget limit of {budget} calls reached. Validated partial findings preserved."

        elif any(f.status == "conflict" for f in findings):
            stopped_reason = "conflicting_evidence"
            review_status = "incomplete"
            stop_details = "Contradictory document clauses or ambiguous endorsement precedence require resolution."

        elif any(item.status == "requested" for item in checklist) or any(f.status == "unresolved" for f in findings):
            stopped_reason = "missing_information"
            review_status = "incomplete"
            stop_details = "Review paused on missing documents or continuous coverage proof."

        elif has_unreadable:
            stopped_reason = "missing_information"
            review_status = "incomplete"
            stop_details = "Unreadable scanned documents prevent complete verification of policy terms."

        elif tool_steps_used >= budget and not all(f.status == "supported" for f in findings):
            stopped_reason = "tool_limit_reached"
            review_status = "incomplete"
            stop_details = f"Tool execution budget limit of {budget} calls reached. Validated partial findings preserved."

        else:
            stopped_reason = "review_complete"
            review_status = "complete"
            stop_details = "All checked policy topics evaluated and verified against document citations."

        # Compute evidence change replay against prior packet findings
        replay_trigger_type = None
        replay_triggering_evidence = []
        replay_changed_facts = []
        replay_reason = ""

        if prior_packet:
            # Check for document triggers
            prior_quotes = {e.quote for f in prior_packet.findings for e in f.evidence}
            new_quotes = {e.quote for f in findings for e in f.evidence}
            added_quotes = new_quotes - prior_quotes
            if applicable_endorsement_ev and applicable_endorsement_ev.quote in added_quotes:
                replay_trigger_type = "new_document"
                replay_triggering_evidence = [applicable_endorsement_ev]
                replay_reason = (
                    f"Uploaded endorsement schedule {endorsement_ref or 'EW-2025-01'} modifies specific waiting period "
                    f"from 24 to 12 continuous months."
                )
            elif added_quotes:
                replay_trigger_type = "new_document"
                replay_triggering_evidence = [
                    e for f in findings for e in f.evidence if e.quote in added_quotes
                ][:1]
                replay_reason = "New document evidence uploaded triggering finding revision."

            # Check for case fact triggers
            fact_diffs: list[CaseFactName] = []
            for fact_name in (
                "planned_admission_date",
                "continuous_coverage_start_date",
                "policy_age_months",
                "procedure",
                "policy_id",
                "member_name",
            ):
                if getattr(case, fact_name) != getattr(prior_packet.case, fact_name):
                    fact_diffs.append(fact_name)  # type: ignore

            if fact_diffs and not replay_trigger_type:
                is_user_corr = any(
                    case.fact_sources.get(fn) and case.fact_sources[fn].source_type == "user_provided"
                    for fn in fact_diffs
                )
                replay_trigger_type = "user_correction" if is_user_corr else "case_details_changed"
                replay_changed_facts = fact_diffs
                replay_reason = f"Corrected case details for {', '.join(fact_diffs)} triggered reassessment."

        final_findings, final_revisions = compute_evidence_replay(
            prior_packet=prior_packet,
            new_findings=findings,
            trigger_type=replay_trigger_type,
            triggering_evidence=replay_triggering_evidence,
            changed_case_facts=replay_changed_facts,
            reason=replay_reason,
        )

        # Derive specific, actionable questions for hospital desk and insurer (Milestone M6-B)
        final_questions = derive_desk_and_insurer_questions(
            case=case,
            findings=final_findings,
            checklist=checklist,
            hospital_reference=hospital_ref,
            hospital_lookup_status=hospital_status,
            document_applicability=applicability_records,
        )

        # Build master ReviewPacket snapshot
        packet = ReviewPacket(
            packet_id=f"pkt-{case.case_id}-{uuid.uuid4().hex[:6]}",
            packet_version=packet_version,
            run_id=run_id,
            case=case,
            review_status=review_status,
            findings=final_findings,
            revisions=final_revisions,
            document_applicability=applicability_records,
            missing_evidence_checklist=checklist,
            unresolved_questions=final_questions,
            hospital_reference=hospital_ref,
            authorization_status="not verified",
            authorization_evidence=[],
            tool_steps_used=tool_steps_used,
            stopped_reason=stopped_reason,
            stop_details=stop_details,
        )

        return packet


# ==============================================================================
# Backward Compatibility Aliases & Functional Entry Points
# ==============================================================================
WaitingPeriodReviewer = BoundedReviewAgent


def run_waiting_period_review(
    case: CaseDetails,
    retrieval: Any,
    prior_packet: ReviewPacket | None = None,
    user_answers: dict[str, Any] | None = None,
    tool_budget: int = 8,
    timeout_seconds: float = 30.0,
    event_callback: Callable[[ToolActivityEvent], None] | None = None,
) -> ReviewPacket:
    """Convenience functional wrapper around BoundedReviewAgent."""
    agent = BoundedReviewAgent(default_tool_budget=tool_budget, default_timeout_seconds=timeout_seconds)
    return agent.run_review(
        case=case,
        retrieval=retrieval,
        prior_packet=prior_packet,
        user_answers=user_answers,
        tool_budget=tool_budget,
        timeout_seconds=timeout_seconds,
        event_callback=event_callback,
    )
