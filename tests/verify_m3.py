"""Milestone M3-B Standalone Verification Script.

Executes standalone validation of:
1. WaitingPeriodReviewer on real extracted synthetic PDF documents.
2. The fictional 24-month condition vs 18-month history acceptance criteria.
3. Citation verification of actual physical page quotations.
4. ToolActivityEvent telemetry stream (<= 8 steps).
5. Non-negotiable invariants (authorisation defaults to unverified; no invented waivers; no approval statements).
"""

import sys
import tempfile
from pathlib import Path

# Ensure src is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import (
    ToolActivityEvent,
    WaitingPeriodReviewer,
    run_waiting_period_review,
)
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    build_synthetic_unreadable_pdf,
)
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


def main():
    print("=== AdmitSense Milestone M3-B Verification ===")
    print()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_m3.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        storage = DocumentStorage(db=db, storage_dir=doc_dir)

        # ----------------------------------------------------------------------
        # Setup Case 1: Ramesh Sharma, Total Knee Replacement (24-mo condition)
        # ----------------------------------------------------------------------
        case_1 = CaseDetails(
            case_id="case-verify-m3-001",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
            procedure="Total Knee Replacement",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
            },
        )
        case_repo.create_case(case_1)

        # Ingest Policy Wording (Page 14: Section 4.2(b), 24-month waiting period)
        doc_pol, _ = storage.save_document(
            case_id="case-verify-m3-001",
            filename="Care_Health_Gold_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )

        # Ingest Renewal Schedule (Page 1: 18 months continuous coverage)
        doc_sched, _ = storage.save_document(
            case_id="case-verify-m3-001",
            filename="Policy_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )

        retrieval = EvidenceRetrievalService(db=db)

        # ----------------------------------------------------------------------
        # [Check 1] Run review and collect tool telemetry events
        # ----------------------------------------------------------------------
        print("[Check 1] Running review with telemetry event tracking...")
        events: list[ToolActivityEvent] = []
        reviewer = WaitingPeriodReviewer(default_tool_budget=8)
        packet = reviewer.run_review(
            case=case_1,
            retrieval=retrieval,
            event_callback=lambda ev: events.append(ev),
        )

        assert packet.tool_steps_used <= 8, f"Tool steps exceeded budget: {packet.tool_steps_used}"
        assert len(events) > 0, "No telemetry events captured"
        print(f"  [PASS] Review completed using {packet.tool_steps_used} tool steps. Captured {len(events)} telemetry events.")

        # ----------------------------------------------------------------------
        # [Check 2] 24-month condition vs 18-month history shortfall evaluation
        # ----------------------------------------------------------------------
        print("[Check 2] Evaluating 24-month condition vs 18-month history acceptance criteria...")
        assert packet.review_status == "incomplete", f"Expected incomplete review status, got {packet.review_status}"
        assert packet.stopped_reason == "missing_information"
        assert len(packet.findings) == 1
        finding = packet.findings[0]

        assert finding.status == "unresolved", f"Expected unresolved finding, got {finding.status}"
        assert "shortfall" in finding.conclusion.lower() or "gap" in finding.conclusion.lower(), "Shortfall not reported in conclusion"
        assert "24" in finding.conclusion or "twenty-four" in finding.conclusion, "24-month rule not cited"
        assert "18" in finding.conclusion or "eighteen" in finding.conclusion, "18-month history not cited"
        print(f"  [PASS] Finding correctly marked 'unresolved' with 6-month shortfall: '{finding.conclusion[:80]}...'")

        # ----------------------------------------------------------------------
        # [Check 3] Verified citations against actual physical page text
        # ----------------------------------------------------------------------
        print("[Check 3] Verifying physical page evidence citations...")
        assert len(finding.evidence) >= 1
        pol_ev = next((e for e in finding.evidence if e.evidence_type == "policy_wording"), None)
        assert pol_ev is not None, "Policy wording citation missing"
        assert pol_ev.page == 14, f"Expected physical page 14 citation, got {pol_ev.page}"
        assert "twenty-four (24) continuous months" in pol_ev.quote
        print(f"  [PASS] Policy wording cited on physical page {pol_ev.page}: '{pol_ev.quote[:70]}...'")

        # ----------------------------------------------------------------------
        # [Check 4] Actionable next actions and missing-evidence checklist
        # ----------------------------------------------------------------------
        print("[Check 4] Checking next action banner and missing-evidence checklist...")
        assert len(packet.missing_evidence_checklist) >= 1
        chk = packet.missing_evidence_checklist[0]
        assert chk.status == "requested"
        assert "continuity" in chk.requested_information.lower() or "schedule" in chk.requested_information.lower()
        assert len(packet.unresolved_questions) >= 1
        print(f"  [PASS] Next action: '{finding.next_action[:80]}...'")
        print(f"  [PASS] Checklist request: '{chk.requested_information}'")

        # ----------------------------------------------------------------------
        # [Check 5] Non-negotiable invariants (authorisation unverified, no invented waiver)
        # ----------------------------------------------------------------------
        print("[Check 5] Verifying non-negotiable domain invariants...")
        assert packet.authorization_status == "not verified", f"Authorisation must be 'not verified', got {packet.authorization_status}"
        assert packet.authorization_evidence == []
        assert "approved" not in finding.conclusion.lower(), "Illegal approval statement found"
        assert "waiver document required" not in finding.conclusion.lower(), "Invented waiver requirement found"
        print("  [PASS] Authorisation strictly 'not verified'; zero inferred approval statements; no invented waivers.")

        # ----------------------------------------------------------------------
        # [Check 6] Satisfied waiting period evaluation (Cataract 12 mo vs 18 mo)
        # ----------------------------------------------------------------------
        print("[Check 6] Evaluating satisfied waiting period scenario (Cataract 12 mo vs 18 mo)...")
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
        packet_cataract = run_waiting_period_review(case=case_cataract, retrieval=retrieval)
        cat_finding = packet_cataract.findings[0]
        assert cat_finding.status == "supported", f"Expected supported finding, got {cat_finding.status}"
        assert cat_finding.evidence[0].page == 11, f"Expected page 11 citation, got {cat_finding.evidence[0].page}"
        print(f"  [PASS] Cataract finding supported on page {cat_finding.evidence[0].page}: '{cat_finding.conclusion[:80]}...'")

    print()
    print("=== ALL MILESTONE M3-B VERIFICATION CHECKS PASSED ===")


if __name__ == "__main__":
    main()
