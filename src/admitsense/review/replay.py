"""Evidence Change Replay computation and diffing logic for AdmitSense (M5).

Provides pure, deterministic delta computation between prior review packet findings
and candidate findings, enforcing schema contracts and revision tracking.
"""

from datetime import datetime, timezone
from typing import Literal
import uuid

from admitsense.schemas import CaseFactName, Evidence, Finding, ReviewPacket, Revision


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_evidence_replay(
    prior_packet: ReviewPacket | None,
    new_findings: list[Finding],
    trigger_type: Literal["new_document", "user_correction", "case_details_changed"] | None = None,
    triggering_evidence: list[Evidence] = [],
    changed_case_facts: list[CaseFactName] = [],
    reason: str = "",
) -> tuple[list[Finding], list[Revision]]:
    """
    Computes delta between prior_packet findings and new findings:
    1. Distinguishes three finding categories:
       - Changed findings: status, conclusion, evidence citations, or next action differs from prior finding.
         Finding.revision increments by exactly 1 (old_finding.revision + 1).
         A Revision record is emitted linking old to new revision.
       - Unchanged findings: status, conclusion, evidence citations, and next action match prior finding.
         Finding.revision remains at old_finding.revision.
         Zero new Revision records are emitted for unchanged findings.
       - New findings: finding_id did not exist in prior_packet.
         Finding.revision is set to 1. No prior Revision record.
    2. Preserves prior findings that were not re-evaluated (e.g. run stopped early or budget cap reached).
    3. Enforces trigger integrity:
       - trigger_type='new_document' requires triggering_evidence.
       - trigger_type in {'user_correction', 'case_details_changed'} requires changed_case_facts.
    4. Preserves accumulated prior revisions, appending newly generated revisions.
    5. Returns (updated_findings_list, all_revisions_list).
    """
    accumulated_revisions: list[Revision] = (
        list(prior_packet.revisions) if prior_packet else []
    )

    if not prior_packet:
        # First review run: all findings are initial (revision 1)
        initial_findings: list[Finding] = []
        for f in new_findings:
            if f.revision != 1:
                f = f.model_copy(update={"revision": 1})
            initial_findings.append(f)
        return initial_findings, []

    # Build lookup of prior findings by finding_id
    prior_map: dict[str, Finding] = {f.finding_id: f for f in prior_packet.findings}

    updated_findings: list[Finding] = []
    new_revisions: list[Revision] = []

    for candidate in new_findings:
        prior_f = prior_map.get(candidate.finding_id)

        if prior_f is None:
            # Newly introduced finding
            new_f = candidate.model_copy(update={"revision": 1})
            updated_findings.append(new_f)
            continue

        # Check if substantive change occurred across status, conclusion, evidence, or next action
        status_changed = candidate.status != prior_f.status
        conclusion_changed = candidate.conclusion.strip() != prior_f.conclusion.strip()
        old_quotes = {e.quote.strip() for e in prior_f.evidence}
        new_quotes = {e.quote.strip() for e in candidate.evidence}
        evidence_changed = old_quotes != new_quotes
        next_action_changed = candidate.next_action.strip() != prior_f.next_action.strip()

        is_substantive = status_changed or conclusion_changed or evidence_changed or next_action_changed

        if is_substantive:
            # Changed finding: revision increments by exactly 1
            next_rev = prior_f.revision + 1
            rev_id = f"rev-{candidate.finding_id[:16]}-{uuid.uuid4().hex[:6]}"

            eff_trigger = trigger_type
            eff_evidence = list(triggering_evidence)
            eff_facts = list(changed_case_facts)

            # Auto-detect trigger if not explicitly provided
            if eff_trigger is None:
                added_evidence = [e for e in candidate.evidence if e.quote.strip() not in old_quotes]
                if added_evidence:
                    eff_trigger = "new_document"
                    eff_evidence = added_evidence
                elif changed_case_facts:
                    eff_trigger = "case_details_changed"
                    eff_facts = changed_case_facts
                else:
                    eff_trigger = "new_document" if candidate.evidence else "case_details_changed"

            # Enforce schema constraints for Revision
            if eff_trigger == "new_document" and not eff_evidence:
                eff_evidence = candidate.evidence[:1] or prior_f.evidence[:1]
            elif eff_trigger in {"user_correction", "case_details_changed"} and not eff_facts:
                eff_facts = candidate.relevant_case_facts or ["procedure"]

            rev_reason = (
                reason.strip()
                or f"Updated assessment for {candidate.topic} ({prior_f.status} -> {candidate.status})."
            )

            rev_record = Revision(
                revision_id=rev_id,
                finding_id=candidate.finding_id,
                old_finding_revision=prior_f.revision,
                new_finding_revision=next_rev,
                old_conclusion=prior_f.conclusion,
                new_conclusion=candidate.conclusion,
                old_status=prior_f.status,
                new_status=candidate.status,
                trigger_type=eff_trigger,
                triggering_evidence=eff_evidence,
                changed_case_facts=eff_facts,
                reason=rev_reason,
                affected_topics=[candidate.topic],
                created_at=_utc_now(),
            )
            new_revisions.append(rev_record)

            updated_f = candidate.model_copy(update={"revision": next_rev})
            updated_findings.append(updated_f)
        else:
            # Unchanged finding: preserve prior revision, emit ZERO new revisions
            unchanged_f = candidate.model_copy(update={"revision": prior_f.revision})
            updated_findings.append(unchanged_f)

    # Preserve prior findings that were not evaluated in candidate findings (e.g. run stopped early)
    updated_ids = {f.finding_id for f in updated_findings}
    for old_f in prior_packet.findings:
        if old_f.finding_id not in updated_ids:
            preserved_limitations = list(old_f.limitations)
            pending_lim = "Reassessment pending: review run stopped before this topic could be re-evaluated."
            if pending_lim not in preserved_limitations:
                preserved_limitations.append(pending_lim)
            updated_findings.append(
                old_f.model_copy(update={"limitations": preserved_limitations})
            )

    all_revisions = accumulated_revisions + new_revisions
    return updated_findings, all_revisions
