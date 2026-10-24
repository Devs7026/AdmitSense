"""Export-Ready Review Packet Data Packaging for AdmitSense (Milestone M6-B & M6-I).

Provides Owner A with deterministic, structured review data extracted directly from
a persisted ReviewPacket snapshot, suitable for rendering into self-contained HTML
preview and download documents.

Invariants:
- Consumes an existing, saved ReviewPacket snapshot.
- Never triggers live model calls, agent runs, or external lookups during export.
- Preserves incomplete, complete, and pending-reassessment states.
- Ensures strict separation of hospital directory references from PDF citations.
- Includes mandatory administrative preparation disclaimers and authorization status.
- Provides HTML-safe escaping utilities for dynamic caregiver text.
"""

from __future__ import annotations

import html
from typing import Any

from admitsense.schemas import (
    Evidence,
    Finding,
    HospitalRecordReference,
    MissingEvidenceItem,
    ReviewPacket,
    Revision,
)

DISCLAIMER_TEXT = (
    "DISCLAIMER: AdmitSense is an administrative preparation aid designed to help caregivers "
    "organize policy information and questions before hospital admission. It does NOT provide medical "
    "advice, does NOT confirm policy coverage, and does NOT approve, pre-authorize, or guarantee "
    "cashless hospitalisation or insurance claim reimbursement. In a medical emergency, always seek "
    "immediate care without delaying for insurance administrative review."
)


def escape_html(text: Any) -> str:
    """Escapes dynamic text to prevent HTML/XSS injection in rendered exports."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def build_review_export_payload(packet: ReviewPacket) -> dict[str, Any]:
    """Transforms a saved ReviewPacket snapshot into a rich, structured export payload.

    Pure deterministic transformation:
    - Zero model calls.
    - Preserves all historical revision records and physical page citations.
    - Formats hospital reference metadata with synthetic labels.
    """
    if not isinstance(packet, ReviewPacket):
        raise TypeError(f"Expected ReviewPacket instance, got {type(packet).__name__}")

    case_dict = {
        "case_id": packet.case.case_id,
        "member_name": packet.case.member_name or "Not Specified",
        "policy_id": packet.case.policy_id or "Not Specified",
        "procedure": packet.case.procedure or "Not Specified",
        "planned_admission_date": packet.case.planned_admission_date.isoformat() if packet.case.planned_admission_date else "Not Specified",
        "hospital_name": packet.case.hospital_name or "Not Specified",
        "continuous_coverage_start_date": packet.case.continuous_coverage_start_date.isoformat() if packet.case.continuous_coverage_start_date else "Not Specified",
        "policy_start_date": packet.case.policy_start_date.isoformat() if packet.case.policy_start_date else "Not Specified",
    }

    # Format findings with citations
    findings_list = []
    for f in packet.findings:
        citations = [
            {
                "document_id": ev.document_id,
                "document_version": ev.document_version,
                "page": ev.page,
                "quote": ev.quote,
                "evidence_type": ev.evidence_type,
            }
            for ev in f.evidence
        ]
        findings_list.append({
            "finding_id": f.finding_id,
            "revision": f.revision,
            "topic": f.topic,
            "status": f.status,
            "conclusion": f.conclusion,
            "citations": citations,
            "limitations": list(f.limitations),
            "next_action": f.next_action,
        })

    # Format revisions
    revisions_list = []
    for rev in packet.revisions:
        revisions_list.append({
            "revision_id": rev.revision_id,
            "finding_id": rev.finding_id,
            "old_finding_revision": rev.old_finding_revision,
            "new_finding_revision": rev.new_finding_revision,
            "old_status": rev.old_status,
            "new_status": rev.new_status,
            "old_conclusion": rev.old_conclusion,
            "new_conclusion": rev.new_conclusion,
            "trigger_type": rev.trigger_type,
            "reason": rev.reason,
            "affected_topics": list(rev.affected_topics),
            "created_at": rev.created_at.isoformat(),
        })

    # Format checklist
    checklist_list = [
        {
            "item_id": item.item_id,
            "requested_information": item.requested_information,
            "why_it_matters": item.why_it_matters,
            "suggested_source": item.suggested_source,
            "status": item.status,
            "resolution_note": item.resolution_note,
        }
        for item in packet.missing_evidence_checklist
    ]

    # Format hospital reference
    hospital_dict = None
    if packet.hospital_reference:
        h = packet.hospital_reference
        hospital_dict = {
            "record_id": h.record_id,
            "hospital_name": h.hospital_name,
            "city": h.city,
            "network_tier": h.network_tier,
            "tpa_desk_contact": h.tpa_desk_contact or "Not Available",
            "dataset_version": h.dataset_version,
            "dataset_date": h.dataset_date.isoformat(),
            "is_synthetic": True,
            "limitations": list(h.limitations),
        }

    return {
        "packet_id": packet.packet_id,
        "packet_version": packet.packet_version,
        "run_id": packet.run_id,
        "generated_at": packet.generated_at.isoformat(),
        "review_status": packet.review_status,
        "stopped_reason": packet.stopped_reason,
        "stop_details": packet.stop_details,
        "authorization_status": packet.authorization_status,
        "case": case_dict,
        "hospital_reference": hospital_dict,
        "findings": findings_list,
        "revisions": revisions_list,
        "missing_evidence_checklist": checklist_list,
        "unresolved_questions": list(packet.unresolved_questions),
        "disclaimer": DISCLAIMER_TEXT,
    }
