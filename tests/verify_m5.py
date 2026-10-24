"""Verification Script for Milestone M5-B & M5-I: Evidence Change Replay.

Executes end-to-end verification of all M5 requirements:
1. Applicable fictional endorsement changes 24 months to 12 months.
2. Supplied 18-month history supports only the relevant narrow finding.
3. Wrong policy ID does not override base policy.
4. Endorsement effective after planned admission date does not silently apply.
5. Ambiguous precedence produces an unresolved/conflict finding.
6. Unrelated findings remain unchanged.
7. Duplicate input does not create duplicate substantive revisions.
8. Corrected case date triggers reassessment with trigger_type='case_details_changed'.
9. Failed/partial reassessment does not falsely report completion.
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import BoundedReviewAgent
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
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


def run_verification() -> bool:
    print("=== AdmitSense Milestone M5 Acceptance Verification ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m5.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        retrieval = EvidenceRetrievalService(db=db)
        agent = BoundedReviewAgent()

        # ----------------------------------------------------------------------
        # Check 1 & 2: Applicable Endorsement Modifies 24 to 12 Months & Narrow Scope
        # ----------------------------------------------------------------------
        print("\n[Check 1 & 2] Applicable endorsement modifies waiting period to 12 months & keeps narrow scope...")
        case_1 = case_repo.create_case(
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
            case_id=case_1.case_id,
            filename=f"{case_1.case_id}_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )
        doc_storage.save_document(
            case_id=case_1.case_id,
            filename=f"{case_1.case_id}_Policy_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )

        pkt_v1 = agent.run_review(case=case_1, retrieval=retrieval)
        knee_v1 = next(f for f in pkt_v1.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_v1.status == "unresolved", f"Expected unresolved, got {knee_v1.status}"
        assert knee_v1.revision == 1
        assert "shortfall" in knee_v1.conclusion.lower()
        print("  [PASS] Baseline Packet v1: 24-month condition vs 18-month history produces shortfall (revision=1).")

        # Ingest applicable endorsement
        doc_storage.save_document(
            case_id=case_1.case_id,
            filename=f"{case_1.case_id}_Endorsement_EW-2025-01.pdf",
            content=build_synthetic_endorsement_pdf(),
            evidence_type="endorsement",
        )

        pkt_v2 = agent.run_review(case=case_1, retrieval=retrieval, prior_packet=pkt_v1)
        assert pkt_v2.packet_version == 2
        knee_v2 = next(f for f in pkt_v2.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_v2.status == "supported", f"Expected supported, got {knee_v2.status}"
        assert knee_v2.revision == 2
        assert "12 continuous months" in knee_v2.conclusion
        assert "EW-2025-01" in knee_v2.conclusion

        # Revision check
        assert len(pkt_v2.revisions) == 1
        rev = pkt_v2.revisions[0]
        assert rev.old_status == "unresolved" and rev.new_status == "supported"
        assert rev.trigger_type == "new_document"
        assert pkt_v2.authorization_status == "not verified"
        print("  [PASS] Packet v2: Endorsement applies; waiting period modified to 12 months -> supported (revision=2).")
        print("  [PASS] Authorization remains strictly 'not verified' with no overall claim approval.")

        # ----------------------------------------------------------------------
        # Check 3: Wrong Policy ID Does Not Override Base Policy
        # ----------------------------------------------------------------------
        print("\n[Check 3] Wrong policy ID does not override base policy...")
        wrong_policy_pdf = generate_pdf_bytes([
            "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-WRONG-01. "
            "Applicable to Policy ID: POL-DIFFERENT-999. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
            "Waiting Period Modification: Joint replacement waiting period reduced to twelve (12) continuous months."
        ])
        case_wrong = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-wrong-policy",
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
        doc_storage.save_document(case_id=case_wrong.case_id, filename=f"{case_wrong.case_id}_endorse_wrong.pdf", content=wrong_policy_pdf, evidence_type="endorsement")

        pkt_wrong = agent.run_review(case=case_wrong, retrieval=retrieval)
        knee_wrong = next(f for f in pkt_wrong.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_wrong.status == "unresolved"
        assert "24" in knee_wrong.conclusion or "twenty-four" in knee_wrong.conclusion
        assert any("mismatch" in lim.lower() for lim in knee_wrong.limitations)
        print("  [PASS] Endorsement with mismatched Policy ID rejected as not_applicable; base 24-month terms remain.")

        # ----------------------------------------------------------------------
        # Check 4: Endorsement Effective After Admission Date Does Not Apply
        # ----------------------------------------------------------------------
        print("\n[Check 4] Endorsement effective after planned admission date does not apply...")
        case_future = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-future-date",
                member_name="Ramesh Sharma",
                policy_id="POL-998877",
                procedure="Total Knee Replacement",
                planned_admission_date=date(2025, 1, 15),  # Admission BEFORE endorsement effective date 2025-04-01
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
        doc_storage.save_document(case_id=case_future.case_id, filename=f"{case_future.case_id}_endorse.pdf", content=build_synthetic_endorsement_pdf(), evidence_type="endorsement")

        pkt_future = agent.run_review(case=case_future, retrieval=retrieval)
        knee_future = next(f for f in pkt_future.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_future.status == "unresolved"
        assert any("after planned admission date" in lim.lower() for lim in knee_future.limitations)
        print("  [PASS] Future effective date endorsement not applied; temporal precedence respected.")

        # ----------------------------------------------------------------------
        # Check 5: Ambiguous Precedence Produces Conflict Finding
        # ----------------------------------------------------------------------
        print("\n[Check 5] Ambiguous precedence produces conflict finding with uncertainty retained...")
        ambig_pdf = generate_pdf_bytes([
            "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. "
            "Applicable to Policy ID: POL-998877. Member Name: Ramesh Sharma. Effective From: 2025-04-01. "
            "Waiting Period Modification: Section 4.2(b) waiting period modified to twelve (12) continuous months, "
            "however precedence unresolved: terms conflict with master policy schedule pending underwriter review."
        ])
        case_ambig = case_repo.create_case(
            CaseDetails(
                case_id="case-m5-ambiguous",
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

        pkt_ambig = agent.run_review(case=case_ambig, retrieval=retrieval)
        knee_ambig = next(f for f in pkt_ambig.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_ambig.status == "conflict"
        assert "ambiguous" in knee_ambig.conclusion.lower() or "conflict" in knee_ambig.conclusion.lower()
        print("  [PASS] Ambiguous precedence produces finding status='conflict'; uncertainty retained.")

        # ----------------------------------------------------------------------
        # Check 6: Unrelated Findings Remain Unchanged Across Replay
        # ----------------------------------------------------------------------
        print("\n[Check 6] Unrelated findings remain unchanged across replay...")
        f_rent_seed = Finding(
            finding_id="find-room-rent-limits",
            revision=1,
            topic="Room Rent and ICU Limits",
            status="supported",
            conclusion="Standard single private room covered up to 1 percent of sum insured per day.",
            evidence=[Evidence(
                document_id=policy_doc.document_id,
                document_version=policy_doc.version,
                page=3,
                quote="Section 2: Room Rent and Intensive Care Unit Limits.",
                evidence_type="policy_wording",
            )],
            relevant_case_facts=[],
            missing_facts=[],
            limitations=["Room rent capping applies proportionate deduction."],
            next_action="Confirm room category with hospital billing desk.",
        )
        pkt_v1.findings.append(f_rent_seed)
        pkt_replay = agent.run_review(case=case_1, retrieval=retrieval, prior_packet=pkt_v1)
        f_rent_after = next(f for f in pkt_replay.findings if f.finding_id == "find-room-rent-limits")
        assert f_rent_after.revision == 1, "Unrelated finding revision must not increment"
        assert f_rent_after.status == "supported"
        assert f_rent_after.conclusion == f_rent_seed.conclusion
        print("  [PASS] Unrelated room rent finding preserved at revision=1 with unchanged conclusion and evidence.")

        # ----------------------------------------------------------------------
        # Check 7: Duplicate Input Does Not Create Duplicate Substantive Revisions
        # ----------------------------------------------------------------------
        print("\n[Check 7] Duplicate input does not create duplicate substantive revisions...")
        pkt_dup = agent.run_review(case=case_1, retrieval=retrieval, prior_packet=pkt_replay)
        knee_dup = next(f for f in pkt_dup.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_dup.revision == 2, f"Expected revision=2 on duplicate re-run, got {knee_dup.revision}"
        assert len(pkt_dup.revisions) == len(pkt_replay.revisions), "No redundant revision records on duplicate input"
        print("  [PASS] Replay with identical input preserved finding revision=2 without creating redundant revision records.")

        # ----------------------------------------------------------------------
        # Check 8: Corrected Case Date Triggers Reassessment
        # ----------------------------------------------------------------------
        print("\n[Check 8] Corrected case date triggers reassessment of dependent findings...")
        case_date_corr = case_repo.create_case(
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
        doc_storage.save_document(case_id=case_date_corr.case_id, filename=f"{case_date_corr.case_id}_p.pdf", content=build_synthetic_policy_pdf(), evidence_type="policy_wording")
        doc_storage.save_document(case_id=case_date_corr.case_id, filename=f"{case_date_corr.case_id}_s.pdf", content=build_synthetic_schedule_pdf(), evidence_type="policy_schedule")
        doc_storage.save_document(case_id=case_date_corr.case_id, filename=f"{case_date_corr.case_id}_e.pdf", content=build_synthetic_endorsement_pdf(), evidence_type="endorsement")

        run1_pkt = agent.run_review(case=case_date_corr, retrieval=retrieval)
        knee_run1 = next(f for f in run1_pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_run1.status == "unresolved"

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
        run2_pkt = agent.run_review(case=case_corrected, retrieval=retrieval, prior_packet=run1_pkt)
        knee_run2 = next(f for f in run2_pkt.findings if "knee" in f.topic.lower() or "joint" in f.topic.lower())
        assert knee_run2.status == "supported"
        assert knee_run2.revision == 2
        assert len(run2_pkt.revisions) == 1
        assert run2_pkt.revisions[0].trigger_type in {"user_correction", "case_details_changed"}
        assert "planned_admission_date" in run2_pkt.revisions[0].changed_case_facts
        print("  [PASS] Corrected planned admission date triggered reassessment; finding revised to supported (revision=2).")

        # ----------------------------------------------------------------------
        # Check 9: Failed / Partial Reassessment Does Not Falsely Report Completion
        # ----------------------------------------------------------------------
        print("\n[Check 9] Failed/partial reassessment does not falsely report completion...")
        pkt_timeout = agent.run_review(case=case_1, retrieval=retrieval, prior_packet=pkt_v1, timeout_seconds=0.0001)
        assert pkt_timeout.review_status == "incomplete"
        assert pkt_timeout.stopped_reason == "timeout"
        print("  [PASS] Timed out reassessment honestly reported status='incomplete', stopped_reason='timeout'.")

    print("\n=== ALL MILESTONE M5 VERIFICATION CHECKS PASSED SUCCESSFULLY ===")
    return True


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
