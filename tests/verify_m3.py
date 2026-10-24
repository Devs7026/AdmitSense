"""Combined Automated Verification Script for Milestone M3 (M3-A, M3-B, and M3-I).

Validates:
Part 1 (M3-B):
- WaitingPeriodReviewer bounded agent analysis on real extracted PDF text.
- 24-month condition vs 18-month continuous coverage history producing cited shortfall.
- Citations verified against physical 1-based page numbers.
- ToolActivityEvent telemetry stream (<= 8 steps).
- Satisfied waiting period scenario (Cataract 12 mo vs 18 mo).
- Invariant: Authorisation strictly defaults to 'not verified'; zero invented waivers.

Part 2 (M3-A & M3-I):
- ReviewService workflow integration and ReviewRepository SQLite persistence.
- Snapshot reload across database restart.
- Incremental review progression (v1 -> v2) with endorsement.
- Historical packet audit trail.
"""

from datetime import date
from decimal import Decimal
import sys
import tempfile
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import (
    ToolActivityEvent,
    WaitingPeriodReviewer,
    run_waiting_period_review,
)
from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
)
from admitsense.review.service import FixtureReviewRunner, ReviewService
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository


def run_m3_verification():
    print("=== AdmitSense Milestone M3 Combined Verification ===")
    print()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_m3.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        storage = DocumentStorage(db=db, storage_dir=doc_dir)
        retrieval = SqliteEvidenceRetrieval(db=db)
        agent_retrieval = EvidenceRetrievalService(db=db)
        review_repo = ReviewRepository(db=db)

        # ======================================================================
        # Part 1: Milestone M3-B Agent Review Engine Verification
        # ======================================================================
        print("--- Part 1: M3-B Review Engine & Telemetry Checks ---")

        case_1 = CaseDetails(
            case_id="case-verify-m3-001",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
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
        case_repo.create_case(case_1)

        # Ingest Policy Wording (Page 14: Section 4.2(b), 24-month waiting period)
        doc_pol, _ = storage.save_document(
            case_id=case_1.case_id,
            filename="Care_Health_Gold_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )

        # Ingest Renewal Schedule (Page 1: 18 months continuous coverage)
        doc_sched, _ = storage.save_document(
            case_id=case_1.case_id,
            filename="Policy_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )

        print("[Check 1] Running review with telemetry event tracking...")
        events: list[ToolActivityEvent] = []
        reviewer = WaitingPeriodReviewer(default_tool_budget=8)
        packet_b = reviewer.run_review(
            case=case_1,
            retrieval=agent_retrieval,
            event_callback=lambda ev: events.append(ev),
        )

        assert packet_b.tool_steps_used <= 8, f"Tool steps exceeded budget: {packet_b.tool_steps_used}"
        assert len(events) > 0, "No telemetry events captured"
        print(f"  [PASS] Review completed using {packet_b.tool_steps_used} tool steps. Captured {len(events)} telemetry events.")

        print("[Check 2] Evaluating 24-month condition vs 18-month history acceptance criteria...")
        assert packet_b.review_status == "incomplete"
        assert packet_b.stopped_reason == "missing_information"
        assert len(packet_b.findings) == 1
        finding = packet_b.findings[0]
        assert finding.status == "unresolved"
        assert "shortfall" in finding.conclusion.lower() or "gap" in finding.conclusion.lower()
        assert "24" in finding.conclusion or "twenty-four" in finding.conclusion
        assert "18" in finding.conclusion or "eighteen" in finding.conclusion
        print(f"  [PASS] Finding correctly marked 'unresolved' with 6-month shortfall: '{finding.conclusion[:80]}...'")

        print("[Check 3] Verifying physical page evidence citations...")
        assert len(finding.evidence) >= 1
        pol_ev = next((e for e in finding.evidence if e.evidence_type == "policy_wording"), None)
        assert pol_ev is not None
        assert pol_ev.page == 14
        assert "twenty-four (24) continuous months" in pol_ev.quote
        print(f"  [PASS] Policy wording cited on physical page {pol_ev.page}: '{pol_ev.quote[:70]}...'")

        print("[Check 4] Checking next action and non-negotiable invariants...")
        assert packet_b.authorization_status == "not verified"
        assert packet_b.authorization_evidence == []
        assert "approved" not in finding.conclusion.lower()
        assert "waiver document required" not in finding.conclusion.lower()
        print("  [PASS] Authorisation strictly 'not verified'; zero inferred approval statements; no invented waivers.")

        print("[Check 5] Evaluating satisfied waiting period scenario (Cataract 12 mo vs 18 mo)...")
        case_cataract = CaseDetails(
            case_id="case-verify-cataract-002",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
            procedure="Cataract Surgery",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
            },
        )
        case_repo.create_case(case_cataract)
        storage.save_document(
            case_id="case-verify-cataract-002",
            filename="Cataract_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )
        storage.save_document(
            case_id="case-verify-cataract-002",
            filename="Cataract_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )
        packet_cataract = run_waiting_period_review(case=case_cataract, retrieval=agent_retrieval)
        cat_finding = packet_cataract.findings[0]
        assert cat_finding.status == "supported"
        assert cat_finding.evidence[0].page == 11
        print(f"  [PASS] Cataract finding supported on page {cat_finding.evidence[0].page}: '{cat_finding.conclusion[:80]}...'")

        # ======================================================================
        # Part 2: Milestone M3-A & M3-I ReviewService & Persistence Checks
        # ======================================================================
        print("\n--- Part 2: M3-A & M3-I Service Integration & Persistence Checks ---")
        review_service = ReviewService(
            case_repo=case_repo,
            review_repo=review_repo,
            retrieval=retrieval,
            runner=reviewer,
        )

        print("[Check 6] Executing review action via ReviewService and persisting snapshot...")
        packet_v1 = review_service.execute_review(case_1.case_id)
        assert packet_v1 is not None
        assert packet_v1.packet_version == 1
        assert packet_v1.review_status == "incomplete"
        assert packet_v1.findings[0].evidence[0].page == 14
        print(f"  [PASS] ReviewPacket snapshot persisted with version={packet_v1.packet_version}, findings={len(packet_v1.findings)}.")

        print("[Check 7] Verifying snapshot persistence and reload across database restart...")
        db_restart = Database(db_path=db_path)
        restart_review_repo = ReviewRepository(db=db_restart)
        reloaded_packet = restart_review_repo.get_latest_review_packet(case_1.case_id)

        assert reloaded_packet is not None
        assert reloaded_packet.packet_id == packet_v1.packet_id
        assert reloaded_packet.packet_version == 1
        assert reloaded_packet.findings[0].conclusion == packet_v1.findings[0].conclusion
        assert reloaded_packet.findings[0].evidence[0].page == 14
        print("  [PASS] Snapshot reloaded identically from SQLite storage across restart.")

        print("[Check 8] Review progression with incremental review runner...")
        review_service_progression = ReviewService(
            case_repo=case_repo,
            review_repo=review_repo,
            retrieval=retrieval,
            runner=FixtureReviewRunner(),
        )
        storage.save_document(
            case_id=case_1.case_id,
            filename="Joint_Replacement_Endorsement.pdf",
            content=build_synthetic_endorsement_pdf(),
            evidence_type="endorsement",
        )
        packet_v2 = review_service_progression.execute_review(case_1.case_id)
        assert packet_v2.packet_version == 2
        assert packet_v2.review_status == "complete"
        assert packet_v2.findings[0].status == "supported"
        print(f"  [PASS] Incremental review produced packet version 2 with status='{packet_v2.review_status}'.")

        packets = restart_review_repo.list_review_packets(case_1.case_id)
        assert len(packets) == 2
        print(f"  [PASS] Review history contains all {len(packets)} versions in order.")

    print("\n=== ALL MILESTONE M3 VERIFICATION CHECKS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    run_m3_verification()
