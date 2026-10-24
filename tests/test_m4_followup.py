"""Unit and integration tests for Milestone M4-A and M4-I (Bounded Agent & User Follow-Up)."""

from datetime import date
from decimal import Decimal
import tempfile
from pathlib import Path
import pytest

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import WaitingPeriodReviewer
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import build_synthetic_policy_pdf
from admitsense.review.service import ReviewService
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository


@pytest.fixture
def m4_setup():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m4.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        retrieval = EvidenceRetrievalService(db=db)
        review_repo = ReviewRepository(db=db)
        reviewer = WaitingPeriodReviewer(default_tool_budget=8)
        review_service = ReviewService(
            case_repo=case_repo,
            review_repo=review_repo,
            retrieval=retrieval,
            runner=reviewer,
        )
        yield {
            "db": db,
            "db_path": db_path,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "retrieval": retrieval,
            "review_repo": review_repo,
            "reviewer": reviewer,
            "review_service": review_service,
        }


def test_activity_telemetry_stream_and_persistence(m4_setup):
    """Verify tool activity events are streamed in real time and persisted in SQLite."""
    service: ReviewService = m4_setup["review_service"]
    case_repo: CaseRepository = m4_setup["case_repo"]
    doc_storage: DocumentStorage = m4_setup["doc_storage"]
    review_repo: ReviewRepository = m4_setup["review_repo"]

    # 1. Create case & ingest policy
    case = case_repo.create_case(
        CaseDetails(
            case_id="case-m4-telemetry",
            member_name="Ananya Verma",
            procedure="Total Knee Replacement",
            policy_age_months=18,
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "policy_age_months": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )

    # 2. Run review with event callback
    streamed_events = []
    def on_event(evt):
        streamed_events.append(evt)

    packet = service.execute_review(case.case_id, event_callback=on_event)
    assert packet is not None
    assert len(streamed_events) > 0
    assert packet.tool_steps_used <= 8

    # 3. Verify real tool events were captured
    first_event = streamed_events[0]
    assert hasattr(first_event, "tool_name")
    assert first_event.tool_name in ("search_pages", "read_page", "verify_citation")
    assert hasattr(first_event, "summary")
    assert len(first_event.summary) > 0

    # 4. Verify persisted in SQLite
    persisted_events = review_repo.list_activity_events(run_id=packet.run_id)
    assert len(persisted_events) == len(streamed_events)
    assert persisted_events[0]["tool_name"] == first_event.tool_name
    assert persisted_events[0]["step_number"] == 1


def test_user_answers_missing_facts_and_provenance(m4_setup):
    """Verify user can provide missing case facts, recording user_provided provenance."""
    service: ReviewService = m4_setup["review_service"]
    case_repo: CaseRepository = m4_setup["case_repo"]
    doc_storage: DocumentStorage = m4_setup["doc_storage"]
    review_repo: ReviewRepository = m4_setup["review_repo"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-m4-answers",
            member_name="Vikram Singh",
            procedure="Total Knee Replacement",
            policy_age_months=18,
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "policy_age_months": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )

    # Initial review: 18 months vs 24 months -> unresolved
    packet_v1 = service.execute_review(case.case_id)
    assert packet_v1.review_status == "incomplete"
    assert packet_v1.findings[0].status == "unresolved"

    # User answers follow-up by providing continuous coverage start date & 24 months coverage
    updated_case = case.model_copy()
    updated_case.continuous_coverage_start_date = date(2024, 1, 1)
    updated_case.policy_age_months = 24
    updated_case.fact_sources["continuous_coverage_start_date"] = FactSource(source_type="user_provided")
    updated_case.fact_sources["policy_age_months"] = FactSource(source_type="user_provided")
    case_repo.update_case(updated_case)

    # Update checklist item to provided_pending_review
    review_repo.update_checklist_item_status(
        case_id=case.case_id,
        item_id=packet_v1.missing_evidence_checklist[0].item_id,
        status="provided_pending_review",
        resolution_note="User provided 24-month continuous coverage certificate dates.",
    )

    # Reload case and verify provenance
    reloaded_case = case_repo.get_case(case.case_id)
    assert reloaded_case.continuous_coverage_start_date == date(2024, 1, 1)
    assert reloaded_case.policy_age_months == 24
    assert reloaded_case.fact_sources["continuous_coverage_start_date"].source_type == "user_provided"

    # Resume review (creates explicit new run)
    packet_v2 = service.execute_review(case.case_id)
    assert packet_v2.packet_version == 2
    assert packet_v2.run_id != packet_v1.run_id
    assert packet_v2.review_status == "complete"
    assert packet_v2.findings[0].status == "supported"


def test_i_dont_have_this_survives_refresh_and_keeps_unresolved(m4_setup):
    """Verify 'I don't have this' survives restart and keeps finding unresolved."""
    service: ReviewService = m4_setup["review_service"]
    case_repo: CaseRepository = m4_setup["case_repo"]
    doc_storage: DocumentStorage = m4_setup["doc_storage"]
    review_repo: ReviewRepository = m4_setup["review_repo"]
    db_path = m4_setup["db_path"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-m4-dont-have",
            member_name="Sunita Rao",
            procedure="Total Knee Replacement",
            policy_age_months=18,
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "policy_age_months": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )

    packet_v1 = service.execute_review(case.case_id)
    chk_item = packet_v1.missing_evidence_checklist[0]

    # User clicks "I don't have this"
    review_repo.update_checklist_item_status(
        case_id=case.case_id,
        item_id=chk_item.item_id,
        status="user_does_not_have",
        resolution_note="Caregiver confirmed no prior insurance portability documents exist.",
    )

    # Simulate restart by reconnecting to SQLite
    db_restart = Database(db_path=db_path)
    restart_repo = ReviewRepository(db=db_restart)
    reloaded_packet = restart_repo.get_latest_review_packet(case.case_id)

    assert reloaded_packet is not None
    assert reloaded_packet.missing_evidence_checklist[0].status == "user_does_not_have"

    # Resume review with restart repo
    restart_service = ReviewService(
        case_repo=CaseRepository(db=db_restart),
        review_repo=restart_repo,
        retrieval=EvidenceRetrievalService(db=db_restart),
        runner=WaitingPeriodReviewer(default_tool_budget=8),
    )
    packet_v2 = restart_service.execute_review(case.case_id)

    # Invariant: status is preserved across resume, and finding stays unresolved
    assert packet_v2.missing_evidence_checklist[0].status == "user_does_not_have"
    assert packet_v2.findings[0].status == "unresolved"
    assert packet_v2.authorization_status == "not verified"


def test_resume_creates_explicit_new_run_retaining_history(m4_setup):
    """Verify resuming review creates an explicit new run and retains historical runs."""
    service: ReviewService = m4_setup["review_service"]
    case_repo: CaseRepository = m4_setup["case_repo"]
    doc_storage: DocumentStorage = m4_setup["doc_storage"]
    review_repo: ReviewRepository = m4_setup["review_repo"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-m4-runs",
            member_name="Deepak Joshi",
            procedure="Total Knee Replacement",
            policy_age_months=18,
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "policy_age_months": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )

    # Run 1
    p1 = service.execute_review(case.case_id)
    assert p1.packet_version == 1

    # Run 2 (resume)
    p2 = service.execute_review(case.case_id)
    assert p2.packet_version == 2
    assert p2.run_id != p1.run_id

    # Run 3 (resume)
    p3 = service.execute_review(case.case_id)
    assert p3.packet_version == 3
    assert p3.run_id != p2.run_id

    # Verify all 3 runs retained in SQLite
    all_runs = review_repo.list_review_packets(case.case_id)
    assert len(all_runs) == 3
    assert all_runs[0].packet_version == 3
    assert all_runs[1].packet_version == 2
    assert all_runs[2].packet_version == 1


def test_tool_budget_exhaustion_honest_partial_results(m4_setup):
    """Verify tool budget capping (<= 8) returns partial results with tool_limit_reached."""
    service: ReviewService = m4_setup["review_service"]
    case_repo: CaseRepository = m4_setup["case_repo"]
    doc_storage: DocumentStorage = m4_setup["doc_storage"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-m4-budget",
            member_name="Pooja Mehta",
            procedure="Total Knee Replacement",
            policy_age_months=18,
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "policy_age_months": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )

    # Force a very tight tool budget of 2 calls
    packet = service.execute_review(case.case_id, tool_budget=2)
    assert packet.tool_steps_used <= 2
    assert packet.stopped_reason == "tool_limit_reached"
    assert packet.review_status == "incomplete"
    assert len(packet.findings) >= 1
    print(f"  [PASS] Budget capped: used {packet.tool_steps_used} steps, stop_reason='{packet.stopped_reason}'")
