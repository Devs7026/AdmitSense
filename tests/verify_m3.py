"""Automated verification script for Owner A Milestone M3-A (Review Workspace & Persistence)."""

from datetime import date
from decimal import Decimal
import sys
import tempfile
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
)
from admitsense.review.service import ReviewService, FixtureReviewRunner
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository


def run_m3_verification():
    print("=== AdmitSense Milestone M3-A Verification ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_m3.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        retrieval = SqliteEvidenceRetrieval(db=db)
        review_repo = ReviewRepository(db=db)
        review_service = ReviewService(
            case_repo=case_repo,
            review_repo=review_repo,
            retrieval=retrieval,
            runner=FixtureReviewRunner(),
        )

        # 1. Setup case with 18-month history (knee replacement waiting period requires 24 months)
        print("\n[Check 1] Case setup with partial facts...")
        case = case_repo.create_case(
            CaseDetails(
                case_id="case-m3-verify-01",
                member_name="Ramesh Sharma",
                policy_id="POL-7026-MED",
                procedure="Total Knee Replacement",
                planned_admission_date=date(2026, 11, 20),
                hospital_name="Apex Super Specialty Hospital",
                policy_age_months=18,
                estimated_cost=Decimal("250000.00"),
                fact_sources={
                    "member_name": FactSource(source_type="user_provided"),
                    "policy_id": FactSource(source_type="user_provided"),
                    "procedure": FactSource(source_type="user_provided"),
                    "planned_admission_date": FactSource(source_type="user_provided"),
                    "hospital_name": FactSource(source_type="user_provided"),
                    "policy_age_months": FactSource(source_type="user_provided"),
                    "estimated_cost": FactSource(source_type="user_provided"),
                },
            )
        )
        assert case.case_id == "case-m3-verify-01"
        print("  [PASS] Case created with 18-month policy age and unknown continuous coverage.")

        # 2. Ingest base policy PDF
        print("\n[Check 2] Ingesting base policy document...")
        policy_pdf = build_synthetic_policy_pdf()
        meta_policy, is_duplicate = doc_storage.save_document(
            case_id=case.case_id,
            filename="Care_Health_Gold_Policy_Wording.pdf",
            content=policy_pdf,
            evidence_type="policy_wording",
        )
        assert meta_policy.extraction_status in ("extracted", "partial")
        print(f"  [PASS] Base policy ingested (Doc ID: {meta_policy.document_id}, Pages: {meta_policy.total_pages})")

        # 3. Trigger Review Action (Simulating Workspace "Review Available Documents")
        print("\n[Check 3] Executing 'Review Available Documents' action via ReviewService...")
        packet_v1 = review_service.execute_review(case.case_id)
        assert packet_v1 is not None
        assert packet_v1.packet_version == 1
        assert packet_v1.review_status == "incomplete"
        assert packet_v1.stopped_reason == "missing_information"
        assert packet_v1.authorization_status == "not verified"
        assert packet_v1.tool_steps_used <= 8
        print(f"  [PASS] Review completed with status='{packet_v1.review_status}', stop_reason='{packet_v1.stopped_reason}'")
        print(f"  [PASS] Tool budget respected: {packet_v1.tool_steps_used} <= 8 steps.")
        print(f"  [PASS] Insurer authorization status correctly defaults to: '{packet_v1.authorization_status}'")

        # 4. Verify Findings, Citations & Missing Evidence Checklist
        print("\n[Check 4] Validating Findings, physical page citations, and checklist items...")
        assert len(packet_v1.findings) >= 1
        f1 = packet_v1.findings[0]
        assert f1.status == "unresolved"
        assert len(f1.evidence) >= 1
        citation = f1.evidence[0]
        assert citation.page == 14
        assert "24" in citation.quote and "knee replacement" in citation.quote.lower()
        print(f"  [PASS] Finding status='{f1.status}', conclusion='{f1.conclusion[:60]}...'")
        print(f"  [PASS] Citation points to physical page {citation.page} with excerpt: '{citation.quote[:50]}...'")

        assert len(packet_v1.missing_evidence_checklist) >= 1
        chk = packet_v1.missing_evidence_checklist[0]
        assert "continuity" in chk.requested_information.lower() or "certificate" in chk.requested_information.lower()
        print(f"  [PASS] Checklist requested: '{chk.requested_information}'")

        # 5. Verify Persistence & Reload across application restart
        print("\n[Check 5] Verifying persistence and snapshot reload across database restart...")
        db_restart = Database(db_path=db_path)
        restart_review_repo = ReviewRepository(db=db_restart)
        reloaded_packet = restart_review_repo.get_latest_review_packet(case.case_id)

        assert reloaded_packet is not None
        assert reloaded_packet.packet_id == packet_v1.packet_id
        assert reloaded_packet.packet_version == 1
        assert reloaded_packet.review_status == "incomplete"
        assert len(reloaded_packet.findings) == len(packet_v1.findings)
        assert reloaded_packet.findings[0].conclusion == f1.conclusion
        assert reloaded_packet.findings[0].evidence[0].page == 14
        print("  [PASS] ReviewPacket reloaded identically from SQLite storage.")

        # 6. Re-review progression: Ingest Endorsement PDF waiving waiting period
        print("\n[Check 6] Uploading waiver endorsement and triggering incremental review...")
        endorsement_pdf = build_synthetic_endorsement_pdf()
        meta_endorsement, is_dup = doc_storage.save_document(
            case_id=case.case_id,
            filename="Joint_Replacement_Endorsement.pdf",
            content=endorsement_pdf,
            evidence_type="endorsement",
        )
        assert meta_endorsement.extraction_status in ("extracted", "partial")

        packet_v2 = review_service.execute_review(case.case_id)
        assert packet_v2.packet_version == 2
        assert packet_v2.review_status == "complete"
        assert packet_v2.stopped_reason == "review_complete"
        assert packet_v2.authorization_status == "not verified"  # Invariant: never inferred!
        f2 = packet_v2.findings[0]
        assert f2.status == "supported"
        assert any(e.document_id == meta_endorsement.document_id for e in f2.evidence)
        print(f"  [PASS] Packet updated to version 2 with status='{packet_v2.review_status}'")
        print(f"  [PASS] Finding updated to status='{f2.status}' supported by endorsement citation on page {f2.evidence[0].page}")
        assert len(packet_v2.revisions) >= 1
        print(f"  [PASS] Audit trail preserved revision history ({len(packet_v2.revisions)} revision(s)).")

        # 7. Check historical listing
        packets = restart_review_repo.list_review_packets(case.case_id)
        assert len(packets) == 2
        assert packets[0].packet_version == 2
        assert packets[1].packet_version == 1
        print("  [PASS] Historical packet list contains all versions in descending order.")

    print("\n[ALL M3-A ACCEPTANCE CHECKS PASSED SUCCESSFULLY]")


if __name__ == "__main__":
    run_m3_verification()
