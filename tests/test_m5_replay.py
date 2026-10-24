"""Milestone M5-B & M5-I Acceptance Test Suite: Evidence Change Replay.

Tests:
1. Applicable fictional endorsement changes 24 months to 12 months.
2. Supplied 18-month history supports only the relevant narrow finding.
3. Wrong policy ID does not override the base policy.
4. Endorsement effective after the admission date does not silently apply.
5. Ambiguous precedence produces an unresolved/conflict finding.
6. Unrelated findings remain unchanged.
7. Duplicate input does not create duplicate substantive revisions.
8. A corrected case date triggers reassessment of dependent findings.
9. Failed/partial reassessment does not falsely report completion.
"""

import tempfile
from datetime import date
from pathlib import Path
import pytest

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import (
    BoundedReviewAgent,
    compute_evidence_replay,
)
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    generate_pdf_bytes,
)
from admitsense.schemas import (
    CaseDetails,
    Evidence,
    FactSource,
    Finding,
    ReviewPacket,
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


def build_wrong_policy_endorsement_pdf() -> bytes:
    """Endorsement applying to a different policy ID (POL-999999 vs POL-998877)."""
    pages = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. "
        "Applicable to Policy ID: POL-999999. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
        "Waiting Period Modification: The specific waiting period for degenerative joint disorders and "
        "joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months "
        "to twelve (12) continuous months."
    ]
    return generate_pdf_bytes(pages)


def build_future_effective_endorsement_pdf() -> bytes:
    """Endorsement effective from 2026-12-01 (after planned admission date 2026-11-15)."""
    pages = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. "
        "Applicable to Policy ID: POL-998877. Member Name: Ramesh Sharma. Effective From: 2026-12-01. "
        "Waiting Period Modification: The specific waiting period for degenerative joint disorders and "
        "joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months "
        "to twelve (12) continuous months."
    ]
    return generate_pdf_bytes(pages)


def build_ambiguous_precedence_endorsement_pdf() -> bytes:
    """Endorsement with contradictory terms and unresolved precedence clause."""
    pages = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. "
        "Applicable to Policy ID: POL-998877. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
        "Waiting Period Modification: Section 4.2(b) waiting period modified to twelve (12) continuous months, "
        "however precedence unresolved: terms conflict with master policy schedule pending underwriter review."
    ]
    return generate_pdf_bytes(pages)


@pytest.fixture
def replay_env():
    """Sets up an isolated database and synthetic documents for M5 replay tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m5.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)

        # Baseline case: Ramesh Sharma, Total Knee Replacement, admission 2026-11-15
        case = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-knee-001",
                member_name="Ramesh Sharma",
                policy_id="POL-998877",
                procedure="Total Knee Replacement",
                planned_admission_date=date(2026, 11, 15),
                fact_sources={
                    "member_name": FactSource(source_type="user_provided"),
                    "policy_id": FactSource(source_type="user_provided"),
                    "procedure": FactSource(source_type="user_provided"),
                    "planned_admission_date": FactSource(source_type="user_provided"),
                },
            )
        )

        # Base policy wording (24-month waiting period on p14)
        policy_doc, _ = doc_storage.save_document(
            case_id=case.case_id,
            filename="Care_Gold_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )

        # Policy renewal schedule (18 months continuous coverage on p1)
        sched_doc, _ = doc_storage.save_document(
            case_id=case.case_id,
            filename="Policy_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )

        retrieval = EvidenceRetrievalService(db=db)

        yield {
            "db": db,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "retrieval": retrieval,
            "case": case,
            "policy_doc": policy_doc,
            "sched_doc": sched_doc,
        }


# ==============================================================================
# Test 1 & 2: Applicable Endorsement Changes 24 to 12 Months & Narrow Scope
# ==============================================================================
def test_applicable_endorsement_changes_waiting_period_and_keeps_narrow_scope(replay_env):
    """Verifies that an applicable endorsement modifies waiting period from 24 to 12 months,
    satisfying the condition with 18 months continuous coverage.
    Also verifies that supplied 18-month history supports ONLY the narrow waiting period finding,
    leaving authorization unverified with NO overall approval claim.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    agent = BoundedReviewAgent()

    # Run initial baseline review (Packet 1)
    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)
    assert pkt_v1.packet_version == 1
    knee_f_v1 = next(f for f in pkt_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f_v1.status == "unresolved"
    assert knee_f_v1.revision == 1
    assert "shortfall" in knee_f_v1.conclusion.lower()
    assert len(pkt_v1.revisions) == 0

    # Ingest applicable endorsement (EW-2025-01: reduces waiting period to 12 months)
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Policy_Endorsement_Schedule_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    # Replay review (Packet 2)
    pkt_v2 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v1)
    assert pkt_v2.packet_version == 2
    assert pkt_v2.run_id != pkt_v1.run_id

    # 1. Finding is revised from unresolved to supported with revision=2
    knee_f_v2 = next(f for f in pkt_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f_v2.status == "supported"
    assert knee_f_v2.revision == 2
    assert "12 continuous months" in knee_f_v2.conclusion
    assert "EW-2025-01" in knee_f_v2.conclusion

    # 2. Revision record emitted
    assert len(pkt_v2.revisions) == 1
    rev = pkt_v2.revisions[0]
    assert rev.finding_id == knee_f_v2.finding_id
    assert rev.old_finding_revision == 1
    assert rev.new_finding_revision == 2
    assert rev.old_status == "unresolved"
    assert rev.new_status == "supported"
    assert rev.trigger_type == "new_document"
    assert len(rev.triggering_evidence) > 0
    assert any(e.evidence_type == "endorsement" for e in rev.triggering_evidence)

    # 3. Missing evidence checklist item is resolved
    chk_item = next(item for item in pkt_v2.missing_evidence_checklist if "continuity" in item.item_id)
    assert chk_item.status == "resolved"
    assert "12 continuous months" in (chk_item.resolution_note or "")

    # 4. Next action updated to pre-admission estimate
    assert "hospital" in knee_f_v2.next_action.lower() or "estimate" in knee_f_v2.next_action.lower()

    # 5. Non-negotiable invariant: authorization strictly remains 'not verified'
    assert pkt_v2.authorization_status == "not verified"
    assert "guarantee" not in knee_f_v2.conclusion.lower()
    assert "claim approved" not in knee_f_v2.conclusion.lower()


# ==============================================================================
# Test 3: Wrong Policy ID Does Not Override Base Policy
# ==============================================================================
def test_wrong_policy_id_does_not_override_base_policy(replay_env):
    """Verifies that an endorsement specifying a mismatched policy ID (POL-999999 vs POL-998877)
    is marked not_applicable and does not override the base policy 24-month waiting period.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    # Ingest endorsement with wrong policy ID
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Endorsement_Wrong_Policy.pdf",
        content=build_wrong_policy_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()
    pkt = agent.run_review(case=case, retrieval=retrieval)

    # Document applicability check
    app = next((a for a in pkt.document_applicability if a.status == "not_applicable"), None)
    assert app is not None
    assert "mismatch" in app.reason.lower()
    assert "POL-999999" in app.reason

    # Base policy remains in effect: knee replacement is unresolved (24 months vs 18 months)
    knee_f = next(f for f in pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f.status == "unresolved"
    assert "24 continuous months" in knee_f.conclusion
    assert any("not applicable" in lim.lower() for lim in knee_f.limitations)


# ==============================================================================
# Test 4: Endorsement Effective After Admission Date Does Not Silently Apply
# ==============================================================================
def test_endorsement_effective_after_admission_date_does_not_apply(replay_env):
    """Verifies that an endorsement effective after the planned admission date (2026-12-01 vs 2026-11-15)
    is marked not_applicable and does not silently apply.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    # Ingest future effective endorsement
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Endorsement_Future_Effective.pdf",
        content=build_future_effective_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()
    pkt = agent.run_review(case=case, retrieval=retrieval)

    # Document applicability check
    app = next((a for a in pkt.document_applicability if a.status == "not_applicable"), None)
    assert app is not None
    assert "after planned admission date" in app.reason.lower()

    # Base policy 24 months remains in effect
    knee_f = next(f for f in pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f.status == "unresolved"
    assert "24 continuous months" in knee_f.conclusion


# ==============================================================================
# Test 5: Ambiguous Precedence Produces Unresolved / Conflict Finding
# ==============================================================================
def test_ambiguous_precedence_produces_conflict_finding(replay_env):
    """Verifies that ambiguous clause precedence or contradictory terms between
    endorsement and base policy produces an explicit conflict or unresolved finding.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    # Ingest ambiguous endorsement
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Endorsement_Ambiguous.pdf",
        content=build_ambiguous_precedence_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()
    pkt = agent.run_review(case=case, retrieval=retrieval)

    # Document applicability is uncertain
    app = next((a for a in pkt.document_applicability if a.status == "uncertain"), None)
    assert app is not None
    assert "ambiguous" in app.reason.lower() or "conflict" in app.reason.lower()

    # Finding status is conflict or unresolved with explicit explanation
    knee_f = next(f for f in pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f.status in {"conflict", "unresolved"}
    assert "conflict" in knee_f.conclusion.lower() or "precedence" in knee_f.conclusion.lower()


# ==============================================================================
# Test 6: Unrelated Findings Remain Unchanged
# ==============================================================================
def test_unrelated_findings_remain_unchanged(replay_env):
    """Verifies that when an endorsement modifies the joint replacement waiting period,
    unrelated findings (Initial 30-day waiting period, Room rent limits) remain strictly at revision=1
    with unchanged conclusions and citations.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    agent = BoundedReviewAgent()

    # Run Packet 1
    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)
    # Seed unrelated findings (30-day waiting period, room rent limits) into pkt_v1 to test preservation
    f_30d_seed = Finding(
        finding_id="find-initial-30-day-waiting-period",
        revision=1,
        topic="Initial 30-Day Waiting Period",
        status="supported",
        conclusion="Section 4.1 imposes an initial 30-day waiting period for illness-related hospitalisations.",
        evidence=[Evidence(
            document_id=replay_env["policy_doc"].document_id,
            document_version=replay_env["policy_doc"].version,
            page=9,
            quote="Section 4.1: Initial Thirty (30) Day Waiting Period for illness-related hospitalisation.",
            evidence_type="policy_wording",
        )],
        relevant_case_facts=[],
        missing_facts=[],
        limitations=["Satisfies general initial 30-day clause."],
        next_action="Continue to monitor specific condition waiting periods.",
    )
    f_rent_seed = Finding(
        finding_id="find-room-rent-limits",
        revision=1,
        topic="Room Rent and ICU Limits",
        status="supported",
        conclusion="Standard single private room covered up to 1 percent of sum insured per day.",
        evidence=[Evidence(
            document_id=replay_env["policy_doc"].document_id,
            document_version=replay_env["policy_doc"].version,
            page=3,
            quote="Section 2: Room Rent and Intensive Care Unit Limits.",
            evidence_type="policy_wording",
        )],
        relevant_case_facts=[],
        missing_facts=[],
        limitations=["Room rent capping applies proportionate deduction."],
        next_action="Confirm room category with hospital billing desk.",
    )
    pkt_v1.findings.extend([f_30d_seed, f_rent_seed])
    f_30d_v1 = f_30d_seed
    f_rent_v1 = f_rent_seed

    assert f_30d_v1 is not None
    assert f_30d_v1.revision == 1
    assert f_rent_v1 is not None
    assert f_rent_v1.revision == 1

    # Ingest endorsement modifying only joint replacement Section 4.2(b)
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Policy_Endorsement_Schedule_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    # Run Packet 2
    pkt_v2 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v1)

    f_30d_v2 = next((f for f in pkt_v2.findings if "30-day" in f.topic.lower() or "initial" in f.topic.lower()), None)
    f_rent_v2 = next((f for f in pkt_v2.findings if "room rent" in f.topic.lower()), None)

    # Unrelated findings are preserved at revision=1 with identical citations
    assert f_30d_v2 is not None
    assert f_30d_v2.revision == 1
    assert f_30d_v2.status == f_30d_v1.status
    assert f_30d_v2.conclusion == f_30d_v1.conclusion
    assert {e.quote for e in f_30d_v2.evidence} == {e.quote for e in f_30d_v1.evidence}

    assert f_rent_v2 is not None
    assert f_rent_v2.revision == 1
    assert f_rent_v2.status == f_rent_v1.status
    assert f_rent_v2.conclusion == f_rent_v1.conclusion
    assert {e.quote for e in f_rent_v2.evidence} == {e.quote for e in f_rent_v1.evidence}

    # Only joint replacement finding was revised
    assert len(pkt_v2.revisions) == 1
    assert pkt_v2.revisions[0].finding_id != f_30d_v2.finding_id
    assert pkt_v2.revisions[0].finding_id != f_rent_v2.finding_id


# ==============================================================================
# Test 7: Duplicate Input Does Not Create Duplicate Substantive Revisions
# ==============================================================================
def test_duplicate_input_does_not_create_duplicate_revisions(replay_env):
    """Verifies that running review repeatedly with identical documents and case details
    does NOT increment finding revision numbers and does NOT append redundant Revision records.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    # Ingest endorsement
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Policy_Endorsement_Schedule_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()

    # Initial run (Packet 1)
    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)
    knee_v1 = next(f for f in pkt_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_v1.revision == 1
    assert len(pkt_v1.revisions) == 0

    # Re-run with prior packet (Packet 2) -> identical input, no change!
    pkt_v2 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v1)
    knee_v2 = next(f for f in pkt_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_v2.revision == 1  # Not incremented!
    assert len(pkt_v2.revisions) == 0  # No duplicate revision emitted!


# ==============================================================================
# Test 8: Corrected Case Date Triggers Reassessment of Dependent Findings
# ==============================================================================
def test_corrected_case_date_triggers_reassessment(replay_env):
    """Verifies that correcting planned admission date from 2025-01-15 (when endorsement was not applicable)
    to 2026-11-15 triggers reassessment of dependent findings with trigger_type='case_details_changed'
    and changed_case_facts=['planned_admission_date'].
    """
    case_repo = replay_env["case_repo"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    # Case initially has planned admission date in early 2025 (before endorsement effective date 2025-04-01)
    case_early = case_repo.create_case(
        CaseDetails(
            case_id="case-m5-date-corr",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
            procedure="Total Knee Replacement",
            planned_admission_date=date(2025, 1, 15),
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "planned_admission_date": FactSource(source_type="user_provided"),
            },
        )
    )

    # Ingest policy, schedule, and endorsement
    doc_storage.save_document(
        case_id=case_early.case_id,
        filename=f"{case_early.case_id}_Policy_Wording.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )
    doc_storage.save_document(
        case_id=case_early.case_id,
        filename=f"{case_early.case_id}_Policy_Renewal_Schedule.pdf",
        content=build_synthetic_schedule_pdf(),
        evidence_type="policy_schedule",
    )
    doc_storage.save_document(
        case_id=case_early.case_id,
        filename=f"{case_early.case_id}_Policy_Endorsement_Schedule_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()

    # Run 1: Endorsement effective date (2025-04-01) is after admission date (2025-01-15) -> not applicable!
    pkt_v1 = agent.run_review(case=case_early, retrieval=retrieval)
    knee_v1 = next(f for f in pkt_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_v1.status == "unresolved"
    assert knee_v1.revision == 1

    # User corrects planned admission date to 2026-11-15 (after endorsement effective date)
    case_corrected = case_early.model_copy(
        update={
            "planned_admission_date": date(2026, 11, 15),
            "fact_sources": {
                **case_early.fact_sources,
                "planned_admission_date": FactSource(source_type="user_provided"),
            },
        }
    )
    case_repo.update_case(case_corrected)

    # Run 2: Replay review with corrected date
    pkt_v2 = agent.run_review(case=case_corrected, retrieval=retrieval, prior_packet=pkt_v1)
    assert pkt_v2.packet_version == 2

    # Finding is now supported at revision=2!
    knee_v2 = next(f for f in pkt_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_v2.status == "supported"
    assert knee_v2.revision == 2

    # Revision record emitted with trigger_type='user_correction' or 'case_details_changed'
    assert len(pkt_v2.revisions) == 1
    rev = pkt_v2.revisions[0]
    assert rev.finding_id == knee_v2.finding_id
    assert rev.old_finding_revision == 1
    assert rev.new_finding_revision == 2
    assert rev.trigger_type in {"user_correction", "case_details_changed"}
    assert "planned_admission_date" in rev.changed_case_facts


# ==============================================================================
# Test 9: Failed / Partial Reassessment Does Not Falsely Report Completion
# ==============================================================================
def test_partial_reassessment_does_not_falsely_report_completion(replay_env):
    """Verifies that when a reassessment stops early due to budget exhaustion or timeout,
    it returns review_status='incomplete' with honest stopped_reason, preserving partial findings
    and not implying the case is completely up to date.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    # Ingest endorsement
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Policy_Endorsement_Schedule_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()

    # Run 1: Normal initial run
    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)

    # Run 2: Reassessment with very tight tool budget (2 calls)
    pkt_v2 = agent.run_review(
        case=case,
        retrieval=retrieval,
        prior_packet=pkt_v1,
        tool_budget=2,
    )

    assert pkt_v2.tool_steps_used <= 2
    assert pkt_v2.review_status == "incomplete"
    assert pkt_v2.stopped_reason in {"tool_limit_reached", "missing_information"}
    assert "complete" != pkt_v2.review_status
