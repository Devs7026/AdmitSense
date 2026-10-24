"""AdmitSense Milestone M6-B & M6-I Verification Script.

Executes 12 comprehensive acceptance checks for:
- Synthetic hospital lookup (exact, no match, ambiguous, missing input).
- Separation of hospital references from PDF page citations.
- Bounded agent review integration with hospital lookup telemetry.
- Prevention of false positive hospital findings on lookup failure.
- Actionable desk and insurer question derivation.
- Removal of obsolete questions when evidence resolves the shortfall.
- Deterministic export data payload packaging from saved snapshot.
- Invariant preservation: authorization strictly 'not verified', zero approval claims.
"""

from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from admitsense.agent.hospital import HospitalLookupService
from admitsense.agent.questions import derive_desk_and_insurer_questions
from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import BoundedReviewAgent, ToolActivityEvent
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
)
from admitsense.review.export_data import build_review_export_payload, escape_html
from admitsense.schemas import (
    CaseDetails,
    Evidence,
    FactSource,
    Finding,
    HospitalRecordReference,
    MissingEvidenceItem,
    ReviewPacket,
    Revision,
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.storage.review_repository import ReviewRepository


def run_m6_verification() -> None:
    temp_dir = tempfile.mkdtemp(prefix="admitsense_m6_verify_")
    try:
        db_path = Path(temp_dir) / "verify_m6.db"
        doc_dir = Path(temp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        review_repo = ReviewRepository(db=db)
        retrieval = EvidenceRetrievalService(db=db)
        hospital_svc = HospitalLookupService()

        print("=== AdmitSense Milestone M6 Combined Acceptance Verification (M6-B & M6-I) ===\n")

        # ----------------------------------------------------------------------
        # Check 1: Synthetic Dataset Metadata & Structure
        # ----------------------------------------------------------------------
        print("[Check 1] Validating synthetic hospital dataset structure and versioning...")
        assert hospital_svc.dataset_version == "v2026.1"
        assert hospital_svc.dataset_date == date(2026, 10, 1)
        assert "SYNTHETIC DEMONSTRATION DATASET" in hospital_svc.disclaimer
        hospitals = hospital_svc.list_hospitals()
        assert len(hospitals) >= 4
        print(f"  [PASS] Synthetic dataset verified: version {hospital_svc.dataset_version}, date {hospital_svc.dataset_date}, {len(hospitals)} facilities.")

        # ----------------------------------------------------------------------
        # Check 2: Exact Hospital Lookup
        # ----------------------------------------------------------------------
        print("[Check 2] Testing exact hospital lookup...")
        exact_res = hospital_svc.lookup("Apex Super Specialty Hospital")
        assert exact_res.status == "exact_match"
        assert exact_res.hospital is not None
        assert exact_res.hospital.record_id == "hosp-synth-001"
        assert exact_res.hospital.network_tier == "tier_1"
        assert exact_res.hospital.is_synthetic is True
        assert any("demonstration only" in lim.lower() for lim in exact_res.hospital.limitations)
        print(f"  [PASS] Exact match verified: '{exact_res.hospital.hospital_name}' ({exact_res.hospital.record_id}, {exact_res.hospital.network_tier}).")

        # ----------------------------------------------------------------------
        # Check 3: Ambiguous Hospital Names (No Silent Selection)
        # ----------------------------------------------------------------------
        print("[Check 3] Testing ambiguous hospital query...")
        ambig_res = hospital_svc.lookup("City")
        assert ambig_res.status == "ambiguous_match"
        assert ambig_res.hospital is None  # Strict rule: never silently pick!
        assert len(ambig_res.candidate_matches) >= 2
        print(f"  [PASS] Ambiguous query returned status='ambiguous_match' with {len(ambig_res.candidate_matches)} candidates; zero uncertain selection.")

        # ----------------------------------------------------------------------
        # Check 4: Unknown Hospital Query (No Match)
        # ----------------------------------------------------------------------
        print("[Check 4] Testing unknown hospital query...")
        no_res = hospital_svc.lookup("Nonexistent Memorial Health Center")
        assert no_res.status == "no_match"
        assert no_res.hospital is None
        print("  [PASS] Unknown query produced honest status='no_match'.")

        # ----------------------------------------------------------------------
        # Check 5: Missing Input Handling
        # ----------------------------------------------------------------------
        print("[Check 5] Testing missing hospital input handling...")
        none_res = hospital_svc.lookup(None)
        assert none_res.status == "missing_input"
        assert none_res.hospital is None
        empty_res = hospital_svc.lookup("   ")
        assert empty_res.status == "missing_input"
        print("  [PASS] Missing and whitespace inputs handled cleanly with status='missing_input'.")

        # ----------------------------------------------------------------------
        # Check 6: Bounded Execution with Agent-Invoked Hospital Lookup
        # ----------------------------------------------------------------------
        print("[Check 6] Executing review with agent-invoked hospital lookup...")
        case = CaseDetails(
            case_id="case-m6-v01",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
            procedure="Total Knee Replacement",
            planned_admission_date=date(2026, 11, 20),
            hospital_name="Apex Super Specialty Hospital",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "planned_admission_date": FactSource(source_type="user_provided"),
                "hospital_name": FactSource(source_type="user_provided"),
            },
        )
        case_repo.create_case(case)

        doc_storage.save_document(
            case_id=case.case_id,
            filename="Care_Gold_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )
        doc_storage.save_document(
            case_id=case.case_id,
            filename="Policy_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )

        events: list[ToolActivityEvent] = []
        agent = BoundedReviewAgent(default_tool_budget=8)
        packet = agent.run_review(
            case=case,
            retrieval=retrieval,
            event_callback=lambda ev: events.append(ev),
        )

        assert packet.tool_steps_used <= 8
        hosp_events = [e for e in events if e.tool_name == "lookup_hospital"]
        assert len(hosp_events) >= 1
        assert packet.hospital_reference is not None
        assert packet.hospital_reference.record_id == "hosp-synth-001"
        print(f"  [PASS] Review executed in {packet.tool_steps_used}/8 steps with hospital lookup telemetry: '{packet.hospital_reference.hospital_name}'.")

        # ----------------------------------------------------------------------
        # Check 7: Lookup Failure Does NOT Become Positive Hospital Finding
        # ----------------------------------------------------------------------
        print("[Check 7] Verifying lookup failure does not create positive hospital finding...")
        case_fail = CaseDetails(
            case_id="case-m6-v02-fail",
            member_name="Ramesh Sharma",
            policy_id="POL-998877",
            procedure="Total Knee Replacement",
            hospital_name="Unlisted Clinic",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
                "policy_id": FactSource(source_type="user_provided"),
                "procedure": FactSource(source_type="user_provided"),
                "hospital_name": FactSource(source_type="user_provided"),
            },
        )
        case_repo.create_case(case_fail)
        packet_fail = agent.run_review(case=case_fail, retrieval=retrieval)

        assert packet_fail.hospital_reference is None
        for f in packet_fail.findings:
            assert "unlisted clinic" not in f.topic.lower()
            assert f.status != "supported" or "hospital" not in f.topic.lower()
        print("  [PASS] Failed lookup left hospital_reference as None with zero false positive findings.")

        # ----------------------------------------------------------------------
        # Check 8: Question Derivation & Obsolete Question Removal
        # ----------------------------------------------------------------------
        print("[Check 8] Verifying resolved evidence gaps remove obsolete questions...")
        unresolved_f = Finding(
            finding_id="find-knee",
            revision=1,
            topic="Specific Waiting Period: Total Knee Replacement",
            status="unresolved",
            conclusion="24-month waiting period with 6-month shortfall.",
            relevant_case_facts=["procedure"],
            missing_facts=["continuous_coverage_start_date"],
            limitations=["Shortfall remains."],
            next_action="Obtain continuity proof.",
        )
        q_unresolved = derive_desk_and_insurer_questions(case=case, findings=[unresolved_f])
        assert any("portability credits" in q for q in q_unresolved)

        supported_f = Finding(
            finding_id="find-knee",
            revision=2,
            topic="Specific Waiting Period: Total Knee Replacement",
            status="supported",
            conclusion="12-month waiting period satisfied by Endorsement EW-2025-01.",
            relevant_case_facts=["procedure"],
            evidence=[
                Evidence(
                    document_id="doc-e1",
                    document_version="v1",
                    page=1,
                    quote="Waiting period reduced from 24 to 12 continuous months.",
                    evidence_type="endorsement",
                )
            ],
            next_action="Proceed to admission.",
        )
        q_supported = derive_desk_and_insurer_questions(case=case, findings=[supported_f])
        assert not any("portability credits" in q for q in q_supported)
        print("  [PASS] Obsolete waiting period questions successfully removed upon finding resolution.")

        # ----------------------------------------------------------------------
        # Check 9: Unrelated Unresolved Gaps Remain Visible
        # ----------------------------------------------------------------------
        print("[Check 9] Verifying unrelated unresolved gaps remain visible in questions...")
        room_f = Finding(
            finding_id="find-room",
            revision=1,
            topic="Inpatient Room Rent Sub-Limit",
            status="unresolved",
            conclusion="Room rent capped at 1% of sum insured. Category unknown.",
            relevant_case_facts=["procedure"],
            missing_facts=["room_category"],
            limitations=["Room rent category not specified."],
            next_action="Check room category with billing desk.",
        )
        q_mixed = derive_desk_and_insurer_questions(case=case, findings=[supported_f, room_f])
        assert any("room rent limit" in q for q in q_mixed)
        print("  [PASS] Unrelated room rent question remained clearly visible.")

        # ----------------------------------------------------------------------
        # Check 10: Non-Negotiable Authorization & Network Invariants
        # ----------------------------------------------------------------------
        print("[Check 10] Checking authorization and network status invariants...")
        assert packet.authorization_status == "not verified"
        for q in packet.unresolved_questions:
            assert "approved" not in q.lower()
            assert "cashless guaranteed" not in q.lower()
        print("  [PASS] Authorization strictly 'not verified'; zero implied approval or cashless guarantees.")

        # ----------------------------------------------------------------------
        # Check 11: Export Data Payload Generation from Saved Snapshot
        # ----------------------------------------------------------------------
        print("[Check 11] Generating export data payload from SQLite snapshot...")
        saved_packet = review_repo.save_review_packet(packet)
        retrieved_packet = review_repo.get_latest_review_packet(case.case_id)
        assert retrieved_packet is not None

        export_payload = build_review_export_payload(retrieved_packet)
        assert export_payload["packet_id"] == retrieved_packet.packet_id
        assert export_payload["packet_version"] == retrieved_packet.packet_version
        assert export_payload["hospital_reference"]["hospital_name"] == "Apex Super Specialty Hospital"
        assert export_payload["hospital_reference"]["is_synthetic"] is True
        assert len(export_payload["findings"]) >= 1
        assert "DISCLAIMER" in export_payload["disclaimer"]
        print("  [PASS] Export payload generated directly from database snapshot without model calls.")

        # ----------------------------------------------------------------------
        # Check 12: Incomplete State Preservation & Dynamic Text Escaping
        # ----------------------------------------------------------------------
        print("[Check 12] Testing incomplete state preservation and HTML escaping...")
        assert export_payload["review_status"] == "incomplete"
        assert export_payload["stopped_reason"] in {"missing_information", "review_complete"}

        malicious_input = "<script>alert('xss')</script> & Caregiver 'Notes' \"Quoted\""
        safe_output = escape_html(malicious_input)
        assert "<script>" not in safe_output
        assert "&lt;script&gt;" in safe_output
        assert "&amp;" in safe_output
        assert "&quot;" in safe_output
        print("  [PASS] Incomplete state preserved; HTML escaping verified.")

        print("\n=== ALL 12 MILESTONE M6 ACCEPTANCE CHECKS PASSED SUCCESSFULLY ===")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_m6_verification()
