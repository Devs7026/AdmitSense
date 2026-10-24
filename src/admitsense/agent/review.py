"""AdmitSense review engine: waiting-period analysis, citation verification, and packet generation.

This module implements Milestone M3-B:
- Evaluates case facts with provenance.
- Retrieves clauses from actual extracted documents using EvidenceRetrieval.
- Verifies citations against physical 1-based page text.
- Enforces tool execution budget (<= 8 calls) and emits caregiver-friendly telemetry.
- Evaluates condition-specific waiting periods against continuous coverage history.
- Transparently reports shortfalls (e.g. 24-month condition vs 18-month history) without
  inventing dummy waivers or claiming insurer approval.
- Emits validated ReviewPacket with findings, checklists, questions, and next actions.
"""

from __future__ import annotations

import re
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
    MissingEvidenceItem,
    ReviewPacket,
    ReviewStatus,
    StopReason,
    utc_now,
)


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
    # Look for digits e.g. (24) or 18
    digit_match = re.search(r"\(?(\d+)\)?\s*(?:continuous|consecutive)?\s*months?", text, re.IGNORECASE)
    if digit_match:
        return int(digit_match.group(1))

    # Look for word representations e.g. twenty-four
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
        # Fallback to key words from procedure
        words = [w for w in re.split(r"\W+", proc_lower) if len(w) > 3]
        terms.extend(words[:3])

    terms.append("waiting period")
    return terms


# ==============================================================================
# Review Runner Implementation
# ==============================================================================
class WaitingPeriodReviewer:
    """Bounded review engine implementing ReviewRunner protocol.

    Executes waiting-period reviews against actual extracted document pages,
    respects fact provenance, checks citations, enforces an 8-call tool budget,
    and returns a pure Pydantic ReviewPacket snapshot.
    """

    def __init__(self, default_tool_budget: int = 8, default_timeout_seconds: float = 30.0) -> None:
        self.default_tool_budget = min(default_tool_budget, 8)
        self.default_timeout_seconds = default_timeout_seconds

    def run_review(
        self,
        case: CaseDetails,
        retrieval: Any,
        prior_packet: ReviewPacket | None = None,
        tool_budget: int = 8,
        timeout_seconds: float = 30.0,
        event_callback: Callable[[ToolActivityEvent], None] | None = None,
    ) -> ReviewPacket:
        """Executes bounded waiting-period review and returns validated ReviewPacket."""
        budget = min(tool_budget, 8)
        run_id = f"run-{case.case_id}-{uuid.uuid4().hex[:8]}"
        step_counter = 0

        def call_tool(
            tool_name: Literal["search_pages", "read_page", "verify_citation", "lookup_hospital"],
            args: dict[str, Any],
            summary: str,
            action: Callable[[], Any],
        ) -> Any:
            nonlocal step_counter
            if step_counter >= budget:
                raise RuntimeError(f"Tool budget limit of {budget} calls reached.")

            step_counter += 1
            current_step = step_counter

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

            try:
                res = action()
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

        # Check available documents for this case
        available_docs = []
        if hasattr(retrieval, "list_documents"):
            available_docs = retrieval.list_documents(case_id=case.case_id)

        # ----------------------------------------------------------------------
        # Case Check A: Missing Procedure
        # ----------------------------------------------------------------------
        if not case.procedure:
            # Check if procedure can be discovered from hospital estimate document
            proc_found = None
            if step_counter < budget:
                results = call_tool(
                    "search_pages",
                    {"case_id": case.case_id, "query": "Procedure Planned Admission", "max_results": 3},
                    "Searching documents for planned procedure details",
                    lambda: retrieval.search_pages(case.case_id, "Procedure Planned Admission", max_results=3),
                )
                if results:
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
                            proc_found = p_match.group(1).strip()

            if not proc_found:
                finding = Finding(
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
                        "User has not provided planned procedure; no hospital estimate or admission note found.",
                        "Cannot identify applicable waiting period clauses without procedure name.",
                    ],
                    next_action="Provide planned surgical or medical procedure name or upload hospital pre-admission estimate.",
                )
                chk = MissingEvidenceItem(
                    item_id="chk-procedure-name",
                    related_finding_ids=[finding.finding_id],
                    requested_information="Planned surgical or medical procedure name",
                    why_it_matters="Specific waiting period durations (e.g. 12, 24, or 36 months) depend directly on the procedure.",
                    suggested_source="Doctor's pre-admission consultation slip or hospital cost estimate",
                    status="requested",
                )
                return ReviewPacket(
                    packet_id=f"pkt-{case.case_id}-{uuid.uuid4().hex[:6]}",
                    packet_version=1,
                    run_id=run_id,
                    case=case,
                    review_status="incomplete",
                    findings=[finding],
                    missing_evidence_checklist=[chk],
                    unresolved_questions=["What specific surgical or medical procedure is planned for this hospital admission?"],
                    authorization_status="not verified",
                    tool_steps_used=step_counter,
                    stopped_reason="missing_information",
                    stop_details="Planned procedure is missing. Specific waiting period analysis paused.",
                )

        # We have a procedure
        procedure_name = case.procedure

        # ----------------------------------------------------------------------
        # Case Check B: Document Check (no documents uploaded)
        # ----------------------------------------------------------------------
        if not available_docs:
            finding = Finding(
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
            chk = MissingEvidenceItem(
                item_id="chk-upload-policy-documents",
                related_finding_ids=[finding.finding_id],
                requested_information="Master Policy Terms and Renewal Schedule PDFs",
                why_it_matters="Policy clauses establish specific waiting periods and continuous coverage requirements.",
                suggested_source="Insurer policy portal, email welcome kit, or employer TPA portal",
                status="requested",
            )
            return ReviewPacket(
                packet_id=f"pkt-{case.case_id}-{uuid.uuid4().hex[:6]}",
                packet_version=1,
                run_id=run_id,
                case=case,
                review_status="incomplete",
                findings=[finding],
                missing_evidence_checklist=[chk],
                unresolved_questions=[f"What are the policy terms and continuous coverage dates for procedure '{procedure_name}'?"],
                authorization_status="not verified",
                tool_steps_used=step_counter,
                stopped_reason="missing_information",
                stop_details="Policy documents missing. Waiting period review cannot proceed.",
            )

        # ----------------------------------------------------------------------
        # Step 1: Search Policy Documents for Waiting Period Clause
        # ----------------------------------------------------------------------
        search_terms = _derive_procedure_search_terms(procedure_name)
        matched_clause_quote = None
        matched_doc_id = None
        matched_version = None
        matched_page = None
        required_waiting_months = None

        for term in search_terms:
            if step_counter >= budget:
                break
            results = call_tool(
                "search_pages",
                {"case_id": case.case_id, "query": term, "max_results": 5},
                f"Searching policy pages for '{term}'",
                lambda t=term: retrieval.search_pages(case.case_id, t, max_results=5),
            )
            if not results:
                continue

            for match in results:
                if step_counter >= budget:
                    break
                doc_id, ver, pg, _ = match
                page_text = call_tool(
                    "read_page",
                    {"document_id": doc_id, "version": ver, "page_number": pg},
                    f"Reading document {doc_id} physical page {pg}",
                    lambda d=doc_id, v=ver, p=pg: retrieval.get_page_text(d, v, p),
                )
                if not page_text:
                    continue

                # Check if this page contains both the procedure reference and a waiting period specification
                sentences = re.split(r"(?<=[.!?])\s+", page_text)
                for sentence in sentences:
                    s_clean = normalize_whitespace(sentence)
                    if any(st in s_clean.lower() for st in ("waiting period", "waiting terms", "waiting rule", "covered only after")):
                        # Check relevance to procedure
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

        # Verify the citation if found
        evidence_list: list[Evidence] = []
        if matched_clause_quote and matched_doc_id and matched_version and matched_page:
            cand_evidence = Evidence(
                document_id=matched_doc_id,
                document_version=matched_version,
                page=matched_page,
                quote=matched_clause_quote,
                evidence_type="policy_wording",
            )
            if step_counter < budget:
                ver_res = call_tool(
                    "verify_citation",
                    {"document_id": matched_doc_id, "version": matched_version, "page": matched_page, "quote": matched_clause_quote},
                    f"Verifying quotation on document {matched_doc_id} page {matched_page}",
                    lambda e=cand_evidence: retrieval.verify_citation(e, case_id=case.case_id),
                )
                is_valid = ver_res.is_valid if hasattr(ver_res, "is_valid") else ver_res[0]
                if is_valid:
                    evidence_list.append(cand_evidence)

        # ----------------------------------------------------------------------
        # Step 2: Determine Continuous Coverage Duration / Policy History
        # ----------------------------------------------------------------------
        elapsed_months: int | None = case.policy_age_months
        schedule_evidence: Evidence | None = None
        schedule_member_name: str | None = None
        schedule_policy_id: str | None = None

        if step_counter < budget:
            sched_results = call_tool(
                "search_pages",
                {"case_id": case.case_id, "query": "Continuous coverage completed Inception Date", "max_results": 3},
                "Searching for continuous coverage duration in policy schedule",
                lambda: retrieval.search_pages(case.case_id, "Continuous coverage completed Inception Date", max_results=3),
            )
            for m in sched_results:
                if step_counter >= budget or schedule_evidence:
                    break
                doc_id, ver, pg, _ = m
                s_page_text = call_tool(
                    "read_page",
                    {"document_id": doc_id, "version": ver, "page_number": pg},
                    f"Reading policy schedule document {doc_id} page {pg}",
                    lambda d=doc_id, v=ver, p=pg: retrieval.get_page_text(d, v, p),
                )
                if not s_page_text:
                    continue

                # Extract member name & policy ID from schedule
                m_match = re.search(r"Insured Member[:\s]+([^\.\n\r]+)", s_page_text, re.IGNORECASE)
                if m_match:
                    schedule_member_name = m_match.group(1).strip()
                p_match = re.search(r"Policy ID[:\s]+([^\.\s,]+)", s_page_text, re.IGNORECASE)
                if p_match:
                    schedule_policy_id = p_match.group(1).strip()

                # Extract coverage completed
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
                    cand_ev = Evidence(
                        document_id=doc_id,
                        document_version=ver,
                        page=pg,
                        quote=quote_text,
                        evidence_type="policy_schedule",
                    )
                    if step_counter < budget:
                        ver_sched = call_tool(
                            "verify_citation",
                            {"document_id": doc_id, "version": ver, "page": pg, "quote": quote_text},
                            f"Verifying policy schedule citation on page {pg}",
                            lambda e=cand_ev: retrieval.verify_citation(e, case_id=case.case_id),
                        )
                        is_sched_valid = ver_sched.is_valid if hasattr(ver_sched, "is_valid") else ver_sched[0]
                        if is_sched_valid:
                            schedule_evidence = cand_ev
                            evidence_list.append(cand_ev)

        # If elapsed months not explicitly in document, check case dates
        if elapsed_months is None and case.continuous_coverage_start_date:
            ref_date = case.planned_admission_date or date.today()
            start = case.continuous_coverage_start_date
            elapsed_months = max(0, (ref_date.year - start.year) * 12 + (ref_date.month - start.month))

        # ----------------------------------------------------------------------
        # Step 3: Check Document Applicability (e.g. Endorsements)
        # ----------------------------------------------------------------------
        applicability_records: list[DocumentApplicability] = []
        endorsement_found = False

        for d in available_docs:
            if d.extraction_status == "unreadable":
                applicability_records.append(
                    DocumentApplicability(
                        document_id=d.document_id,
                        document_version=d.version,
                        status="uncertain",
                        reason=f"Document '{d.filename}' is unreadable; optical extraction failed and text cannot be assessed.",
                    )
                )
            elif d.evidence_type == "endorsement":
                endorsement_found = True
                # Record applicability metadata without executing M5 replay revision
                applicability_records.append(
                    DocumentApplicability(
                        document_id=d.document_id,
                        document_version=d.version,
                        policy_id=case.policy_id,
                        member_name=case.member_name,
                        status="uncertain",
                        reason="Endorsement uploaded for case. Formal revision evaluation is reserved for Milestone M5 replay.",
                    )
                )

        # ----------------------------------------------------------------------
        # Step 4: Evaluate Condition Waiting Period vs Policy History
        # ----------------------------------------------------------------------
        findings: list[Finding] = []
        checklist: list[MissingEvidenceItem] = []
        unresolved_questions: list[str] = []
        relevant_facts: list[CaseFactName] = ["procedure"]
        if case.policy_id:
            relevant_facts.append("policy_id")
        if case.continuous_coverage_start_date:
            relevant_facts.append("continuous_coverage_start_date")
        if case.policy_age_months is not None:
            relevant_facts.append("policy_age_months")
        if case.planned_admission_date:
            relevant_facts.append("planned_admission_date")

        # Identity checks / discrepancy
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
        finding_id = f"find-waiting-period-{slug}"

        # If unreadable documents exist, record limitation
        has_unreadable = any(d.extraction_status == "unreadable" for d in available_docs)
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

        if required_waiting_months is None:
            # No specific waiting clause found
            finding = Finding(
                finding_id=finding_id,
                revision=1,
                topic=f"Specific Condition Waiting Period: {procedure_name}",
                status="unresolved",
                conclusion=(
                    f"A specific waiting period clause for '{procedure_name}' was not located in the uploaded policy wording. "
                    f"General waiting periods or pre-existing condition exclusions may still apply."
                ),
                evidence=evidence_list,
                relevant_case_facts=relevant_facts,
                missing_facts=["specific_clause_reference"],
                limitations=identity_limitations + [
                    "Uploaded policy wording does not contain an explicit named clause for this procedure.",
                    "Consult full policy exclusions section or TPA desk for guidance.",
                ],
                next_action="Review full exclusion schedule or contact TPA desk for specific waiting period classification.",
            )
            findings.append(finding)
            unresolved_questions.append(
                f"Under what clause or specific illness code does the insurer classify '{procedure_name}'?"
            )
            review_status: ReviewStatus = "incomplete"
            stopped_reason: StopReason = "missing_information"
            stop_details = "Specific clause for procedure not identified in policy text."

        elif elapsed_months is None:
            # Clause found but continuous coverage duration unknown
            finding = Finding(
                finding_id=finding_id,
                revision=1,
                topic=f"Specific Condition Waiting Period: {procedure_name}",
                status="unresolved",
                conclusion=(
                    f"Under policy terms, '{procedure_name}' is subject to a specific waiting period of "
                    f"{required_waiting_months} continuous months. Continuous coverage duration is not documented."
                ),
                evidence=evidence_list,
                relevant_case_facts=relevant_facts,
                missing_facts=["continuous_coverage_start_date"],
                limitations=identity_limitations + [
                    "Elapsed continuous coverage duration is unknown.",
                    "Cannot verify waiting period satisfaction without policy inception or renewal dates.",
                ],
                next_action="Obtain policy renewal schedule or continuity certificate to prove elapsed coverage.",
            )
            findings.append(finding)
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
            review_status = "incomplete"
            stopped_reason = "missing_information"
            stop_details = f"Awaiting continuous coverage proof for {required_waiting_months}-month waiting period."

        elif elapsed_months < required_waiting_months:
            # The core M3 fictional scenario: 24-month condition vs 18-month history
            shortfall = required_waiting_months - elapsed_months
            finding = Finding(
                finding_id=finding_id,
                revision=1,
                topic=f"Specific Condition Waiting Period: {procedure_name}",
                status="unresolved",
                conclusion=(
                    f"Policy terms impose a specific waiting period of {required_waiting_months} continuous months "
                    f"for treatment of {procedure_name}. Available records document {elapsed_months} months of continuous "
                    f"coverage, leaving a {shortfall}-month shortfall before the waiting period is satisfied."
                ),
                evidence=evidence_list,
                relevant_case_facts=relevant_facts,
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
            findings.append(finding)
            checklist.append(
                MissingEvidenceItem(
                    item_id=f"chk-waiting-period-continuity-{slug}",
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
            review_status = "incomplete"
            stopped_reason = "missing_information"
            stop_details = (
                f"Waiting period shortfall of {shortfall} months ({elapsed_months} documented vs {required_waiting_months} required). "
                f"Awaiting continuity proof."
            )

        else:
            # Elapsed months >= required waiting months -> Supported finding
            finding = Finding(
                finding_id=finding_id,
                revision=1,
                topic=f"Specific Condition Waiting Period: {procedure_name}",
                status="supported",
                conclusion=(
                    f"Policy terms specify a waiting period of {required_waiting_months} continuous months for {procedure_name}. "
                    f"Available records document {elapsed_months} months of continuous coverage, satisfying this specific waiting period."
                ),
                evidence=evidence_list,
                relevant_case_facts=relevant_facts,
                missing_facts=[],
                limitations=identity_limitations + [
                    "Applies solely to specific condition waiting period; does not guarantee claim settlement or overall policy coverage.",
                    "Insurer pre-authorization submission is still required prior to planned hospital admission.",
                ],
                next_action="Confirm planned admission date and obtain itemized pre-admission cost estimate from hospital desk.",
            )
            findings.append(finding)
            review_status = "complete" if not identity_limitations and not has_unreadable else "incomplete"
            stopped_reason = "review_complete" if review_status == "complete" else "missing_information"
            stop_details = (
                f"Specific waiting period of {required_waiting_months} months satisfied by {elapsed_months} months continuous coverage."
            )

        # Build master ReviewPacket
        packet = ReviewPacket(
            packet_id=f"pkt-{case.case_id}-{uuid.uuid4().hex[:6]}",
            packet_version=1,
            run_id=run_id,
            case=case,
            review_status=review_status,
            findings=findings,
            revisions=[],  # M5 will populate revisions
            document_applicability=applicability_records,
            missing_evidence_checklist=checklist,
            unresolved_questions=unresolved_questions,
            authorization_status="not verified",
            authorization_evidence=[],
            tool_steps_used=step_counter,
            stopped_reason=stopped_reason,
            stop_details=stop_details,
        )

        return packet


# ==============================================================================
# Functional Entry Point
# ==============================================================================
def run_waiting_period_review(
    case: CaseDetails,
    retrieval: Any,
    prior_packet: ReviewPacket | None = None,
    tool_budget: int = 8,
    timeout_seconds: float = 30.0,
    event_callback: Callable[[ToolActivityEvent], None] | None = None,
) -> ReviewPacket:
    """Convenience functional wrapper around WaitingPeriodReviewer."""
    reviewer = WaitingPeriodReviewer(default_tool_budget=tool_budget, default_timeout_seconds=timeout_seconds)
    return reviewer.run_review(
        case=case,
        retrieval=retrieval,
        prior_packet=prior_packet,
        tool_budget=tool_budget,
        timeout_seconds=timeout_seconds,
        event_callback=event_callback,
    )
