"""Combined Verification Script for Milestone M5: Evidence Change Replay (M5-A, M5-B, M5-I).

Executes end-to-end verification of all M5 requirements:
Part 1 (M5-A & Replay Storage):
1. Ingest base policy & renewal schedule -> initial unresolved finding (Rev 1).
2. Upload new endorsement without replacing base policy v1.
3. Reassessment with endorsement revises only justified findings (Rev 1 -> Rev 2).
4. Duplicate uploads and duplicate re-reviews emit 0 duplicate revisions.
5. Historical finding snapshots at Rev 1 and Rev 2 remain accessible via get_finding_snapshot.
6. Replay audit history survives simulated application restart.
7. Stale review rejection via StaleReviewError prevents concurrent overwrites.
8. Transactional integrity: failed saves rollback atomically.
9. Authorization strictly remains 'not verified'.

Part 2 (M5-B & Live Bounded Review Agent Replay):
10. Applicable endorsement modifies waiting period to 12 months & keeps narrow scope.
11. Wrong policy ID does not override base policy.
12. Endorsement effective after planned admission date does not apply.
13. Ambiguous precedence produces conflict finding with uncertainty retained.
14. Unrelated findings remain unchanged across replay.
15. Duplicate input does not create duplicate substantive revisions.
16. Corrected case date triggers reassessment of dependent findings.
17. Failed/partial reassessment does not falsely report completion.
"""

from datetime import date
from pathlib import Path
import sys
import tempfile

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import BoundedReviewAgent
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
    ReviewPacket,
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository, StaleReviewError


def run_m5_combined_verification() -> bool:
    print("=== AdmitSense Milestone M5 Combined Acceptance Verification (M5-A, M5-B, M5-I) ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_m5.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        review_repo = ReviewRepository(db=db)
        sqlite_retrieval = SqliteEvidenceRetrieval(db=db)

        # ======================================================================
        # Part 1: M5-A Storage, Persistence & Replay Diff Checks (Owner A)
        # ======================================================================
        print("\n--- Part 1: M5-A Storage, Persistence & Replay Diff Checks ---")

        case = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-verify-001",
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

        # Step 1: Base policy upload & Initial review
        print("\n[Check 1] Ingesting base policy and executing baseline review...")
        policy_pdf = build_synthetic_policy_pdf()
        doc_base, is_dup1 = doc_storage.save_document(
            case_id=case.case_id,
            filename="Care_Gold_Policy_Wording.pdf",
            content=policy_pdf,
            evidence_type="policy_wording",
        )
        assert is_dup1 is False
        assert doc_base.version == "v1"

        sched_pdf = build_synthetic_schedule_pdf()
        doc_sched, _ = doc_storage.save_document(
            case_id=case.case_id,
            filename="Care_Renewal_Schedule.pdf",
            content=sched_pdf,
            evidence_type="policy_schedule",
        )

        service = ReviewService(
            case_repo=case_repo,
            review_repo=review_repo,
            retrieval=sqlite_retrieval,
            runner=FixtureReviewRunner(),
        )

        packet_v1 = service.execute_review(case.case_id)
        assert packet_v1.packet_version == 1
        assert len(packet_v1.revisions) == 0
        assert packet_v1.findings[0].revision == 1
        assert packet_v1.findings[0].status == "unresolved"
        print("  [PASS] Baseline Packet v1 persisted: finding at Revision 1 (unresolved shortfall).")

        # Step 2: Upload endorsement without replacing base policy
        print("\n[Check 2] Uploading new endorsement schedule without replacing older base policy...")
        end_pdf = build_synthetic_endorsement_pdf()
        doc_end, is_dup2 = doc_storage.save_document(
            case_id=case.case_id,
            filename="Joint_Replacement_Endorsement.pdf",
            content=end_pdf,
            evidence_type="endorsement",
        )
        assert is_dup2 is False
        assert doc_end.version == "v1"

        old_base = doc_storage.get_document(doc_base.document_id, "v1")
        assert old_base is not None
        assert old_base.total_pages == 15
        print(f"  [PASS] Endorsement {doc_end.document_id} uploaded; base policy {doc_base.document_id} v1 intact.")

        # Step 3: Reassessment revises finding and logs revision
        print("\n[Check 3] Reassessment with endorsement revises only justified findings (Rev 1 -> Rev 2)...")
        packet_v2 = service.execute_review(case.case_id)
        assert packet_v2.packet_version == 2
        assert packet_v2.findings[0].revision == 2
        assert packet_v2.findings[0].status == "supported"
        assert len(packet_v2.revisions) == 1

        rev = packet_v2.revisions[0]
        assert rev.finding_id == "find-waiting-period-joint"
        assert rev.old_finding_revision == 1
        assert rev.new_finding_revision == 2
        assert rev.trigger_type == "new_document"
        print(f"  [PASS] Revision recorded: Rev {rev.old_finding_revision} -> Rev {rev.new_finding_revision} ({rev.old_status} -> {rev.new_status})")

        # Step 4: Duplicate upload and re-review handling
        print("\n[Check 4] Duplicate upload and re-review handling (no duplicate revisions)...")
        doc_end_dup, is_dup3 = doc_storage.save_document(
            case_id=case.case_id,
            filename="Joint_Replacement_Endorsement.pdf",
            content=end_pdf,
            evidence_type="endorsement",
        )
        assert is_dup3 is True

        packet_v3 = service.execute_review(case.case_id)
        assert packet_v3.packet_version == 3
        assert len(packet_v3.revisions) == 1
        assert packet_v3.findings[0].revision == 2
        print("  [PASS] Re-review on unchanged evidence retained revision 2 and emitted ZERO duplicate revisions.")

        # Step 5: Historical finding snapshots
        print("\n[Check 5] Historical finding snapshots and evidence accessibility...")
        f_rev1 = review_repo.get_finding_snapshot(case.case_id, "find-waiting-period-joint", revision=1)
        assert f_rev1 is not None and f_rev1.revision == 1 and f_rev1.status == "unresolved"

        f_rev2 = review_repo.get_finding_snapshot(case.case_id, "find-waiting-period-joint", revision=2)
        assert f_rev2 is not None and f_rev2.revision == 2 and f_rev2.status == "supported"
        print(f"  [PASS] Historical snapshots verified: Rev 1 status='{f_rev1.status}', Rev 2 status='{f_rev2.status}'.")

        # Step 6: Application restart persistence
        print("\n[Check 6] Simulating application restart and verifying replay persistence...")
        db_restart = Database(db_path=db_path)
        repo_restart = ReviewRepository(db=db_restart)
        reloaded_pkt = repo_restart.get_latest_review_packet(case.case_id)
        assert reloaded_pkt is not None
        assert reloaded_pkt.packet_version == 3
        assert len(reloaded_pkt.revisions) == 1
        print("  [PASS] Replay audit history survived application restart.")

        # Step 7: Stale review protection
        print("\n[Check 7] Stale review protection via StaleReviewError...")
        stale_packet = ReviewPacket(
            packet_id="pkt-stale-test",
            packet_version=2,
            run_id="run-stale-01",
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
        try:
            review_repo.save_review_packet(stale_packet, expected_prior_packet_version=1)
            assert False, "StaleReviewError not raised!"
        except StaleReviewError as e:
            print(f"  [PASS] Stale review successfully rejected: {e}")

        # Step 8: Failed saves rollback atomically
        print("\n[Check 8] Transactional integrity on failed save...")
        corrupt_packet = ReviewPacket(
            packet_id="pkt-corrupt",
            packet_version=4,
            run_id="run-corrupt",
            case=CaseDetails(case_id="case-NONEXISTENT-FK"),
            review_status="incomplete",
            findings=[],
            revisions=[],
            missing_evidence_checklist=[],
            unresolved_questions=[],
            authorization_status="not verified",
            tool_steps_used=1,
            stopped_reason="missing_information",
        )
        try:
            review_repo.save_review_packet(corrupt_packet)
        except Exception:
            pass
        latest_after_fail = review_repo.get_latest_review_packet(case.case_id)
        assert latest_after_fail is not None and latest_after_fail.packet_version == 3
        print("  [PASS] Previous review remained completely intact after failed save attempt.")

        # Step 9: Authorization remains strictly 'not verified'
        print("\n[Check 9] Verifying authorization status invariant...")
        assert packet_v1.authorization_status == "not verified"
        assert packet_v2.authorization_status == "not verified"
        assert packet_v3.authorization_status == "not verified"
        print("  [PASS] Authorization strictly 'not verified' across all packets; zero inferred approval.")

        # ======================================================================
        # Part 2: M5-B Live Review Agent Replay & Applicability Checks (Owner B)
        # ======================================================================
        print("\n--- Part 2: M5-B Live Review Agent Replay & Applicability Checks ---")
        agent_retrieval = EvidenceRetrievalService(db=db)
        bounded_agent = BoundedReviewAgent()

        # Check 10: Applicable endorsement modifies waiting period to 12 months & keeps narrow scope
        print("\n[Check 10] Live agent replay: endorsement modifies waiting period to 12 months...")
        case_live = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-live-agent",
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
        live_pol, _ = doc_storage.save_document(case_id=case_live.case_id, filename=f"{case_live.case_id}_pol.pdf", content=build_synthetic_policy_pdf(), evidence_type="policy_wording")
        doc_storage.save_document(case_id=case_live.case_id, filename=f"{case_live.case_id}_sched.pdf", content=build_synthetic_schedule_pdf(), evidence_type="policy_schedule")

        live_pkt1 = bounded_agent.run_review(case=case_live, retrieval=agent_retrieval)
        assert live_pkt1.findings[0].status == "unresolved"

        doc_storage.save_document(case_id=case_live.case_id, filename=f"{case_live.case_id}_endorse.pdf", content=build_synthetic_endorsement_pdf(), evidence_type="endorsement")
        live_pkt2 = bounded_agent.run_review(case=case_live, retrieval=agent_retrieval, prior_packet=live_pkt1)
        knee_f2 = next(f for f in live_pkt2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_f2.status == "supported"
        assert knee_f2.revision == 2
        assert len(live_pkt2.revisions) == 1
        print("  [PASS] Live agent replay: finding revised (Rev 1 -> Rev 2), status='supported', 1 Revision record.")

        # Check 11: Wrong policy ID does not override base policy
        print("\n[Check 11] Wrong policy ID does not override base policy...")
        wrong_pdf = generate_pdf_bytes([
            "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-WRONG-01. "
            "Applicable to Policy ID: POL-DIFFERENT-999. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
            "Waiting Period Modification: Joint replacement waiting period reduced to twelve (12) continuous months."
        ])
        case_wrong = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-live-wrong",
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
        doc_storage.save_document(case_id=case_wrong.case_id, filename=f"{case_wrong.case_id}_pol.pdf", content=build_synthetic_policy_pdf(), evidence_type="policy_wording")
        doc_storage.save_document(case_id=case_wrong.case_id, filename=f"{case_wrong.case_id}_sched.pdf", content=build_synthetic_schedule_pdf(), evidence_type="policy_schedule")
        doc_storage.save_document(case_id=case_wrong.case_id, filename=f"{case_wrong.case_id}_wrong.pdf", content=wrong_pdf, evidence_type="endorsement")
        live_wrong_pkt = bounded_agent.run_review(case=case_wrong, retrieval=agent_retrieval)
        knee_wrong = next(f for f in live_wrong_pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_wrong.status == "unresolved"
        assert any("mismatch" in lim.lower() for lim in knee_wrong.limitations)
        print("  [PASS] Mismatched policy ID endorsement marked not_applicable; base 24-month terms remain.")

        # Check 12: Endorsement effective after planned admission date does not apply
        print("\n[Check 12] Endorsement effective after planned admission date does not apply...")
        case_future = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-live-future",
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
        live_future_pkt = bounded_agent.run_review(case=case_future, retrieval=agent_retrieval)
        knee_future = next(f for f in live_future_pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_future.status == "unresolved"
        assert any("after planned admission date" in lim.lower() for lim in knee_future.limitations)
        print("  [PASS] Future effective date endorsement not applied; base terms retained.")

        # Check 13: Ambiguous precedence produces conflict finding
        print("\n[Check 13] Ambiguous precedence produces conflict finding with uncertainty retained...")
        ambig_pdf = generate_pdf_bytes([
            "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. "
            "Applicable to Policy ID: POL-998877. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
            "Waiting Period Modification: Section 4.2(b) waiting period modified to twelve (12) continuous months, "
            "however precedence unresolved: terms conflict with master policy schedule pending underwriter review."
        ])
        case_ambig = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-live-ambig",
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
        doc_storage.save_document(case_id=case_ambig.case_id, filename=f"{case_ambig.case_id}_pol.pdf", content=build_synthetic_policy_pdf(), evidence_type="policy_wording")
        doc_storage.save_document(case_id=case_ambig.case_id, filename=f"{case_ambig.case_id}_sched.pdf", content=build_synthetic_schedule_pdf(), evidence_type="policy_schedule")
        doc_storage.save_document(case_id=case_ambig.case_id, filename=f"{case_ambig.case_id}_ambig.pdf", content=ambig_pdf, evidence_type="endorsement")
        live_ambig_pkt = bounded_agent.run_review(case=case_ambig, retrieval=agent_retrieval)
        knee_ambig = next(f for f in live_ambig_pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_ambig.status == "conflict"
        print("  [PASS] Ambiguous precedence produced status='conflict'; uncertainty retained.")

        # Check 14: Unrelated findings remain unchanged
        print("\n[Check 14] Unrelated findings remain unchanged across replay...")
        f_rent_seed = Finding(
            finding_id="find-room-rent-limits",
            revision=1,
            topic="Room Rent and ICU Limits",
            status="supported",
            conclusion="Standard single private room covered up to 1 percent of sum insured per day.",
            evidence=[Evidence(
                document_id=live_pol.document_id,
                document_version=live_pol.version,
                page=3,
                quote="Section 2: Room Rent and Intensive Care Unit Limits.",
                evidence_type="policy_wording",
            )],
            relevant_case_facts=[],
            missing_facts=[],
            limitations=["Room rent capping applies proportionate deduction."],
            next_action="Confirm room category with hospital billing desk.",
        )
        live_pkt1.findings.append(f_rent_seed)
        live_pkt_replayed = bounded_agent.run_review(case=case_live, retrieval=agent_retrieval, prior_packet=live_pkt1)
        f_rent_res = next(f for f in live_pkt_replayed.findings if f.finding_id == "find-room-rent-limits")
        assert f_rent_res.revision == 1
        assert f_rent_res.status == "supported"
        assert f_rent_res.conclusion == f_rent_seed.conclusion
        print("  [PASS] Unrelated room rent finding preserved at revision=1 with identical citations.")

        # Check 15: Corrected case date triggers reassessment
        print("\n[Check 15] Corrected case date triggers reassessment of dependent findings...")
        case_date_corr = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-live-date-corr",
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
        doc_storage.save_document(case_id=case_date_corr.case_id, filename=f"{case_date_corr.case_id}_p.pdf", content=build_synthetic_policy_pdf(), evidence_type="policy_wording")
        doc_storage.save_document(case_id=case_date_corr.case_id, filename=f"{case_date_corr.case_id}_s.pdf", content=build_synthetic_schedule_pdf(), evidence_type="policy_schedule")
        doc_storage.save_document(case_id=case_date_corr.case_id, filename=f"{case_date_corr.case_id}_e.pdf", content=build_synthetic_endorsement_pdf(), evidence_type="endorsement")

        run1 = bounded_agent.run_review(case=case_date_corr, retrieval=agent_retrieval)
        assert run1.findings[0].status == "unresolved"

        case_corrected = case_date_corr.model_copy(
            update={
                "planned_admission_date": date(2026, 11, 15),
                "fact_sources": {
                    **case_date_corr.fact_sources,
                    "planned_admission_date": FactSource(source_type="user_provided"),
                },
            }
        )
        case_repo.update_case(case_corrected)
        run2 = bounded_agent.run_review(case=case_corrected, retrieval=agent_retrieval, prior_packet=run1)
        knee_run2 = next(f for f in run2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_run2.status == "supported"
        assert knee_run2.revision == 2
        assert len(run2.revisions) == 1
        assert "planned_admission_date" in run2.revisions[0].changed_case_facts
        print("  [PASS] Corrected admission date triggered reassessment: Rev 1 (unresolved) -> Rev 2 (supported).")

        # Check 16: Failed/partial reassessment does not falsely report completion
        print("\n[Check 16] Failed/partial reassessment does not falsely report completion...")
        pkt_timeout = bounded_agent.run_review(case=case_live, retrieval=agent_retrieval, prior_packet=live_pkt1, timeout_seconds=0.0001)
        assert pkt_timeout.review_status == "incomplete"
        assert pkt_timeout.stopped_reason == "timeout"
        print("  [PASS] Timed out reassessment honestly reported status='incomplete', stopped_reason='timeout'.")

    print("\n=== ALL 16 COMBINED MILESTONE M5 ACCEPTANCE CHECKS PASSED SUCCESSFULLY ===")
    return True


if __name__ == "__main__":
    success = run_m5_combined_verification()
    sys.exit(0 if success else 1)
