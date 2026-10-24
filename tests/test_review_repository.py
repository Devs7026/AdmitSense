"""Tests for AdmitSense SQLite ReviewRepository."""

import tempfile
from pathlib import Path
import pytest

from admitsense.storage.database import Database
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.review_repository import ReviewRepository
from tests.fixtures.sample_review_packets import (
    SAMPLE_INCOMPLETE_REVIEW_PACKET,
    SAMPLE_SUPPORTED_FINDING_PACKET,
)


@pytest.fixture
def temp_review_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_review_repo.db"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        review_repo = ReviewRepository(db=db)
        yield review_repo, case_repo, db_path


def test_save_and_retrieve_latest_review_packet(temp_review_repo):
    review_repo, case_repo, _ = temp_review_repo

    # Persist the associated case first
    case_repo.create_case(SAMPLE_INCOMPLETE_REVIEW_PACKET.case)

    # Save packet
    saved = review_repo.save_review_packet(SAMPLE_INCOMPLETE_REVIEW_PACKET)
    assert saved.packet_id == SAMPLE_INCOMPLETE_REVIEW_PACKET.packet_id

    # Retrieve latest packet
    loaded = review_repo.get_latest_review_packet("case-fixture-001")
    assert loaded is not None
    assert loaded.packet_id == "pkt-fixture-incomplete-001"
    assert loaded.packet_version == 1
    assert loaded.review_status == "incomplete"
    assert loaded.authorization_status == "not verified"
    assert len(loaded.findings) == 1
    assert loaded.findings[0].finding_id == "find-waiting-period-hernia"
    assert loaded.findings[0].status == "unresolved"
    assert len(loaded.findings[0].evidence) == 1
    assert loaded.findings[0].evidence[0].page == 8
    assert len(loaded.missing_evidence_checklist) == 1
    assert loaded.missing_evidence_checklist[0].item_id == "chk-hernia-coverage-dates"


def test_multiple_packet_versions_and_listing(temp_review_repo):
    review_repo, case_repo, _ = temp_review_repo

    case_repo.create_case(SAMPLE_INCOMPLETE_REVIEW_PACKET.case)
    review_repo.save_review_packet(SAMPLE_INCOMPLETE_REVIEW_PACKET)

    # Create a revised packet for the same case
    revised_packet = SAMPLE_INCOMPLETE_REVIEW_PACKET.model_copy(
        update={
            "packet_id": "pkt-fixture-incomplete-002",
            "packet_version": 2,
            "review_status": "complete",
            "stopped_reason": "review_complete",
        }
    )
    review_repo.save_review_packet(revised_packet)

    # Latest should be version 2
    latest = review_repo.get_latest_review_packet("case-fixture-001")
    assert latest is not None
    assert latest.packet_id == "pkt-fixture-incomplete-002"
    assert latest.packet_version == 2
    assert latest.review_status == "complete"

    # List all packets
    packets = review_repo.list_review_packets("case-fixture-001")
    assert len(packets) == 2
    assert packets[0].packet_version == 2
    assert packets[1].packet_version == 1


def test_persistence_across_database_restart(temp_review_repo):
    review_repo, case_repo, db_path = temp_review_repo

    case_repo.create_case(SAMPLE_SUPPORTED_FINDING_PACKET.case)
    review_repo.save_review_packet(SAMPLE_SUPPORTED_FINDING_PACKET)

    # Simulate restart by creating new Database instance on same file
    new_db = Database(db_path=db_path)
    new_review_repo = ReviewRepository(db=new_db)

    loaded = new_review_repo.get_latest_review_packet(SAMPLE_SUPPORTED_FINDING_PACKET.case.case_id)
    assert loaded is not None
    assert loaded.packet_id == SAMPLE_SUPPORTED_FINDING_PACKET.packet_id
    assert loaded.review_status == "complete"
    assert len(loaded.findings) == len(SAMPLE_SUPPORTED_FINDING_PACKET.findings)
    assert loaded.findings[0].conclusion == SAMPLE_SUPPORTED_FINDING_PACKET.findings[0].conclusion


def test_update_checklist_item_status_and_preservation(temp_review_repo):
    review_repo, case_repo, _ = temp_review_repo

    case_repo.create_case(SAMPLE_INCOMPLETE_REVIEW_PACKET.case)
    review_repo.save_review_packet(SAMPLE_INCOMPLETE_REVIEW_PACKET)

    # 1. Update checklist item status to user_does_not_have
    updated = review_repo.update_checklist_item_status(
        case_id="case-fixture-001",
        item_id="chk-hernia-coverage-dates",
        status="user_does_not_have",
        resolution_note="Caregiver declared portability certificate unavailable.",
    )
    assert updated is not None
    assert updated.missing_evidence_checklist[0].status == "user_does_not_have"
    assert "Caregiver declared" in updated.missing_evidence_checklist[0].resolution_note

    # 2. Reload from database and verify persistence
    reloaded = review_repo.get_latest_review_packet("case-fixture-001")
    assert reloaded is not None
    assert reloaded.missing_evidence_checklist[0].status == "user_does_not_have"

    # 3. Save a newer packet version and verify user_does_not_have is preserved
    new_packet = SAMPLE_INCOMPLETE_REVIEW_PACKET.model_copy(
        update={
            "packet_id": "pkt-fixture-incomplete-003",
            "packet_version": 2,
            "run_id": "run-fixture-003",
        }
    )
    saved_v2 = review_repo.save_review_packet(new_packet)
    assert saved_v2.missing_evidence_checklist[0].status == "user_does_not_have"


def test_save_and_list_activity_events(temp_review_repo):
    review_repo, case_repo, _ = temp_review_repo

    event_1 = {
        "run_id": "run-m4-001",
        "step_number": 1,
        "tool_name": "search_pages",
        "tool_arguments": {"query": "waiting period"},
        "status": "completed",
        "summary": "Searching policy pages for 'waiting period'",
        "error": None,
    }
    event_2 = {
        "run_id": "run-m4-001",
        "step_number": 2,
        "tool_name": "read_page",
        "tool_arguments": {"document_id": "doc-01", "page_number": 14},
        "status": "completed",
        "summary": "Reading candidate document doc-01 page 14",
        "error": None,
    }

    review_repo.save_activity_event(event_1, case_id="case-001")
    review_repo.save_activity_event(event_2, case_id="case-001")

    events = review_repo.list_activity_events(run_id="run-m4-001")
    assert len(events) == 2
    assert events[0]["step_number"] == 1
    assert events[0]["tool_name"] == "search_pages"
    assert events[1]["step_number"] == 2
    assert events[1]["tool_name"] == "read_page"

    # Query by case_id
    case_events = review_repo.list_activity_events(case_id="case-001")
    assert len(case_events) == 2

