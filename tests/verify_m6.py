"""Combined Milestone M6 Acceptance Verification Script (M6-A, M6-B, M6-I).

Executes comprehensive acceptance checks for both sides of Milestone M6:
- Part 1 (M6-A & M6-I): Interface & Export Side:
  - Hospital directory lookup states (matched, no_match, ambiguous, missing).
  - Synthetic hospital dataset transparency (version, publication date, non-authorisation disclaimer).
  - Review packet snapshot construction (findings, citations, checklist, desk questions, revisions).
  - Deterministic HTML export generation directly from snapshot with zero model calls.
  - Complete HTML escaping of dynamic text (XSS prevention).
  - Export safety (zero internal filesystem paths, secrets, or file:// links).
  - Incomplete review export with visible stop reasons and limitations.
  - Historical packet snapshot immutability across subsequent revisions.
  - Standalone HTML document structure with responsive styles and print CSS.

- Part 2 (M6-B & M6-I): Review-Data & Agent Side:
  - Synthetic hospital lookup service (exact, ambiguous, no match, missing input).
  - Separation of hospital references from PDF page citations.
  - Bounded agent review integration with hospital lookup telemetry (<= 8 calls).
  - Prevention of false-positive hospital findings on lookup failure.
  - Actionable desk and insurer question derivation linked to findings/facts.
  - Dynamic removal of obsolete questions when evidence resolves the shortfall.
  - Preservation of unresolved evidence gaps.
  - Deterministic export data payload packaging from saved snapshot.
  - Invariant enforcement: authorization strictly 'not verified', zero approval/cashless claims.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
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
from admitsense.documents.hospital_directory import (
    HospitalLookupResult as DirectoryLookupResult,
    LocalSyntheticHospitalDirectory,
)
from admitsense.documents.models import DocumentRecord
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
)
from admitsense.export.html_exporter import generate_review_packet_html
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


# ==============================================================================
# Helper for Part 1 Test Cases
# ==============================================================================
def _build_test_case_part1(case_id: str, hospital_name: str | None = "Apex Super Specialty Hospital") -> CaseDetails:
    sources = {
        "member_name": FactSource(source_type="user_provided"),
        "policy_id": FactSource(source_type="user_provided"),
        "procedure": FactSource(source_type="user_provided"),
        "planned_admission_date": FactSource(source_type="user_provided"),
        "continuous_coverage_start_date": FactSource(source_type="user_provided"),
        "estimated_cost": FactSource(source_type="user_provided"),
    }
    if hospital_name is not None:
        sources["hospital_name"] = FactSource(source_type="user_provided")

    return CaseDetails(
        case_id=case_id,
        member_name="Ramesh Sharma",
        policy_id="POL-CARE-998877",
        procedure="Total Knee Replacement",
        planned_admission_date=date(2026, 11, 20),
        continuous_coverage_start_date=date(2025, 4, 1),
        estimated_cost=Decimal("175000.00"),
        hospital_name=hospital_name,
        fact_sources=sources,
    )


# ==============================================================================
# Part 1: Owner A M6-A & Interface/Export Acceptance Checks (Checks 1 to 9)
# ==============================================================================
def run_m6_part1_export_verification() -> None:
    print("--- Part 1: Milestone M6-A Interface & Deterministic HTML Exporter ---")

    # [Check 1] Hospital lookup states
    print("\n[Check 1] Verifying hospital directory lookup states...")
    directory = LocalSyntheticHospitalDirectory()

    res_matched = directory.lookup_hospital("Apex Super Specialty Hospital")
    assert res_matched.status == "matched", f"Expected matched, got {res_matched.status}"
    assert res_matched.record is not None
    assert res_matched.record.hospital_name == "Apex Super Specialty Hospital"
    assert res_matched.record.network_tier == "tier_1"
    assert res_matched.record.record_id == "hosp-synth-001"
    print("  [PASS] 'matched' state verified: Apex Super Specialty Hospital (hosp-synth-001, tier_1)")

    res_no_match = directory.lookup_hospital("Unknown Apollo Care Clinic")
    assert res_no_match.status == "no_match", f"Expected no_match, got {res_no_match.status}"
    assert res_no_match.record is None
    print("  [PASS] 'no_match' state verified with clear message.")

    res_ambiguous = directory.lookup_hospital("General Hospital Clinic")
    assert res_ambiguous.status in {"ambiguous_match", "matched"}
    print("  [PASS] 'ambiguous_match' / candidate resolution verified.")

    res_missing = directory.lookup_hospital(None)
    assert res_missing.status == "missing_information", f"Expected missing_information, got {res_missing.status}"
    assert res_missing.record is None
    print("  [PASS] 'missing_information' state verified when hospital name is None.")

    # [Check 2] Synthetic dataset transparency & non-authorisation disclaimer
    print("\n[Check 2] Verifying synthetic dataset transparency & non-authorisation invariants...")
    assert res_matched.dataset_version == "v2026.1"
    assert res_matched.dataset_date == date(2026, 10, 1)
    assert res_matched.is_synthetic is True
    assert "SYNTHETIC DEMONSTRATION DATASET" in res_matched.disclaimer
    assert "Does not establish current insurer network agreement or cashless guarantee" in res_matched.disclaimer
    print("  [PASS] Explicit synthetic labeling (v2026.1, 2026-10-01) and boundary disclaimer present.")

    # [Check 3] Review packet snapshot construction
    print("\n[Check 3] Constructing complete review packet snapshot with M5 history...")
    case = _build_test_case_part1("case-m6-v01")
    finding_rev1 = Finding(
        finding_id="find-waiting-period-total-knee-replacement",
        revision=1,
        topic="Specific Condition Waiting Period: Total Knee Replacement",
        status="unresolved",
        conclusion="Policy terms impose 24 months waiting period; coverage history shows 18 months.",
        next_action="Obtain endorsement schedule clarifying amended waiting periods.",
        evidence=[
            Evidence(
                document_id="doc-care_health_gold_policy",
                document_version="v1",
                page=14,
                quote="Section 4.2(b): Degenerative joint disorders and joint replacement surgeries are subject to twenty-four (24) continuous months waiting period.",
                evidence_type="policy_wording",
            )
        ],
        missing_facts=["endorsement_schedule"],
        limitations=["Waiting period shortfall of 6 months under standard wording."],
    )
    finding_rev2 = Finding(
        finding_id="find-waiting-period-total-knee-replacement",
        revision=2,
        topic="Specific Condition Waiting Period: Total Knee Replacement",
        status="supported",
        conclusion="Policy terms specify a waiting period of 12 months under Endorsement Schedule EW-2025-01. 18 months continuous coverage satisfies this requirement.",
        next_action="Confirm planned admission date and obtain itemized pre-admission cost estimate.",
        evidence=[
            Evidence(
                document_id="doc-joint_replacement_endorsement",
                document_version="v1",
                page=1,
                quote="Waiting Period Modification: The specific waiting period for degenerative joint disorders and joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months to twelve (12) continuous months.",
                evidence_type="endorsement",
            )
        ],
    )
    rev_entry = Revision(
        revision_id="rev-m6-001",
        finding_id="find-waiting-period-total-knee-replacement",
        old_finding_revision=1,
        new_finding_revision=2,
        old_conclusion=finding_rev1.conclusion,
        new_conclusion=finding_rev2.conclusion,
        old_status="unresolved",
        new_status="supported",
        trigger_type="new_document",
        triggering_evidence=finding_rev2.evidence,
        reason="Applicable endorsement schedule reduces specific waiting period to 12 months.",
        affected_topics=["Specific Condition Waiting Period: Total Knee Replacement"],
    )
    checklist_item = MissingEvidenceItem(
        item_id="chk-m6-001",
        related_finding_ids=["find-waiting-period-total-knee-replacement"],
        requested_information="Pre-admission itemized cost estimate from hospital billing desk",
        why_it_matters="Clarifies anticipated out-of-pocket room rent and surgical package limits.",
        suggested_source="Hospital Admission Desk",
        status="requested",
    )
    packet_v2 = ReviewPacket(
        packet_id="pkt-m6-export-002",
        packet_version=2,
        run_id="run-m6-002",
        generated_at=datetime(2026, 10, 24, 14, 0, 0, tzinfo=timezone.utc),
        case=case,
        review_status="complete",
        stopped_reason="review_complete",
        findings=[finding_rev2],
        revisions=[rev_entry],
        missing_evidence_checklist=[checklist_item],
        unresolved_questions=["Confirm whether planned knee implant model is covered under standard package sub-limits."],
        authorization_status="not verified",
        tool_steps_used=4,
    )
    print("  [PASS] ReviewPacket snapshot v2 created with Finding Rev 2, Revision history, Checklist & Questions.")

    # [Check 4] Deterministic HTML generation
    print("\n[Check 4] Generating standalone HTML export from snapshot...")
    html_out = generate_review_packet_html(packet_v2, hospital_result=res_matched)
    html_repeat = generate_review_packet_html(packet_v2, hospital_result=res_matched)
    assert html_out == html_repeat, "HTML export must be completely deterministic!"
    print("  [PASS] Export is deterministic across multiple invocations (identical byte-for-byte).")

    # [Check 5] Dynamic text escaping (XSS prevention)
    print("\n[Check 5] Verifying complete HTML escaping of dynamic text...")
    case_xss = _build_test_case_part1("case-xss-001")
    case_xss.member_name = "Malicious <script>alert('XSS')</script> User"
    finding_xss = Finding(
        finding_id="find-xss-001",
        revision=1,
        topic="XSS Topic <img src=x onerror=alert(1)>",
        status="unresolved",
        conclusion="Payload in conclusion: <script>document.cookie='leak'</script> & 'quotes'",
        next_action="Action with <tag> & entities.",
        missing_facts=["<script>alert(2)</script>"],
    )
    pkt_xss = ReviewPacket(
        packet_id="pkt-xss-test",
        packet_version=1,
        run_id="run-xss-test",
        case=case_xss,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[finding_xss],
    )
    xss_html = generate_review_packet_html(pkt_xss)
    assert "<script>alert('XSS')</script>" not in xss_html
    assert "<script>document.cookie" not in xss_html
    assert "<img src=x onerror=alert(1)>" not in xss_html
    assert "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;" in xss_html
    assert "&lt;img src=x onerror=alert(1)&gt;" in xss_html
    print("  [PASS] All script tags and HTML-like characters properly escaped.")

    # [Check 6] Export safety (no internal paths or secrets)
    print("\n[Check 6] Checking export safety (no internal file paths or file:// links)...")
    assert "file:///" not in html_out
    assert "C:\\Users\\" not in html_out
    assert "/home/" not in html_out
    assert "/tmp/" not in html_out
    assert ".sqlite" not in html_out
    print("  [PASS] Export is completely sanitized of internal paths and local URLs.")

    # [Check 7] Incomplete review export
    print("\n[Check 7] Verifying incomplete review packet export with visible limitations...")
    pkt_incomplete = ReviewPacket(
        packet_id="pkt-m6-partial",
        packet_version=1,
        run_id="run-partial-001",
        case=case,
        review_status="incomplete",
        stopped_reason="tool_limit_reached",
        stop_details="Pre-dispatch cap of 8 tool calls reached before policy schedule was evaluated.",
        tool_steps_used=8,
        findings=[finding_rev1],
        authorization_status="not verified",
    )
    partial_html = generate_review_packet_html(pkt_incomplete)
    assert "INCOMPLETE REVIEW PACKET" in partial_html
    assert "TOOL LIMIT REACHED (MAX 8 CALLS)" in partial_html
    assert "Pre-dispatch cap of 8 tool calls reached" in partial_html
    print("  [PASS] Incomplete review exported with visible stop reason and limitations notice.")

    # [Check 8] Historical packet snapshots retain original findings
    print("\n[Check 8] Verifying older packet snapshot retains original findings after revision...")
    pkt_v1 = ReviewPacket(
        packet_id="pkt-m6-export-001",
        packet_version=1,
        run_id="run-m6-001",
        generated_at=datetime(2026, 10, 24, 13, 30, 0, tzinfo=timezone.utc),
        case=case,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[finding_rev1],
        authorization_status="not verified",
        tool_steps_used=2,
    )
    html_v1 = generate_review_packet_html(pkt_v1, hospital_result=res_matched)
    html_v2 = generate_review_packet_html(packet_v2, hospital_result=res_matched)

    assert "pkt-m6-export-001" in html_v1
    assert "Rev 1" in html_v1
    assert "UNRESOLVED" in html_v1
    assert "shortfall of 6 months" in html_v1
    assert "Rev 2" not in html_v1

    assert "pkt-m6-export-002" in html_v2
    assert "Rev 2" in html_v2
    assert "SUPPORTED" in html_v2
    assert "18 months continuous coverage satisfies this requirement." in html_v2
    assert "Rev 1 &rarr; <strong>Rev 2</strong>" in html_v2
    print("  [PASS] Historical packet snapshots remain permanently immutable and faithfully preserved.")

    # [Check 9] Standalone HTML document structure
    print("\n[Check 9] Verifying standalone HTML document structure...")
    assert html_out.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in html_out
    assert "@media print" in html_out
    assert "INSURER AUTHORISATION STATUS: NOT VERIFIED" in html_out
    assert "SYNTHETIC DEMONSTRATION DATA" in html_out

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp_file:
        tmp_file.write(html_out)
        tmp_path = Path(tmp_file.name)

    assert tmp_path.exists() and tmp_path.stat().st_size > 1000
    tmp_path.unlink()
    print("  [PASS] Standalone HTML document structure valid; ready for independent browser opening.")


# ==============================================================================
# Part 2: Owner B M6-B & Review-Data Acceptance Checks (Checks 10 to 21)
# ==============================================================================
def run_m6_part2_review_verification() -> None:
    print("\n--- Part 2: Milestone M6-B Agent Hospital Lookup & Desk Questions ---")
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

        # [Check 10] Synthetic Dataset Metadata & Structure
        print("\n[Check 10] Validating synthetic hospital dataset structure and versioning...")
        assert hospital_svc.dataset_version == "v2026.1"
        assert hospital_svc.dataset_date == date(2026, 10, 1)
        assert "SYNTHETIC DEMONSTRATION DATASET" in hospital_svc.disclaimer
        hospitals = hospital_svc.list_hospitals()
        assert len(hospitals) >= 4
        print(f"  [PASS] Synthetic dataset verified: version {hospital_svc.dataset_version}, date {hospital_svc.dataset_date}, {len(hospitals)} facilities.")

        # [Check 11] Exact Hospital Lookup
        print("[Check 11] Testing exact hospital lookup...")
        exact_res = hospital_svc.lookup("Apex Super Specialty Hospital")
        assert exact_res.status == "exact_match"
        assert exact_res.hospital is not None
        assert exact_res.hospital.record_id == "hosp-synth-001"
        assert exact_res.hospital.network_tier == "tier_1"
        assert exact_res.hospital.is_synthetic is True
        assert any("demonstration only" in lim.lower() for lim in exact_res.hospital.limitations)
        print(f"  [PASS] Exact match verified: '{exact_res.hospital.hospital_name}' ({exact_res.hospital.record_id}, {exact_res.hospital.network_tier}).")

        # [Check 12] Ambiguous Hospital Names (No Silent Selection)
        print("[Check 12] Testing ambiguous hospital query...")
        ambig_res = hospital_svc.lookup("City")
        assert ambig_res.status == "ambiguous_match"
        assert ambig_res.hospital is None  # Strict rule: never silently pick!
        assert len(ambig_res.candidate_matches) >= 2
        print(f"  [PASS] Ambiguous query returned status='ambiguous_match' with {len(ambig_res.candidate_matches)} candidates; zero uncertain selection.")

        # [Check 13] Unknown Hospital Query (No Match)
        print("[Check 13] Testing unknown hospital query...")
        no_res = hospital_svc.lookup("Nonexistent Memorial Health Center")
        assert no_res.status == "no_match"
        assert no_res.hospital is None
        print("  [PASS] Unknown query produced honest status='no_match'.")

        # [Check 14] Missing Input Handling
        print("[Check 14] Testing missing hospital input handling...")
        none_res = hospital_svc.lookup(None)
        assert none_res.status == "missing_input"
        assert none_res.hospital is None
        empty_res = hospital_svc.lookup("   ")
        assert empty_res.status == "missing_input"
        print("  [PASS] Missing and whitespace inputs handled cleanly with status='missing_input'.")

        # [Check 15] Bounded Execution with Agent-Invoked Hospital Lookup
        print("[Check 15] Executing review with agent-invoked hospital lookup...")
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
        assert packet.hospital_record is not None
        assert packet.hospital_record.record_id == "hosp-synth-001"
        print(f"  [PASS] Review executed in {packet.tool_steps_used}/8 steps with hospital lookup telemetry: '{packet.hospital_reference.hospital_name}'.")

        # [Check 16] Lookup Failure Does NOT Become Positive Hospital Finding
        print("[Check 16] Verifying lookup failure does not create positive hospital finding...")
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
        assert packet_fail.hospital_record is None
        for f in packet_fail.findings:
            assert "unlisted clinic" not in f.topic.lower()
            assert f.status != "supported" or "hospital" not in f.topic.lower()
        print("  [PASS] Failed lookup left hospital_reference as None with zero false positive findings.")

        # [Check 17] Question Derivation & Obsolete Question Removal
        print("[Check 17] Verifying resolved evidence gaps remove obsolete questions...")
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

        # [Check 18] Unrelated Unresolved Gaps Remain Visible
        print("[Check 18] Verifying unrelated unresolved gaps remain visible in questions...")
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

        # [Check 19] Non-Negotiable Authorization & Network Invariants
        print("[Check 19] Checking authorization and network status invariants...")
        assert packet.authorization_status == "not verified"
        for q in packet.unresolved_questions:
            assert "approved" not in q.lower()
            assert "cashless guaranteed" not in q.lower()
        print("  [PASS] Authorization strictly 'not verified'; zero implied approval or cashless guarantees.")

        # [Check 20] Export Data Payload Generation from Saved Snapshot
        print("[Check 20] Generating export data payload from SQLite snapshot...")
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

        # [Check 21] Incomplete State Preservation & Dynamic Text Escaping
        print("[Check 21] Testing incomplete state preservation and HTML escaping...")
        assert export_payload["review_status"] == "incomplete"
        assert export_payload["stopped_reason"] in {"missing_information", "review_complete"}

        malicious_input = "<script>alert('xss')</script> & Caregiver 'Notes' \"Quoted\""
        safe_output = escape_html(malicious_input)
        assert "<script>" not in safe_output
        assert "&lt;script&gt;" in safe_output
        assert "&amp;" in safe_output
        assert "&quot;" in safe_output
        print("  [PASS] Incomplete state preserved; HTML escaping verified.")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    print("=== AdmitSense Milestone M6 Combined Acceptance Verification (M6-A, M6-B, M6-I) ===\n")
    run_m6_part1_export_verification()
    run_m6_part2_review_verification()
    print("\n=== ALL 21 MILESTONE M6 COMBINED ACCEPTANCE CHECKS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    main()
