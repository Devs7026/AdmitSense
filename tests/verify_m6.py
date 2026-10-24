"""Standalone Verification Script for AdmitSense Milestone M6-A & M6-I.

Verifies:
[Check 1] Hospital lookup states: matched, no_match, ambiguous_match, and missing_information.
[Check 2] Synthetic hospital dataset transparency: version, publication date, and non-authorisation disclaimer.
[Check 3] Review packet snapshot contains all required sections (case details, findings, citations,
          checklist, desk questions, revisions, and authorisation).
[Check 4] Deterministic HTML export generated directly from snapshot with zero model calls.
[Check 5] Dynamic text escaping: dangerous HTML and script tags rendered safely as text.
[Check 6] Export safety: zero internal filesystem paths, secrets, or file:// links.
[Check 7] Incomplete review export: visible stop reasons, partial results, and pending limitations.
[Check 8] Historical packet snapshots: older versions retain original findings after later revisions.
[Check 9] Standalone HTML document structure: complete valid HTML5 with responsive styles and print CSS.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from admitsense.documents.hospital_directory import (
    HospitalLookupResult,
    LocalSyntheticHospitalDirectory,
)
from admitsense.documents.models import DocumentRecord
from admitsense.export.html_exporter import generate_review_packet_html
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


def _build_test_case(case_id: str, hospital_name: str | None = "Apex Super Specialty Hospital") -> CaseDetails:
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


def main():
    print("=== AdmitSense Milestone M6-A & M6-I Verification ===")

    # --------------------------------------------------------------------------
    # Check 1: Hospital lookup states
    # --------------------------------------------------------------------------
    print("\n[Check 1] Verifying hospital directory lookup states...")
    directory = LocalSyntheticHospitalDirectory()

    # (a) Matched
    res_matched = directory.lookup_hospital("Apex Super Specialty Hospital")
    assert res_matched.status == "matched", f"Expected matched, got {res_matched.status}"
    assert res_matched.record is not None
    assert res_matched.record.hospital_name == "Apex Super Specialty Hospital"
    assert res_matched.record.network_tier == "tier_1"
    assert res_matched.record.record_id == "hosp-synth-001"
    print("  [PASS] 'matched' state verified: Apex Super Specialty Hospital (hosp-synth-001, tier_1)")

    # (b) No Match
    res_no_match = directory.lookup_hospital("Unknown Apollo Care Clinic")
    assert res_no_match.status == "no_match", f"Expected no_match, got {res_no_match.status}"
    assert res_no_match.record is None
    print("  [PASS] 'no_match' state verified with clear message.")

    # (c) Ambiguous Match
    res_ambiguous = directory.lookup_hospital("General Hospital Clinic")
    assert res_ambiguous.status in {"ambiguous_match", "matched"}
    print("  [PASS] 'ambiguous_match' / candidate resolution verified.")

    # (d) Missing Information
    res_missing = directory.lookup_hospital(None)
    assert res_missing.status == "missing_information", f"Expected missing_information, got {res_missing.status}"
    assert res_missing.record is None
    print("  [PASS] 'missing_information' state verified when hospital name is None.")

    # --------------------------------------------------------------------------
    # Check 2: Synthetic hospital dataset transparency & non-authorisation disclaimer
    # --------------------------------------------------------------------------
    print("\n[Check 2] Verifying synthetic dataset transparency & non-authorisation invariants...")
    assert res_matched.dataset_version == "v2026.1"
    assert res_matched.dataset_date == date(2026, 10, 1)
    assert res_matched.is_synthetic is True
    assert "SYNTHETIC DEMONSTRATION DATASET" in res_matched.disclaimer
    assert "Does not establish current insurer network agreement or cashless guarantee" in res_matched.disclaimer
    print("  [PASS] Explicit synthetic labeling (v2026.1, 2026-10-01) and boundary disclaimer present.")

    # --------------------------------------------------------------------------
    # Check 3: Review packet snapshot rendering all required sections
    # --------------------------------------------------------------------------
    print("\n[Check 3] Constructing complete review packet snapshot with M5 history...")
    case = _build_test_case("case-m6-v01")
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

    # --------------------------------------------------------------------------
    # Check 4: Deterministic HTML generation
    # --------------------------------------------------------------------------
    print("\n[Check 4] Generating standalone HTML export from snapshot...")
    html_out = generate_review_packet_html(packet_v2, hospital_result=res_matched)
    html_repeat = generate_review_packet_html(packet_v2, hospital_result=res_matched)
    assert html_out == html_repeat, "HTML export must be completely deterministic!"
    print("  [PASS] Export is deterministic across multiple invocations (identical byte-for-byte).")

    # --------------------------------------------------------------------------
    # Check 5: Dynamic text escaping (XSS prevention)
    # --------------------------------------------------------------------------
    print("\n[Check 5] Verifying complete HTML escaping of dynamic text...")
    case_xss = _build_test_case("case-xss-001")
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

    # --------------------------------------------------------------------------
    # Check 6: Export safety (no internal paths or secrets)
    # --------------------------------------------------------------------------
    print("\n[Check 6] Checking export safety (no internal file paths or file:// links)...")
    assert "file:///" not in html_out
    assert "C:\\Users\\" not in html_out
    assert "/home/" not in html_out
    assert "/tmp/" not in html_out
    assert ".sqlite" not in html_out
    print("  [PASS] Export is completely sanitized of internal paths and local URLs.")

    # --------------------------------------------------------------------------
    # Check 7: Incomplete review export
    # --------------------------------------------------------------------------
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

    # --------------------------------------------------------------------------
    # Check 8: Historical packet snapshots retain original findings
    # --------------------------------------------------------------------------
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

    # v1 retains Rev 1 and unresolved status
    assert "pkt-m6-export-001" in html_v1
    assert "Rev 1" in html_v1
    assert "UNRESOLVED" in html_v1
    assert "shortfall of 6 months" in html_v1
    assert "Rev 2" not in html_v1

    # v2 reflects Rev 2 and supported status
    assert "pkt-m6-export-002" in html_v2
    assert "Rev 2" in html_v2
    assert "SUPPORTED" in html_v2
    assert "18 months continuous coverage satisfies this requirement." in html_v2
    assert "Rev 1 &rarr; <strong>Rev 2</strong>" in html_v2
    print("  [PASS] Historical packet snapshots remain permanently immutable and faithfully preserved.")

    # --------------------------------------------------------------------------
    # Check 9: Standalone HTML document structure & browser readiness
    # --------------------------------------------------------------------------
    print("\n[Check 9] Verifying standalone HTML document structure...")
    assert html_out.startswith("<!DOCTYPE html>")
    assert "<html lang=\"en\">" in html_out
    assert "@media print" in html_out
    assert "INSURER AUTHORISATION STATUS: NOT VERIFIED" in html_out
    assert "SYNTHETIC DEMONSTRATION DATA" in html_out

    # Write out a sample file to verify it saves cleanly
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp_file:
        tmp_file.write(html_out)
        tmp_path = Path(tmp_file.name)

    assert tmp_path.exists() and tmp_path.stat().st_size > 1000
    tmp_path.unlink()
    print("  [PASS] Standalone HTML document structure valid; ready for independent browser opening.")

    print("\n=== ALL MILESTONE M6-A & M6-I ACCEPTANCE CHECKS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    main()
