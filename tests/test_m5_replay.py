"""Unit and Integration Tests for Milestone M5-A and M5-I (Interface & Replay Storage).

Tests:
1. compute_evidence_replay distinguishes changed, unchanged, and new findings.
2. compute_evidence_replay increments revision by exactly 1 on change and emits Revision record.
3. compute_evidence_replay leaves unchanged findings at prior revision with 0 new revisions.
4. ReviewRepository.save_review_packet persists revisions and finding snapshots atomically.
5. ReviewRepository.get_finding_snapshot retrieves prior finding states and their evidence.
6. Transactional integrity: failed save rolls back without partial mutations.
7. Stale review protection: save_review_packet rejects stale results via StaleReviewError.
8. Duplicate document uploads do not create duplicate substantive revisions.
9. Citations link to physical pages and retain distinct old vs new document versions.
"""

from datetime import date
from decimal import Decimal
import tempfile
from pathlib import Path
import pytest

from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
)
from admitsense.review.replay import compute_evidence_replay
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


@pytest.fixture
def m5_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m5.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        review_repo = ReviewRepository(db=db)
        retrieval = SqliteEvidenceRetrieval(db=db)

        # Create base test case
        case = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-test-01",
                member_name="Ramesh Sharma",
                procedure="Total Knee Replacement",
                policy_age_months=18,
                planned_admission_date=date(2026, 11, 1),
                fact_sources={
                    "member_name": FactSource(source_type="user_provided"),
                    "procedure": FactSource(source_type="user_provided"),
                    "policy_age_months": FactSource(source_type="user_provided"),
                    "planned_admission_date": FactSource(source_type="user_provided"),
                },
            )
        )

        yield {
            "db": db,
            "db_path": db_path,
            "case": case,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "review_repo": review_repo,
            "retrieval": retrieval,
        }


def test_compute_evidence_replay_categorization():
    """Verify compute_evidence_replay distinguishes changed, unchanged, and new findings."""
    f_old1 = Finding(
        finding_id="find-waiting-period",
        revision=1,
        topic="Specific Condition Waiting Period",
        status="unresolved",
        conclusion="Shortfall of 6 months remaining under Section 4.2(b).",
        evidence=[
            Evidence(
                document_id="doc-policy",
                document_version="v1",
                page=14,
                quote="Section 4.2(b): Waiting period of 24 months.",
                evidence_type="policy_wording",
            )
        ],
        relevant_case_facts=["procedure"],
        missing_facts=["continuous_coverage_start_date"],
        limitations=["6-month gap"],
        next_action="Obtain continuity proof.",
    )

    f_old2 = Finding(
        finding_id="find-initial-waiting",
        revision=1,
        topic="Initial 30-Day Waiting Period",
        status="supported",
        conclusion="Initial 30-day waiting period satisfied.",
        evidence=[
            Evidence(
                document_id="doc-policy",
                document_version="v1",
                page=9,
                quote="Section 4.1: Initial 30-day period.",
                evidence_type="policy_wording",
            )
        ],
        relevant_case_facts=["policy_start_date"],
        next_action="Confirm admission date.",
    )

    prior_packet = ReviewPacket(
        packet_id="pkt-test-01",
        packet_version=1,
        run_id="run-01",
        case=CaseDetails(case_id="case-01"),
        review_status="incomplete",
        findings=[f_old1, f_old2],
        revisions=[],
        missing_evidence_checklist=[],
        unresolved_questions=[],
        authorization_status="not verified",
        tool_steps_used=2,
        stopped_reason="missing_information",
    )

    # 1. Candidate where find-waiting-period changed to supported via endorsement
    endorsement_ev = Evidence(
        document_id="doc-endorsement",
        document_version="v1",
        page=1,
        quote="Endorsement EW-01: Waiting period reduced to 12 months.",
        evidence_type="endorsement",
    )
    f_cand_changed = Finding(
        finding_id="find-waiting-period",
        revision=1,
        topic="Specific Condition Waiting Period",
        status="supported",
        conclusion="12-month waiting period satisfied by 18 months continuous coverage.",
        evidence=[endorsement_ev],
        relevant_case_facts=["procedure"],
        next_action="Obtain hospital estimate.",
    )

    # 2. Candidate where find-initial-waiting is completely unchanged
    f_cand_unchanged = f_old2.model_copy()

    # 3. New candidate finding
    f_cand_new = Finding(
        finding_id="find-room-rent",
        revision=1,
        topic="Room Rent Limit",
        status="supported",
        conclusion="Room rent covered up to 1% of Sum Insured.",
        evidence=[
            Evidence(
                document_id="doc-policy",
                document_version="v1",
                page=3,
                quote="Section 2.1: Room rent 1% limit.",
                evidence_type="policy_wording",
            )
        ],
        next_action="Select room category accordingly.",
    )

    updated_findings, revisions = compute_evidence_replay(
        prior_packet=prior_packet,
        new_findings=[f_cand_changed, f_cand_unchanged, f_cand_new],
        trigger_type="new_document",
        triggering_evidence=[endorsement_ev],
        reason="Uploaded endorsement EW-01 reduced waiting period to 12 months.",
    )

    assert len(updated_findings) == 3
    assert len(revisions) == 1

    # Check changed finding
    f_res_changed = next(f for f in updated_findings if f.finding_id == "find-waiting-period")
    assert f_res_changed.revision == 2
    assert f_res_changed.status == "supported"

    # Check unchanged finding: revision stayed 1
    f_res_unchanged = next(f for f in updated_findings if f.finding_id == "find-initial-waiting")
    assert f_res_unchanged.revision == 1
    assert f_res_unchanged.status == "supported"

    # Check new finding: revision starts at 1
    f_res_new = next(f for f in updated_findings if f.finding_id == "find-room-rent")
    assert f_res_new.revision == 1

    # Check Revision log details
    rev = revisions[0]
    assert rev.finding_id == "find-waiting-period"
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

    # Save packet v1
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

    # Save packet v2 with revision
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
        next_action="Proceed to pre-auth",
    )
    rev_1_to_2 = Revision(
        revision_id="rev-001",
        finding_id="find-knee",
        old_finding_revision=1,
        new_finding_revision=2,
        old_status="unresolved",
        new_status="supported",
        old_conclusion="Shortfall of 6 months",
        new_conclusion="12-month period satisfied",
        trigger_type="new_document",
        triggering_evidence=[ev_v2],
        reason="Endorsement uploaded",
        affected_topics=["Waiting Period"],
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
    assert old_snap.evidence[0].page == 14

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

    # Initial packet v1
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

    # Another session updates case to packet v2
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

    # Now a stale execution attempting to save based on expected_prior_packet_version=1 must be REJECTED!
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

    # Verify latest packet remains p2
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

    # Create a corrupted packet that will violate foreign keys or cause a database error
    # E.g. targeting a non-existent case_id in the inner case model
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

    # Previous review for our case must remain intact!
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

    # 1. Ingest base policy
    policy_pdf = build_synthetic_policy_pdf()
    doc_v1, is_dup1 = doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Policy.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup1 is False
    assert doc_v1.version == "v1"

    # 2. Duplicate upload of base policy
    doc_dup, is_dup2 = doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Policy.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup2 is True
    assert doc_dup.version == "v1"

    # 3. Initial review using FixtureReviewRunner
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
    assert pkt1.findings[0].status == "unresolved"

    # 4. Ingest new endorsement document
    end_pdf = build_synthetic_endorsement_pdf()
    doc_end, is_dup3 = doc_storage.save_document(
        case_id=case.case_id,
        filename="Joint_Replacement_Endorsement.pdf",
        content=end_pdf,
        evidence_type="endorsement",
    )
    assert is_dup3 is False
    assert doc_end.version == "v1"

    # Older document v1 remains accessible!
    old_doc = doc_storage.get_document(doc_v1.document_id, "v1")
    assert old_doc is not None
    assert old_doc.total_pages == 15

    # 5. Re-review evaluates endorsement: revises finding to supported and emits 1 Revision
    pkt2 = service.execute_review(case.case_id)
    assert pkt2.packet_version == 2
    assert len(pkt2.revisions) == 1
    assert pkt2.findings[0].revision == 2
    assert pkt2.findings[0].status == "supported"
    assert pkt2.revisions[0].trigger_type == "new_document"
    assert pkt2.revisions[0].triggering_evidence[0].document_id == doc_end.document_id

    # 6. Re-review again without new evidence (duplicate review or re-run)
    # Must NOT create duplicate substantive revisions!
    pkt3 = service.execute_review(case.case_id)
    assert pkt3.packet_version == 3
    # Accumulated revisions remain 1 (no duplicate revision added)
    assert len(pkt3.revisions) == 1
    assert pkt3.findings[0].revision == 2
    assert pkt3.findings[0].status == "supported"
