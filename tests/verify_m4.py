"""Automated verification script for Milestone M4-A and M4-I (Bounded Agent & User Follow-Up)."""

from datetime import date
from decimal import Decimal
import sys
import tempfile
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import WaitingPeriodReviewer
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import build_synthetic_policy_pdf
from admitsense.review.service import ReviewService
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository


def run_m4_verification():
    print("=== AdmitSense Milestone M4-A & M4-I Verification ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_m4.db"
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

        # 1. Real activity events stream & SQLite persistence
        print("\n[Check 1] Real tool activity events stream & SQLite persistence...")
        case = case_repo.create_case(
            CaseDetails(
                case_id="case-m4-v01",
                member_name="Ramesh Sharma",
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

        streamed_events = []
        packet_v1 = review_service.execute_review(
            case_id=case.case_id,
            event_callback=lambda evt: streamed_events.append(evt),
        )
        assert len(streamed_events) > 0
        assert packet_v1.tool_steps_used <= 8
        print(f"  [PASS] Captured {len(streamed_events)} tool activity events during review execution.")

        persisted_events = review_repo.list_activity_events(run_id=packet_v1.run_id)
        assert len(persisted_events) == len(streamed_events)
        print(f"  [PASS] All {len(persisted_events)} events persisted in SQLite 'tool_activity_events' table.")
        print(f"  [PASS] First event: Step {persisted_events[0]['step_number']}/8 [{persisted_events[0]['tool_name']}] '{persisted_events[0]['summary']}'")

        # 2. Honest status and partial results reporting
        print("\n[Check 2] Display run status, stop reason, and validated partial findings...")
        assert packet_v1.review_status == "incomplete"
        assert packet_v1.stopped_reason == "missing_information"
        assert len(packet_v1.findings) >= 1
        assert packet_v1.findings[0].status == "unresolved"
        assert packet_v1.authorization_status == "not verified"  # Invariant!
        print(f"  [PASS] Honest status='{packet_v1.review_status}', stop_reason='{packet_v1.stopped_reason}'")
        print(f"  [PASS] Partial finding preserved: {packet_v1.findings[0].topic} -> {packet_v1.findings[0].status}")

        # 3. User answers missing facts with provenance
        print("\n[Check 3] User answers missing facts with FactSource provenance...")
        updated_case = case.model_copy()
        updated_case.continuous_coverage_start_date = date(2024, 1, 1)
        updated_case.policy_age_months = 24
        updated_case.fact_sources["continuous_coverage_start_date"] = FactSource(source_type="user_provided")
        updated_case.fact_sources["policy_age_months"] = FactSource(source_type="user_provided")
        case_repo.update_case(updated_case)

        # Update checklist item status to provided_pending_review
        chk_id = packet_v1.missing_evidence_checklist[0].item_id
        review_repo.update_checklist_item_status(
            case_id=case.case_id,
            item_id=chk_id,
            status="provided_pending_review",
            resolution_note="User supplied continuous coverage start date.",
        )

        reloaded_case = case_repo.get_case(case.case_id)
        assert reloaded_case.continuous_coverage_start_date == date(2024, 1, 1)
        assert reloaded_case.fact_sources["continuous_coverage_start_date"].source_type == "user_provided"
        print("  [PASS] Follow-up facts saved in SQLite with user_provided provenance.")

        # 4. 'I don't have this' survives restart and keeps finding unresolved
        print("\n[Check 4] 'I don't have this' handling and persistence across restart...")
        case_2 = case_repo.create_case(
            CaseDetails(
                case_id="case-m4-v02",
                member_name="Priya Patel",
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
            case_id=case_2.case_id,
            filename="Case_2_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )
        c2_pkt1 = review_service.execute_review(case_2.case_id)
        c2_chk = c2_pkt1.missing_evidence_checklist[0]

        review_repo.update_checklist_item_status(
            case_id=case_2.case_id,
            item_id=c2_chk.item_id,
            status="user_does_not_have",
            resolution_note="Caregiver declared portability certificate unavailable.",
        )

        # Simulate restart
        db_restart = Database(db_path=db_path)
        restart_review_repo = ReviewRepository(db=db_restart)
        reloaded_pkt = restart_review_repo.get_latest_review_packet(case_2.case_id)
        assert reloaded_pkt is not None
        assert reloaded_pkt.missing_evidence_checklist[0].status == "user_does_not_have"
        print("  [PASS] 'user_does_not_have' survived simulated application restart.")

        # 5. Resumed review creates an explicit new run retaining earlier history
        print("\n[Check 5] Resumed review creates an explicit new run and retains historical records...")
        c1_pkt2 = review_service.execute_review(case.case_id)
        assert c1_pkt2.packet_version == 2
        assert c1_pkt2.run_id != packet_v1.run_id
        assert c1_pkt2.review_status == "complete"
        assert c1_pkt2.findings[0].status == "supported"
        print(f"  [PASS] Resumed review created version {c1_pkt2.packet_version} with new Run ID: {c1_pkt2.run_id}")

        history = review_repo.list_review_packets(case.case_id)
        assert len(history) == 2
        assert history[0].packet_version == 2
        assert history[1].packet_version == 1
        print(f"  [PASS] Earlier run retained in SQLite history (total {len(history)} runs for case).")

        # 6. Tool budget enforcement (<= 8 calls)
        print("\n[Check 6] Tool budget capping and honest tool_limit_reached reporting...")
        capped_pkt = review_service.execute_review(case_2.case_id, tool_budget=2)
        assert capped_pkt.tool_steps_used <= 2
        assert capped_pkt.stopped_reason == "tool_limit_reached"
        assert capped_pkt.review_status == "incomplete"
        print(f"  [PASS] Budget capped at {capped_pkt.tool_steps_used} calls with stopped_reason='{capped_pkt.stopped_reason}'")

        # 7. Honest error reporting without masking failure as success
        print("\n[Check 7] Honest error reporting on runner failure...")
        class FailingRunner:
            def run_review(self, *args, **kwargs):
                raise RuntimeError("Simulated insurer policy lookup timeout")

        failing_service = ReviewService(
            case_repo=case_repo,
            review_repo=review_repo,
            retrieval=retrieval,
            runner=FailingRunner(),
        )
        err_pkt = failing_service.execute_review(case.case_id)
        assert err_pkt.review_status == "incomplete"
        assert err_pkt.stopped_reason == "processing_error"
        assert "Simulated insurer policy lookup timeout" in (err_pkt.stop_details or "")
        print(f"  [PASS] Error handled honestly: status='{err_pkt.review_status}', reason='{err_pkt.stopped_reason}'")

    print("\n=== ALL MILESTONE M4 ACCEPTANCE CHECKS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    run_m4_verification()
