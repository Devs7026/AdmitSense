"""Combined Test Suite for Milestone M5: Evidence Change Replay (M5-A, M5-B, M5-I).

Covers:
Part 1 (M5-A & Replay Storage):
- compute_evidence_replay categories (changed, unchanged, new findings)
- Atomic transactional persistence of packets, findings, revisions, checklist
- Immutable historical finding snapshots via get_finding_snapshot
- Stale review protection via StaleReviewError
- Transactional rollback on failed save
- Non-destructive new evidence upload and version tracking

Part 2 (M5-B & Live Review Agent Replay):
- Applicable endorsement reduces 24-month waiting period to 12 months
- Supplied 18-month history supports only narrow finding without overall claim approval
- Wrong policy ID does not override base policy
- Endorsement effective after planned admission date does not apply
- Ambiguous precedence produces conflict finding with uncertainty retained
- Unrelated findings remain unchanged across replay
- Duplicate input does not create duplicate substantive revisions
- Corrected case date triggers reassessment of dependent findings
- Partial reassessment does not falsely report completion
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import pytest

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import (
    BoundedReviewAgent,
    compute_evidence_replay,
)
from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    generate_pdf_bytes,
)
from admitsense.review.service import FixtureReviewRunner, ReviewService
from admitsense.schemas import (
    CaseDetails,
    Evidence,
    FactSource,
    Finding,
    MissingEvidenceItem,
    ReviewPacket,
    Revision,
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository, StaleReviewError


# ==============================================================================
# Fixtures
# ==============================================================================
@pytest.fixture
def m5_env():
    """Isolated environment for M5-A storage, repository, and service tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m5_storage.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        review_repo = ReviewRepository(db=db)
        retrieval = SqliteEvidenceRetrieval(db=db)

        case = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-storage-001",
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

        yield {
            "db": db,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "review_repo": review_repo,
            "retrieval": retrieval,
            "case": case,
        }


@pytest.fixture
def replay_env():
    """Isolated environment with synthetic documents for M5-B live review agent tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m5_agent.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)

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

        policy_doc, _ = doc_storage.save_document(
            case_id=case.case_id,
            filename=f"{case.case_id}_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )

        sched_doc, _ = doc_storage.save_document(
            case_id=case.case_id,
            filename=f"{case.case_id}_Policy_Renewal_Schedule.pdf",
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
# Part 1: M5-A & Replay Storage Tests (Owner A)
# ==============================================================================
def test_compute_evidence_replay_finding_categories_and_revisions(m5_env):
    """Verify compute_evidence_replay categorizes changed, unchanged, and new findings,
    incrementing revision by exactly 1 on change and emitting 0 revisions for unchanged findings.
    """
    case: CaseDetails = m5_env["case"]

    ev_policy = Evidence(
        document_id="doc-policy",
        document_version="v1",
        page=14,
        quote="Section 4.2(b): Joint replacement subject to 24 continuous months waiting period.",
        evidence_type="policy_wording",
    )
    f_knee_v1 = Finding(
        finding_id="find-knee",
        revision=1,
        topic="Specific Waiting Period: Joint Replacement",
        status="unresolved",
        conclusion="Shortfall of 6 months.",
        evidence=[ev_policy],
        limitations=["Waiting period shortfall exists."],
        next_action="Obtain endorsement or clarification.",
    )
    f_initial_30d = Finding(
        finding_id="find-30d",
        revision=1,
        topic="Initial 30-Day Waiting Period",
        status="supported",
        conclusion="Initial 30-day period satisfied.",
        evidence=[ev_policy],
        limitations=[],
        next_action="Monitor specific waiting periods.",
    )

    prior_packet = ReviewPacket(
        packet_id="pkt-v1",
        packet_version=1,
        run_id="run-01",
        case=case,
        review_status="incomplete",
        findings=[f_knee_v1, f_initial_30d],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=4,
        stopped_reason="missing_information",
    )

    # Candidate findings for replay:
    # 1. f_knee revised to supported (changed)
    # 2. f_30d unchanged (identical status and conclusion)
    # 3. f_room_rent new (newly introduced finding)
    ev_end = Evidence(
        document_id="doc-endorsement",
        document_version="v1",
        page=1,
        quote="Waiting period reduced to 12 continuous months.",
        evidence_type="endorsement",
    )
    f_knee_cand = Finding(
        finding_id="find-knee",
        revision=1,  # Candidate starts with 1 before delta computation
        topic="Specific Waiting Period: Joint Replacement",
        status="supported",
        conclusion="Waiting period of 12 continuous months satisfied.",
        evidence=[ev_end],
        limitations=[],
        next_action="Confirm pre-admission estimate.",
    )
    f_30d_cand = Finding(
        finding_id="find-30d",
        revision=1,
        topic="Initial 30-Day Waiting Period",
        status="supported",
        conclusion="Initial 30-day period satisfied.",
        evidence=[ev_policy],
        limitations=[],
        next_action="Monitor specific waiting periods.",
    )
    f_room_rent = Finding(
        finding_id="find-rent",
        revision=1,
        topic="Room Rent Limits",
        status="supported",
        conclusion="Room rent capped at 1% sum insured.",
        evidence=[ev_policy],
        limitations=[],
        next_action="Check room tariff with hospital.",
    )

    updated_findings, all_revisions = compute_evidence_replay(
        prior_packet=prior_packet,
        new_findings=[f_knee_cand, f_30d_cand, f_room_rent],
        trigger_type="new_document",
        triggering_evidence=[ev_end],
        reason="Applicable endorsement reduces waiting period.",
    )

    # Verify updated findings count and revisions
    assert len(updated_findings) == 3
    knee_res = next(f for f in updated_findings if f.finding_id == "find-knee")
    assert knee_res.revision == 2
    assert knee_res.status == "supported"

    d30_res = next(f for f in updated_findings if f.finding_id == "find-30d")
    assert d30_res.revision == 1
    assert d30_res.status == "supported"

    rent_res = next(f for f in updated_findings if f.finding_id == "find-rent")
    assert rent_res.revision == 1

    assert len(all_revisions) == 1
    rev = all_revisions[0]
    assert rev.finding_id == "find-knee"
    assert rev.old_finding_revision == 1
    assert rev.new_finding_revision == 2
    assert rev.old_status == "unresolved"
    assert rev.new_status == "supported"
    assert rev.trigger_type == "new_document"
    assert len(rev.triggering_evidence) == 1
    assert rev.triggering_evidence[0].document_id == "doc-endorsement"


def test_review_repository_atomic_revisions_and_finding_snapshots(m5_env):
    """Verify ReviewRepository saves packets atomically and get_finding_snapshot retrieves historical states."""
    repo: ReviewRepository = m5_env["review_repo"]
    case: CaseDetails = m5_env["case"]

    ev_v1 = Evidence(
        document_id="doc-policy",
        document_version="v1",
        page=14,
        quote="24-month waiting clause",
        evidence_type="policy_wording",
    )
    f_v1 = Finding(
        finding_id="find-knee",
        revision=1,
        topic="Waiting Period",
        status="unresolved",
        conclusion="Shortfall of 6 months",
        evidence=[ev_v1],
        limitations=["Shortfall exists"],
        next_action="Request waiver",
    )

    pkt_v1 = ReviewPacket(
        packet_id="pkt-m5-v1",
        packet_version=1,
        run_id="run-m5-01",
        case=case,
        review_status="incomplete",
        findings=[f_v1],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=3,
        stopped_reason="missing_information",
    )
    repo.save_review_packet(pkt_v1)

    ev_v2 = Evidence(
        document_id="doc-endorsement",
        document_version="v1",
        page=1,
        quote="12-month waiting clause",
        evidence_type="endorsement",
    )
    f_v2 = Finding(
        finding_id="find-knee",
        revision=2,
        topic="Waiting Period",
        status="supported",
        conclusion="12-month period satisfied",
        evidence=[ev_v2],
        limitations=[],
        next_action="Confirm hospital estimate",
    )
    rev_1_to_2 = Revision(
        revision_id="rev-001",
        finding_id="find-knee",
        old_finding_revision=1,
        new_finding_revision=2,
        old_conclusion="Shortfall of 6 months",
        new_conclusion="12-month period satisfied",
        old_status="unresolved",
        new_status="supported",
        trigger_type="new_document",
        triggering_evidence=[ev_v2],
        reason="Endorsement applied",
        affected_topics=["Waiting Period"],
        created_at=datetime.now(timezone.utc),
    )

    pkt_v2 = ReviewPacket(
        packet_id="pkt-m5-v2",
        packet_version=2,
        run_id="run-m5-02",
        case=case,
        review_status="complete",
        findings=[f_v2],
        revisions=[rev_1_to_2],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=2,
        stopped_reason="review_complete",
    )
    repo.save_review_packet(pkt_v2, expected_prior_packet_version=1)

    # 1. Verify get_finding_snapshot retrieves historical state
    old_snap = repo.get_finding_snapshot(case.case_id, "find-knee", revision=1)
    assert old_snap is not None
    assert old_snap.revision == 1
    assert old_snap.status == "unresolved"
    assert old_snap.conclusion == "Shortfall of 6 months"
    assert old_snap.evidence[0].document_id == "doc-policy"

    # 2. Verify get_finding_snapshot retrieves new state
    new_snap = repo.get_finding_snapshot(case.case_id, "find-knee", revision=2)
    assert new_snap is not None
    assert new_snap.revision == 2
    assert new_snap.status == "supported"
    assert new_snap.conclusion == "12-month period satisfied"
    assert new_snap.evidence[0].document_id == "doc-endorsement"

    # 3. Verify get_finding_history
    history = repo.get_finding_history(case.case_id, "find-knee")
    assert len(history) == 1
    assert history[0].old_finding_revision == 1
    assert history[0].new_finding_revision == 2

    # 4. Verify list_all_revisions
    all_revs = repo.list_all_revisions(case.case_id)
    assert len(all_revs) == 1


def test_stale_review_rejection_prevents_overwrite(m5_env):
    """Verify StaleReviewError is raised when saving against an outdated expected prior version."""
    repo: ReviewRepository = m5_env["review_repo"]
    case: CaseDetails = m5_env["case"]

    p1 = ReviewPacket(
        packet_id="pkt-p1",
        packet_version=1,
        run_id="run-p1",
        case=case,
        review_status="incomplete",
        findings=[],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=1,
        stopped_reason="missing_information",
    )
    repo.save_review_packet(p1)

    p2 = ReviewPacket(
        packet_id="pkt-p2",
        packet_version=2,
        run_id="run-p2",
        case=case,
        review_status="incomplete",
        findings=[],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=2,
        stopped_reason="missing_information",
    )
    repo.save_review_packet(p2, expected_prior_packet_version=1)

    stale_p = ReviewPacket(
        packet_id="pkt-stale",
        packet_version=2,
        run_id="run-stale",
        case=case,
        review_status="incomplete",
        findings=[],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=1,
        stopped_reason="timeout",
    )

    with pytest.raises(StaleReviewError) as exc_info:
        repo.save_review_packet(stale_p, expected_prior_packet_version=1)

    assert "Stale review rejected" in str(exc_info.value)

    latest = repo.get_latest_review_packet(case.case_id)
    assert latest is not None
    assert latest.packet_id == "pkt-p2"
    assert latest.packet_version == 2


def test_failed_save_leaves_previous_review_intact(m5_env):
    """Verify transactional rollback: a failing review save leaves the previous review intact."""
    repo: ReviewRepository = m5_env["review_repo"]
    case: CaseDetails = m5_env["case"]

    p1 = ReviewPacket(
        packet_id="pkt-good-01",
        packet_version=1,
        run_id="run-good-01",
        case=case,
        review_status="incomplete",
        findings=[],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=1,
        stopped_reason="missing_information",
    )
    repo.save_review_packet(p1)

    corrupted_packet = ReviewPacket(
        packet_id="pkt-bad-02",
        packet_version=2,
        run_id="run-bad-02",
        case=CaseDetails(case_id="case-NONEXISTENT-FOREIGN-KEY"),
        review_status="incomplete",
        findings=[],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=2,
        stopped_reason="missing_information",
    )

    with pytest.raises(Exception):
        repo.save_review_packet(corrupted_packet)

    latest = repo.get_latest_review_packet(case.case_id)
    assert latest is not None
    assert latest.packet_id == "pkt-good-01"
    assert latest.packet_version == 1


def test_new_evidence_immutable_versions_and_duplicate_handling(m5_env):
    """Verify uploading new evidence does not replace older versions and duplicate uploads do not create duplicate revisions."""
    doc_storage: DocumentStorage = m5_env["doc_storage"]
    case: CaseDetails = m5_env["case"]
    repo: ReviewRepository = m5_env["review_repo"]
    retrieval = m5_env["retrieval"]

    policy_pdf = build_synthetic_policy_pdf()
    doc_v1, is_dup1 = doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Policy.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup1 is False
    assert doc_v1.version == "v1"

    doc_dup, is_dup2 = doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Policy.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup2 is True
    assert doc_dup.version == "v1"

    service = ReviewService(
        case_repo=m5_env["case_repo"],
        review_repo=repo,
        retrieval=retrieval,
        runner=FixtureReviewRunner(),
    )
    pkt1 = service.execute_review(case.case_id)
    assert pkt1.packet_version == 1
    assert len(pkt1.revisions) == 0
    assert pkt1.findings[0].revision == 1

    end_pdf = build_synthetic_endorsement_pdf()
    doc_end, is_dup3 = doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement.pdf",
        content=end_pdf,
        evidence_type="endorsement",
    )
    assert is_dup3 is False
    assert doc_end.version == "v1"

    old_doc = doc_storage.get_document(doc_v1.document_id, "v1")
    assert old_doc is not None
    assert old_doc.total_pages == 15

    pkt2 = service.execute_review(case.case_id)
    assert pkt2.packet_version == 2
    assert len(pkt2.revisions) == 1
    assert pkt2.findings[0].revision == 2
    assert pkt2.findings[0].status == "supported"

    pkt3 = service.execute_review(case.case_id)
    assert pkt3.packet_version == 3
    assert len(pkt3.revisions) == 1
    assert pkt3.findings[0].revision == 2


# ==============================================================================
# Part 2: M5-B & Live Review Agent Replay Tests (Owner B)
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

    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)
    assert pkt_v1.packet_version == 1
    knee_f_v1 = next(f for f in pkt_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f_v1.status == "unresolved"
    assert knee_f_v1.revision == 1
    assert "shortfall" in knee_f_v1.conclusion.lower()
    assert len(pkt_v1.revisions) == 0

    doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    pkt_v2 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v1)
    assert pkt_v2.packet_version == 2
    assert pkt_v2.run_id != pkt_v1.run_id

    knee_f_v2 = next(f for f in pkt_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f_v2.status == "supported"
    assert knee_f_v2.revision == 2
    assert "12 continuous months" in knee_f_v2.conclusion
    assert "EW-2025-01" in knee_f_v2.conclusion

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

    chk_item = next(item for item in pkt_v2.missing_evidence_checklist if "continuity" in item.item_id)
    assert chk_item.status == "resolved"
    assert "12 continuous months" in (chk_item.resolution_note or "")

    assert "hospital" in knee_f_v2.next_action.lower() or "estimate" in knee_f_v2.next_action.lower()
    assert pkt_v2.authorization_status == "not verified"
    assert "guarantee" not in knee_f_v2.conclusion.lower()
    assert "claim approved" not in knee_f_v2.conclusion.lower()


def test_wrong_policy_id_does_not_override_base_policy(replay_env):
    """Verifies that an endorsement specifying a different Policy ID is evaluated as not_applicable,
    retaining the base policy 24-month waiting period without overriding it.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    wrong_pdf = generate_pdf_bytes([
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-WRONG-01. "
        "Applicable to Policy ID: POL-DIFFERENT-999. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
        "Waiting Period Modification: Joint replacement waiting period reduced to twelve (12) continuous months."
    ])
    doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement_Wrong_Policy.pdf",
        content=wrong_pdf,
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()
    packet = agent.run_review(case=case, retrieval=retrieval)

    knee_finding = next(f for f in packet.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_finding.status == "unresolved"
    assert "24" in knee_finding.conclusion or "twenty-four" in knee_finding.conclusion
    assert any("mismatch" in lim.lower() for lim in knee_finding.limitations)


def test_endorsement_effective_after_admission_date_does_not_apply(replay_env):
    """Verifies that an endorsement whose effective date is after planned admission date
    does not silently apply, and base policy terms remain in effect.
    """
    case_repo = replay_env["case_repo"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    case_future = case_repo.create_case(
        CaseDetails(
            case_id="case-m5-future-test",
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

    doc_storage.save_document(case_id=case_future.case_id, filename=f"{case_future.case_id}_pol.pdf", content=build_synthetic_policy_pdf(), evidence_type="policy_wording")
    doc_storage.save_document(case_id=case_future.case_id, filename=f"{case_future.case_id}_sched.pdf", content=build_synthetic_schedule_pdf(), evidence_type="policy_schedule")
    doc_storage.save_document(case_id=case_future.case_id, filename=f"{case_future.case_id}_end.pdf", content=build_synthetic_endorsement_pdf(), evidence_type="endorsement")

    agent = BoundedReviewAgent()
    packet = agent.run_review(case=case_future, retrieval=retrieval)

    knee_f = next(f for f in packet.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f.status == "unresolved"
    assert any("after planned admission date" in lim.lower() for lim in knee_f.limitations)


def test_ambiguous_precedence_produces_conflict_finding(replay_env):
    """Verifies that contradictory terms with ambiguous priority language produce an unresolved/conflict finding."""
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    ambig_pdf = generate_pdf_bytes([
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. "
        "Applicable to Policy ID: POL-998877. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
        "Waiting Period Modification: Section 4.2(b) waiting period modified to twelve (12) continuous months, "
        "however precedence unresolved: terms conflict with master policy schedule pending underwriter review."
    ])
    doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement_Ambiguous.pdf",
        content=ambig_pdf,
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()
    packet = agent.run_review(case=case, retrieval=retrieval)

    knee_f = next(f for f in packet.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_f.status == "conflict"
    assert "conflict" in knee_f.conclusion.lower() or "ambiguous" in knee_f.conclusion.lower()


def test_unrelated_findings_remain_unchanged(replay_env):
    """Verifies that when an endorsement modifies the joint replacement waiting period,
    unrelated findings remain strictly at revision=1 with unchanged conclusions and citations.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    agent = BoundedReviewAgent()

    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)

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

    doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    pkt_v2 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v1)

    f_30d_v2 = next((f for f in pkt_v2.findings if f.finding_id == "find-initial-30-day-waiting-period"), None)
    f_rent_v2 = next((f for f in pkt_v2.findings if f.finding_id == "find-room-rent-limits"), None)

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

    assert len(pkt_v2.revisions) == 1
    assert pkt_v2.revisions[0].finding_id != f_30d_v2.finding_id
    assert pkt_v2.revisions[0].finding_id != f_rent_v2.finding_id


def test_duplicate_input_does_not_create_duplicate_revisions(replay_env):
    """Verifies that running review repeatedly with identical documents and case details
    does NOT increment finding revision numbers and does NOT append redundant Revision records.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    agent = BoundedReviewAgent()

    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)
    f_v1 = pkt_v1.findings[0]
    assert f_v1.revision == 1
    assert len(pkt_v1.revisions) == 0

    doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    pkt_v2 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v1)
    f_v2 = next(f for f in pkt_v2.findings if f.finding_id == f_v1.finding_id)
    assert f_v2.revision == 2
    assert len(pkt_v2.revisions) == 1

    pkt_v3 = agent.run_review(case=case, retrieval=retrieval, prior_packet=pkt_v2)
    f_v3 = next(f for f in pkt_v3.findings if f.finding_id == f_v1.finding_id)
    assert f_v3.revision == 2
    assert len(pkt_v3.revisions) == 1


def test_corrected_case_date_triggers_reassessment(replay_env):
    """Verifies that correcting planned admission date from 2025-01-15 (when endorsement was not applicable)
    to 2026-11-15 triggers reassessment of dependent findings with trigger_type='case_details_changed'
    and changed_case_facts=['planned_admission_date'].
    """
    case_repo = replay_env["case_repo"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

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

    pkt_v1 = agent.run_review(case=case_early, retrieval=retrieval)
    knee_v1 = next(f for f in pkt_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_v1.status == "unresolved"
    assert knee_v1.revision == 1

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

    pkt_v2 = agent.run_review(case=case_corrected, retrieval=retrieval, prior_packet=pkt_v1)
    assert pkt_v2.packet_version == 2

    knee_v2 = next(f for f in pkt_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
    assert knee_v2.status == "supported"
    assert knee_v2.revision == 2

    assert len(pkt_v2.revisions) == 1
    rev = pkt_v2.revisions[0]
    assert rev.finding_id == knee_v2.finding_id
    assert rev.old_finding_revision == 1
    assert rev.new_finding_revision == 2
    assert rev.trigger_type in {"user_correction", "case_details_changed"}
    assert "planned_admission_date" in rev.changed_case_facts


def test_partial_reassessment_does_not_falsely_report_completion(replay_env):
    """Verifies that when a reassessment stops early due to budget exhaustion or timeout,
    it returns review_status='incomplete' with honest stopped_reason, preserving partial findings
    and not implying the case is completely up to date.
    """
    case = replay_env["case"]
    retrieval = replay_env["retrieval"]
    doc_storage = replay_env["doc_storage"]

    doc_storage.save_document(
        case_id=case.case_id,
        filename=f"{case.case_id}_Endorsement_EW-2025-01.pdf",
        content=build_synthetic_endorsement_pdf(),
        evidence_type="endorsement",
    )

    agent = BoundedReviewAgent()

    pkt_v1 = agent.run_review(case=case, retrieval=retrieval)

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
