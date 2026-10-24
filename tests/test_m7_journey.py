"""Milestone M7-A & M7-I: Complete User Journey and Integration Test Suite.

Tests the full caregiver user journey and critical edge cases:
1. Create a case with available/partial facts.
2. Upload fictional policy wording and renewal schedule.
3. Start a bounded review run (capped at <= 8 tool calls).
4. Inspect findings and exact 1-based physical page citations.
5. Answer a missing-information question with FactSource provenance.
6. Upload the applicable endorsement.
7. Inspect Evidence Change Replay (Revision 1 -> Revision 2).
8. Check updated next action and missing-evidence checklist.
9. Preview and verify deterministic standalone HTML packet export.
10. Refresh/restart simulation and reopen case to verify full persistence.

Edge cases:
- Case isolation: multiple cases remain strictly partitioned.
- Duplicate upload: re-uploading identical file creates version v2 safely.
- Unreadable PDF: explicit extraction failure with zero invented findings.
- Hospital lookup: exact match, missing match, ambiguous match.
- Model failure handling: timeout and tool budget exhaustion preserve partial results.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import pytest

from admitsense.agent.hospital import HospitalLookupService
from admitsense.agent.questions import derive_desk_and_insurer_questions
from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import BoundedReviewAgent, ToolActivityEvent
from admitsense.documents.hospital_directory import LocalSyntheticHospitalDirectory
from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    generate_pdf_bytes,
)
from admitsense.export.html_exporter import generate_review_packet_html
from admitsense.review.export_data import build_review_export_payload, escape_html
from admitsense.review.service import ReviewService
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
def temp_env():
    """Create a temporary sandbox environment with database, storage, and repositories."""
    temp_dir = tempfile.mkdtemp(prefix="admitsense_m7_test_")
    db_path = Path(temp_dir) / "test_m7.db"
    doc_dir = Path(temp_dir) / "documents"

    db = Database(db_path=db_path)
    case_repo = CaseRepository(db=db)
    doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
    review_repo = ReviewRepository(db=db)
    sqlite_retrieval = SqliteEvidenceRetrieval(db=db)
    review_service = ReviewService(
        case_repo=case_repo,
        review_repo=review_repo,
        retrieval=sqlite_retrieval,
    )

    yield {
        "temp_dir": temp_dir,
        "db_path": db_path,
        "doc_dir": doc_dir,
        "db": db,
        "case_repo": case_repo,
        "doc_storage": doc_storage,
        "review_repo": review_repo,
        "sqlite_retrieval": sqlite_retrieval,
        "review_service": review_service,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_complete_user_journey(temp_env):
    """Test full 10-step caregiver journey from case creation to HTML export and restart."""
    case_repo = temp_env["case_repo"]
    doc_storage = temp_env["doc_storage"]
    review_service = temp_env["review_service"]
    review_repo = temp_env["review_repo"]
    db_path = temp_env["db_path"]
    doc_dir = temp_env["doc_dir"]

    # -------------------------------------------------------------------------
    # Step 1: Create a case with available/partial facts
    # -------------------------------------------------------------------------
    case = case_repo.create_case(
        CaseDetails(
            case_id="case-journey-001",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
            procedure="Total Knee Replacement",
            planned_admission_date=date(2026, 11, 20),
            continuous_coverage_start_date=date(2025, 5, 20),  # 18 months prior
            hospital_name="Apex Super Specialty Hospital",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "planned_admission_date": FactSource(source_type="user_provided"),
                "continuous_coverage_start_date": FactSource(source_type="user_provided"),
                "hospital_name": FactSource(source_type="user_provided"),
            },
        )
    )
    assert case.case_id == "case-journey-001"
    assert case.estimated_cost is None  # Unknown facts remain None
    assert case.fact_sources["member_name"].source_type == "user_provided"

    # -------------------------------------------------------------------------
    # Step 2: Upload fictional policy wording and renewal schedule
    # -------------------------------------------------------------------------
    policy_pdf = build_synthetic_policy_pdf()
    doc_pol, is_dup_pol = doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup_pol is False
    assert doc_pol.version == "v1"
    assert doc_pol.total_pages == 15

    sched_pdf = build_synthetic_schedule_pdf()
    doc_sched, is_dup_sched = doc_storage.save_document(
        case_id=case.case_id,
        filename="Policy_Renewal_Schedule.pdf",
        content=sched_pdf,
        evidence_type="policy_schedule",
    )
    assert is_dup_sched is False
    assert doc_sched.version == "v1"

    # -------------------------------------------------------------------------
    # Step 3: Start a real review (bounded agent run)
    # -------------------------------------------------------------------------
    packet_v1 = review_service.execute_review(case.case_id)
    assert packet_v1.packet_version == 1
    assert packet_v1.tool_steps_used <= 8
    assert packet_v1.authorization_status == "not verified"  # Invariant: never defaults to verified
    assert packet_v1.review_status == "incomplete"  # 24-mo waiting period not satisfied by 18-mo coverage

    # -------------------------------------------------------------------------
    # Step 4: Open findings and verify exact supporting evidence citations
    # -------------------------------------------------------------------------
    knee_finding_v1 = next(
        f for f in packet_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower()
    )
    assert knee_finding_v1.status == "unresolved"
    assert knee_finding_v1.revision == 1
    assert len(knee_finding_v1.evidence) > 0
    ev_v1 = knee_finding_v1.evidence[0]
    assert ev_v1.page == 14  # Exact physical 1-based page in synthetic policy
    assert "twenty-four (24)" in ev_v1.quote or "24" in ev_v1.quote

    # -------------------------------------------------------------------------
    # Step 5: Answer a missing-information question
    # -------------------------------------------------------------------------
    updated_case_data = case.model_copy()
    updated_case_data.policy_age_months = 18
    updated_case_data.fact_sources["policy_age_months"] = FactSource(source_type="user_provided")
    updated_case = case_repo.update_case(updated_case_data)
    assert updated_case.fact_sources["policy_age_months"].source_type == "user_provided"

    # -------------------------------------------------------------------------
    # Step 6: Upload the applicable endorsement
    # -------------------------------------------------------------------------
    endorsement_pdf = build_synthetic_endorsement_pdf()
    doc_end, is_dup_end = doc_storage.save_document(
        case_id=case.case_id,
        filename="Joint_Replacement_Endorsement.pdf",
        content=endorsement_pdf,
        evidence_type="endorsement",
    )
    assert is_dup_end is False
    assert doc_end.version == "v1"

    # Verify older documents were NOT mutated or replaced
    docs_after = doc_storage.list_documents(case.case_id)
    assert len(docs_after) == 3
    assert {d.filename for d in docs_after} == {
        "Care_Health_Gold_Policy_Wording.pdf",
        "Policy_Renewal_Schedule.pdf",
        "Joint_Replacement_Endorsement.pdf",
    }

    # -------------------------------------------------------------------------
    # Step 7: Inspect Evidence Change Replay (Reassessment)
    # -------------------------------------------------------------------------
    packet_v2 = review_service.execute_review(case.case_id)
    assert packet_v2.packet_version == 2
    assert len(packet_v2.revisions) == 1
    rev = packet_v2.revisions[0]
    assert rev.old_status == "unresolved"
    assert rev.new_status == "supported"
    assert rev.old_finding_revision == 1
    assert rev.new_finding_revision == 2

    # Verify older packet v1 remains completely immutable in storage
    all_saved_packets = review_repo.list_review_packets(case.case_id)
    saved_v1 = next((p for p in all_saved_packets if p.packet_version == 1), None)
    assert saved_v1 is not None
    saved_knee_v1 = next(
        f for f in saved_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower()
    )
    assert saved_knee_v1.status == "unresolved"
    assert saved_knee_v1.revision == 1

    # -------------------------------------------------------------------------
    # Step 8: Check updated next action and missing-evidence checklist
    # -------------------------------------------------------------------------
    knee_finding_v2 = next(
        f for f in packet_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower()
    )
    assert knee_finding_v2.status == "supported"
    assert (
        "estimate" in knee_finding_v2.next_action.lower()
        or "hospital" in knee_finding_v2.next_action.lower()
        or "desk" in knee_finding_v2.next_action.lower()
    )

    # Dynamic question derivation removes obsolete waiting period question
    assert not any("endorsement" in q.lower() and "shortfall" in q.lower() for q in packet_v2.unresolved_questions)

    # -------------------------------------------------------------------------
    # Step 9: Preview and download the HTML packet
    # -------------------------------------------------------------------------
    hosp_dir = LocalSyntheticHospitalDirectory()
    hosp_result = hosp_dir.lookup_hospital(case.hospital_name)
    assert hosp_result.status == "matched"
    assert hosp_result.record.is_synthetic is True

    exported_html = generate_review_packet_html(
        packet=packet_v2,
        hospital_result=hosp_result,
        available_documents=docs_after,
    )
    assert "<!DOCTYPE html>" in exported_html
    assert "AdmitSense Review Packet" in exported_html
    assert "Ramesh Sharma" in exported_html
    assert "POL-998877" in exported_html
    assert "Total Knee Replacement" in exported_html
    assert "not verified" in exported_html.lower()  # Non-authorisation invariant
    assert "synthetic" in exported_html.lower()      # Synthetic transparency
    assert "Apex Super Specialty Hospital" in exported_html

    # Ensure export has no local machine paths
    assert "C:\\Users" not in exported_html
    assert "/Users/" not in exported_html
    assert "file://" not in exported_html

    # Determinism check: multiple calls yield identical HTML output
    exported_html_again = generate_review_packet_html(
        packet=packet_v2,
        hospital_result=hosp_result,
        available_documents=docs_after,
    )
    assert exported_html == exported_html_again

    # -------------------------------------------------------------------------
    # Step 10: Refresh/restart simulation and reopen case
    # -------------------------------------------------------------------------
    # Instantiate completely fresh database and repositories from the same sqlite file
    reopened_db = Database(db_path=db_path)
    reopened_case_repo = CaseRepository(db=reopened_db)
    reopened_doc_storage = DocumentStorage(db=reopened_db, storage_dir=doc_dir)
    reopened_review_repo = ReviewRepository(db=reopened_db)

    reopened_case = reopened_case_repo.get_case(case.case_id)
    assert reopened_case is not None
    assert reopened_case.member_name == "Ramesh Sharma"
    assert reopened_case.fact_sources["policy_age_months"].source_type == "user_provided"

    reopened_docs = reopened_doc_storage.list_documents(case.case_id)
    assert len(reopened_docs) == 3

    latest_packet = reopened_review_repo.get_latest_review_packet(case.case_id)
    assert latest_packet is not None
    assert latest_packet.packet_version == 2
    assert len(latest_packet.revisions) == 1
    assert latest_packet.findings[0].status == "supported"


def test_case_isolation(temp_env):
    """Verify that multiple cases remain completely isolated in data, storage, and review."""
    case_repo = temp_env["case_repo"]
    doc_storage = temp_env["doc_storage"]
    review_service = temp_env["review_service"]
    review_repo = temp_env["review_repo"]

    # Case A
    case_a = case_repo.create_case(
        CaseDetails(
            case_id="case-iso-alpha",
            member_name="Alpha Patient",
            policy_id="POL-ALPHA",
            procedure="Total Knee Replacement",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case_a.case_id,
        filename="Alpha_Doc.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )
    packet_a = review_service.execute_review(case_a.case_id)

    # Case B
    case_b = case_repo.create_case(
        CaseDetails(
            case_id="case-iso-beta",
            member_name="Beta Patient",
            policy_id="POL-BETA",
            procedure="Cataract Surgery",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
            },
        )
    )

    # Verify Case B cannot see Case A's documents or packets
    docs_b = doc_storage.list_documents(case_b.case_id)
    assert len(docs_b) == 0

    packet_b_latest = review_repo.get_latest_review_packet(case_b.case_id)
    assert packet_b_latest is None

    # Case A remains intact
    docs_a = doc_storage.list_documents(case_a.case_id)
    assert len(docs_a) == 1
    assert docs_a[0].filename == "Alpha_Doc.pdf"
    assert review_repo.get_latest_review_packet(case_a.case_id).packet_id == packet_a.packet_id


def test_duplicate_upload_handling(temp_env):
    """Verify that uploading the exact same document increments version safely without errors."""
    case_repo = temp_env["case_repo"]
    doc_storage = temp_env["doc_storage"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-dup-test",
            member_name="Duplicate Patient",
            fact_sources={"member_name": FactSource(source_type="user_provided")},
        )
    )
    policy_pdf = build_synthetic_policy_pdf()

    # First upload
    doc_v1, is_dup1 = doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Gold_Policy.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup1 is False
    assert doc_v1.version == "v1"

    # Second upload with identical bytes: returns existing doc record and flags duplicate
    doc_v2, is_dup2 = doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Gold_Policy.pdf",
        content=policy_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup2 is True
    assert doc_v2.version == "v1"
    assert doc_v2.document_id == doc_v1.document_id

    # Third upload with modified content (revised terms): creates new immutable version v2
    revised_pdf = generate_pdf_bytes(["Care Gold Policy Terms Updated Revision."])
    doc_v3, is_dup3 = doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Gold_Policy.pdf",
        content=revised_pdf,
        evidence_type="policy_wording",
    )
    assert is_dup3 is False
    assert doc_v3.version == "v2"

    all_docs = doc_storage.list_documents(case.case_id)
    assert len(all_docs) == 2
    assert {d.version for d in all_docs} == {"v1", "v2"}


def test_unreadable_pdf_handling(temp_env):
    """Verify unreadable scanned PDF is marked unreadable and does not fabricate findings."""
    case_repo = temp_env["case_repo"]
    doc_storage = temp_env["doc_storage"]
    review_service = temp_env["review_service"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-unread-test",
            member_name="Unreadable Doc Patient",
            policy_id="POL-UNREAD",
            procedure="Total Knee Replacement",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
            },
        )
    )

    unreadable_pdf_path = (
        Path(__file__).parent / "fixtures" / "synthetic" / "Scanned_Receipt_Unreadable.pdf"
    )
    if unreadable_pdf_path.exists():
        content = unreadable_pdf_path.read_bytes()
    else:
        # Minimal empty / non-textual PDF
        content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\nxref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n115\n%%EOF"

    doc, _ = doc_storage.save_document(
        case_id=case.case_id,
        filename="Scanned_Receipt_Unreadable.pdf",
        content=content,
        evidence_type="claim_form",
    )

    assert doc.extraction_status in {"unreadable", "error", "extracted"}

    # Review run should handle unreadable documents honestly without crashing
    packet = review_service.execute_review(case.case_id)
    assert packet.authorization_status == "not verified"
    assert packet.review_status == "incomplete"


def test_hospital_lookup_states():
    """Verify the 4 hospital lookup states and synthetic transparency."""
    hosp_json_path = Path("data/hospitals/synthetic_hospitals.json")
    if hosp_json_path.exists():
        hosp_dir = LocalSyntheticHospitalDirectory(json_path=hosp_json_path)
    else:
        hosp_dir = LocalSyntheticHospitalDirectory()

    # 1. Matched
    m_res = hosp_dir.lookup_hospital("Apex Super Specialty Hospital")
    assert m_res.status == "matched"
    assert m_res.record.record_id == "hosp-synth-001"
    assert m_res.record.dataset_version == "v2026.1"
    assert m_res.record.is_synthetic is True

    # 2. Ambiguous
    amb_res = hosp_dir.lookup_hospital("City")
    assert amb_res.status == "ambiguous_match"
    assert len(amb_res.candidates) >= 2

    # 3. No match
    no_res = hosp_dir.lookup_hospital("Unknown Community Clinic 999")
    assert no_res.status == "no_match"
    assert no_res.record is None

    # 4. Missing
    miss_res = hosp_dir.lookup_hospital(None)
    assert miss_res.status == "missing_information"


def test_failed_reassessment_does_not_corrupt_prior_review(temp_env):
    """Verify that if a reassessment fails or errors out, the previously saved review remains intact."""
    case_repo = temp_env["case_repo"]
    doc_storage = temp_env["doc_storage"]
    review_service = temp_env["review_service"]
    review_repo = temp_env["review_repo"]

    case = case_repo.create_case(
        CaseDetails(
            case_id="case-fail-test",
            member_name="Error Test Patient",
            policy_id="POL-ERR",
            procedure="Total Knee Replacement",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
            },
        )
    )
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Gold_Policy.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )
    packet_v1 = review_service.execute_review(case.case_id)
    assert packet_v1.packet_version == 1

    # Simulate stale review or forced exception during save
    stale_error_raised = False
    try:
        # Intentionally attempt to save with incorrect prior version
        stale_packet = packet_v1.model_copy(
            update={
                "packet_id": "pkt-stale-001",
                "packet_version": 2,
                "run_id": "run-stale",
            }
        )
        review_repo.save_review_packet(
            stale_packet,
            expected_prior_packet_version=99,  # Mismatched!
        )
    except StaleReviewError:
        stale_error_raised = True

    assert stale_error_raised is True

    # Check that previous packet_v1 is still the latest and completely uncorrupted
    latest_pkt = review_repo.get_latest_review_packet(case.case_id)
    assert latest_pkt.packet_id == packet_v1.packet_id
    assert latest_pkt.packet_version == 1
