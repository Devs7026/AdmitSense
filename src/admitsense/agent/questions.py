"""Actionable Desk and Insurer Questions Derivation Engine (Milestone M6-B).

Derives concrete, specific clarification questions for family caregivers to ask:
- Hospital admission / TPA desks.
- Insurer claims / underwriting staff.

Invariants:
- Derived strictly from active unresolved findings, conflicts, missing facts, and hospital status.
- Removes obsolete questions when evidence resolves the underlying issue.
- Avoids duplicate questions.
- Does NOT invent mandatory documents or imply insurance approval.
"""

from __future__ import annotations

from typing import Any
from admitsense.schemas import (
    CaseDetails,
    DocumentApplicability,
    Finding,
    HospitalMatchStatus,
    HospitalRecordReference,
    MissingEvidenceItem,
)


def derive_desk_and_insurer_questions(
    case: CaseDetails,
    findings: list[Finding],
    checklist: list[MissingEvidenceItem] = [],
    hospital_reference: HospitalRecordReference | None = None,
    hospital_lookup_status: HospitalMatchStatus | None = None,
    document_applicability: list[DocumentApplicability] = [],
) -> list[str]:
    """Generates specific, actionable questions for hospital desk and insurer staff.

    - Resolves/removes questions when underlying findings become 'supported'.
    - Preserves questions for remaining unresolved gaps and conflicts.
    - Adds relevant hospital TPA desk contact inquiries when available.
    - Never implies coverage or approval.
    """
    questions: list[str] = []

    # 1. Questions from Unresolved or Conflicting Findings
    for f in findings:
        # If finding is supported, NO question is generated (obsolete questions removed)
        if f.status == "supported":
            continue

        topic_lower = f.topic.lower()
        conc_lower = f.conclusion.lower()

        if f.status == "conflict":
            q = (
                f"Ask the insurer's underwriting desk to issue an official precedence clarification "
                f"between base policy terms and endorsement schedule regarding {f.topic}."
            )
            questions.append(q)

        elif f.status == "unresolved":
            if "procedure" in topic_lower or "procedure" in f.missing_facts or "procedure is unspecified" in conc_lower:
                q = "What specific surgical or medical procedure is planned for this hospital admission? Ask the attending surgeon or hospital desk for the exact clinical procedure name."
                questions.append(q)

            elif "shortfall" in conc_lower or "continuous coverage" in conc_lower or "waiting period" in topic_lower:
                q = (
                    f"Ask the insurer helpline whether prior policy continuity certificates or portability credits "
                    f"can be applied to satisfy the specific waiting period for {f.topic}."
                )
                questions.append(q)

            elif "room rent" in topic_lower or "room category" in conc_lower:
                q = (
                    "Ask the hospital admission desk whether the chosen room category complies with the policy's room rent limit "
                    "to prevent proportionate deduction penalties on associated medical charges."
                )
                questions.append(q)

            elif "no documents" in conc_lower or "zero documents" in conc_lower or "missing documents" in topic_lower:
                q = "Obtain a copy of the complete health insurance policy terms and conditions document from the insurer or employer portal."
                questions.append(q)

            else:
                q = f"Request written clarification from the insurer regarding requirements to satisfy coverage conditions for {f.topic}."
                questions.append(q)

        elif f.status == "needs_human_review":
            q = (
                f"Provide the insurer's claims department with supporting medical records for human review "
                f"regarding {f.topic}."
            )
            questions.append(q)

    # 2. Questions from Missing Case Facts
    if not case.procedure or not str(case.procedure).strip():
        questions.append("What specific surgical or medical procedure is planned for this hospital admission?")

    if not case.planned_admission_date:
        questions.append("Confirm the scheduled hospital admission date with the attending physician or hospital desk.")

    if not case.hospital_name or not case.hospital_name.strip():
        questions.append("Confirm the designated hospital name and city for the planned admission.")

    if not case.policy_id or not case.policy_id.strip():
        questions.append("Check the health insurance card or renewal schedule for the accurate policy number.")

    # 3. Questions from Hospital Reference and Lookup State
    if hospital_reference:
        if hospital_reference.tpa_desk_contact:
            questions.append(
                f"Contact the hospital TPA / Insurance desk at {hospital_reference.hospital_name} "
                f"({hospital_reference.tpa_desk_contact}) to confirm cashless pre-authorization submission deadlines "
                f"and required admission documents."
            )
        if hospital_reference.network_tier == "non_network":
            questions.append(
                f"Clarify with {hospital_reference.hospital_name} billing desk whether they provide itemized "
                f"indoor case records and payment receipts required for reimbursement claims, as this facility is not on the cashless network."
            )
    elif hospital_lookup_status == "no_match" and case.hospital_name:
        questions.append(
            f"Verify with the insurer helpline whether '{case.hospital_name}' is currently an empanelled "
            f"network hospital, as it was not found in the local hospital directory."
        )
    elif hospital_lookup_status == "ambiguous_match" and case.hospital_name:
        questions.append(
            f"Confirm the exact hospital branch and location for '{case.hospital_name}' with the admission desk "
            f"to verify network empanelment."
        )

    # 4. Questions from Ambiguous Document Applicability
    for app in document_applicability:
        if app.status == "uncertain":
            questions.append(
                f"Inquire with the insurer whether endorsement schedule '{app.document_id}' is active and "
                f"applicable to this policy."
            )

    # 5. Ordered Deduplication
    seen: set[str] = set()
    deduped: list[str] = []
    for q in questions:
        norm = " ".join(q.strip().split())
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(norm)

    return deduped
