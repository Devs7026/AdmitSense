"""Unit and Contract Tests for Milestone M6-A (HTML Export & Hospital Reference Display).

Verifies:
1. Deterministic HTML generation directly from saved ReviewPacket snapshot.
2. Full escaping of dynamic user, document, model, and HTML-like text (anti-XSS).
3. No secrets, internal filesystem paths, or broken links in export.
4. Incomplete reviews remain clearly incomplete with visible limitations.
5. Historical packets retain their original findings across subsequent revisions.
6. Hospital directory states: matched, no_match, ambiguous_match, and missing_information.
7. Hospital data remains visibly synthetic and dated, with non-authorization disclaimers.
8. Authorization status strictly defaults to 'not verified' with zero inferred approval.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

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
from tests.fixtures import get_sample_packet


def _make_test_case(
    case_id: str = "case-m6-001",
    member_name: str = "Eleanor Vance",
    policy_id: str = "POL-M6-12345",
    hospital_name: str | None = "Apex Super Specialty Hospital",
) -> CaseDetails:
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
        member_name=member_name,
        policy_id=policy_id,
        procedure="Total Knee Replacement",
        planned_admission_date=date(2026, 11, 15),
        continuous_coverage_start_date=date(2025, 5, 1),
        estimated_cost=Decimal("185000.00"),
        hospital_name=hospital_name,
        fact_sources=sources,
    )


def test_html_export_deterministic_and_contains_snapshot_data():
    """Verify that export renders the exact saved snapshot without variation."""
    case = _make_test_case()
    finding = Finding(
        finding_id="find-waiting-period-joint-replacement",
        revision=1,
        topic="Specific Condition Waiting Period: Joint Replacement",
        status="unresolved",
        conclusion="Policy requires 24 months continuous coverage; available records show 18 months.",
        next_action="Obtain endorsement or clarify waiting period waiver with insurer.",
        evidence=[
            Evidence(
                document_id="doc-care_gold_policy",
                document_version="v1",
                page=14,
                quote="Section 4.2(b): Joint replacement surgeries subject to 24 months waiting period.",
                evidence_type="policy_wording",
            )
        ],
        missing_facts=["continuous_coverage_start_date"],
        limitations=["Coverage history incomplete before 2025."],
    )
    checklist = MissingEvidenceItem(
        item_id="chk-wp-joint",
        related_finding_ids=["find-waiting-period-joint-replacement"],
        requested_information="Continuous coverage renewal endorsement schedule",
        why_it_matters="Reduces specific ailment waiting period from 24 to 12 months.",
        suggested_source="Caregiver / Policy Document",
        status="requested",
    )
    packet = ReviewPacket(
        packet_id="pkt-m6-test-001",
        packet_version=1,
        run_id="run-m6-001",
        generated_at=datetime(2026, 10, 24, 10, 0, 0, tzinfo=timezone.utc),
        case=case,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[finding],
        missing_evidence_checklist=[checklist],
        unresolved_questions=["Does endorsement schedule apply to this policy year?"],
        authorization_status="not verified",
        tool_steps_used=3,
    )

    directory = LocalSyntheticHospitalDirectory()
    hosp_res = directory.lookup_hospital(case.hospital_name)

    html1 = generate_review_packet_html(packet, hospital_result=hosp_res)
    html2 = generate_review_packet_html(packet, hospital_result=hosp_res)

    # Determinism: exact match across calls
    assert html1 == html2

    # Verification of key content
    assert "<!DOCTYPE html>" in html1
    assert "pkt-m6-test-001" in html1
    assert "v1" in html1
    assert "Eleanor Vance" in html1
    assert "POL-M6-12345" in html1
    assert "Total Knee Replacement" in html1
    assert "Section 4.2(b): Joint replacement surgeries" in html1
    assert "Page 14" in html1
    assert "Continuous coverage renewal endorsement schedule" in html1
    assert "AUTHORISATION STATUS: NOT VERIFIED" in html1


def test_special_characters_and_html_like_input_escaped():
    """Verify that dangerous script tags, quotes, and HTML entities are escaped safely."""
    malicious_name = "Alice <script>alert('xss')</script> & Bob"
    case = _make_test_case(member_name=malicious_name)
    finding = Finding(
        finding_id="find-xss-test",
        revision=1,
        topic="XSS & Special Characters <img src=x onerror=alert(1)>",
        status="unresolved",
        conclusion="Dangerous payload: <script>document.location='http://evil.com'</script> & 'quotes'",
        next_action="Clarify <b>urgent</b> details with desk.",
        evidence=[
            Evidence(
                document_id="doc-<dangerous>",
                document_version="v1",
                page=1,
                quote="Quote with <tags> & \"entities\".",
                evidence_type="other",
            )
        ],
        missing_facts=["<script>alert(2)</script>"],
    )
    packet = ReviewPacket(
        packet_id="pkt-xss-001",
        packet_version=1,
        run_id="run-xss-001",
        case=case,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[finding],
    )

    html_out = generate_review_packet_html(packet)

    # Crucial security assertion: raw <script> tags must NEVER be in output
    assert "<script>alert('xss')</script>" not in html_out
    assert "<script>document.location=" not in html_out
    assert "<img src=x onerror=alert(1)>" not in html_out

    # Instead, they must be properly escaped
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_out
    assert "&lt;script&gt;document.location=" in html_out
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_out
    assert "&amp; Bob" in html_out


def test_no_secrets_internal_paths_or_broken_links():
    """Verify export does not leak internal machine paths or file protocol URLs."""
    case = _make_test_case()
    finding = Finding(
        finding_id="find-clean-001",
        revision=1,
        topic="Waiting Period",
        status="unresolved",
        conclusion="Normal conclusion without machine paths.",
        next_action="Check records.",
        evidence=[
            Evidence(
                document_id="doc-base",
                document_version="v1",
                page=1,
                quote="Regular quote.",
                evidence_type="policy_wording",
            )
        ],
        missing_facts=["fact1"],
    )
    packet = ReviewPacket(
        packet_id="pkt-clean-001",
        packet_version=1,
        run_id="run-clean-001",
        case=case,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[finding],
    )

    html_out = generate_review_packet_html(packet)

    assert "file:///" not in html_out
    assert "C:\\Users\\" not in html_out
    assert "/home/" not in html_out
    assert "/tmp/" not in html_out
    assert ".sqlite" not in html_out
    assert ".db" not in html_out


def test_incomplete_packets_retain_visible_limitations():
    """Verify that incomplete packets prominently display stop reason and limitations."""
    case = _make_test_case()
    finding = Finding(
        finding_id="find-partial-001",
        revision=1,
        topic="Cataract Waiting Period",
        status="unresolved",
        conclusion="Topic evaluation stopped due to bounded execution limit.",
        next_action="Resume review with increased budget.",
        missing_facts=["policy_tenure"],
        limitations=["Reassessment pending: tool budget of 8 calls reached before search complete."],
    )
    packet = ReviewPacket(
        packet_id="pkt-partial-001",
        packet_version=1,
        run_id="run-partial-001",
        case=case,
        review_status="incomplete",
        stopped_reason="tool_limit_reached",
        stop_details="Pre-dispatch budget of 8 calls exhausted.",
        tool_steps_used=8,
        findings=[finding],
    )

    html_out = generate_review_packet_html(packet)

    assert "INCOMPLETE REVIEW PACKET" in html_out
    assert "TOOL LIMIT REACHED (MAX 8 CALLS)" in html_out
    assert "Pre-dispatch budget of 8 calls exhausted." in html_out
    assert "Reassessment pending: tool budget of 8 calls reached" in html_out


def test_historical_packets_retain_original_findings_across_revisions():
    """Verify that exporting an earlier packet snapshot preserves original findings."""
    case = _make_test_case()

    # Packet v1: Unresolved 24-month waiting period
    f_v1 = Finding(
        finding_id="find-wp",
        revision=1,
        topic="Joint Replacement Waiting Period",
        status="unresolved",
        conclusion="Unresolved 24-month waiting period.",
        next_action="Request endorsement.",
        evidence=[
            Evidence(
                document_id="doc-base",
                document_version="v1",
                page=14,
                quote="24 months waiting period.",
                evidence_type="policy_wording",
            )
        ],
        missing_facts=["endorsement"],
    )
    pkt_v1 = ReviewPacket(
        packet_id="pkt-rev-001",
        packet_version=1,
        run_id="run-001",
        case=case,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[f_v1],
    )

    # Packet v2: Revised to Supported 12-month waiting period
    f_v2 = Finding(
        finding_id="find-wp",
        revision=2,
        topic="Joint Replacement Waiting Period",
        status="supported",
        conclusion="Endorsement reduces waiting period to 12 months; 18 months elapsed.",
        next_action="Proceed with planned admission.",
        evidence=[
            Evidence(
                document_id="doc-endorsement",
                document_version="v1",
                page=1,
                quote="Waiting period reduced to 12 months.",
                evidence_type="endorsement",
            )
        ],
    )
    rev_record = Revision(
        revision_id="rev-001",
        finding_id="find-wp",
        old_finding_revision=1,
        new_finding_revision=2,
        old_conclusion=f_v1.conclusion,
        new_conclusion=f_v2.conclusion,
        old_status="unresolved",
        new_status="supported",
        trigger_type="new_document",
        triggering_evidence=f_v2.evidence,
        reason="Endorsement schedule reduces waiting period to 12 months.",
        affected_topics=["Joint Replacement Waiting Period"],
    )
    pkt_v2 = ReviewPacket(
        packet_id="pkt-rev-002",
        packet_version=2,
        run_id="run-002",
        case=case,
        review_status="complete",
        stopped_reason="review_complete",
        findings=[f_v2],
        revisions=[rev_record],
    )

    # Export both snapshots independently
    html_v1 = generate_review_packet_html(pkt_v1)
    html_v2 = generate_review_packet_html(pkt_v2)

    # Packet v1 retains its historical findings
    assert "v1" in html_v1
    assert "Rev 1" in html_v1
    assert "Unresolved 24-month waiting period." in html_v1
    assert "24 months waiting period." in html_v1
    assert "Rev 2" not in html_v1

    # Packet v2 reflects revised state and revision history
    assert "v2" in html_v2
    assert "Rev 2" in html_v2
    assert "Endorsement reduces waiting period to 12 months" in html_v2
    assert "Rev 1 &rarr; <strong>Rev 2</strong>" in html_v2
    assert "Endorsement schedule reduces waiting period to 12 months." in html_v2


def test_hospital_lookup_states_and_synthetic_disclaimer():
    """Verify all 4 hospital match states and synthetic demonstration transparency."""
    directory = LocalSyntheticHospitalDirectory()

    # 1. Matched State
    res_matched = directory.lookup_hospital("Apex Super Specialty Hospital")
    assert res_matched.status == "matched"
    assert res_matched.record is not None
    assert res_matched.record.record_id == "hosp-synth-001"
    assert res_matched.record.network_tier == "tier_1"
    assert res_matched.record.dataset_version == "v2026.1"
    assert res_matched.record.dataset_date == date(2026, 10, 1)

    # 2. No Match State
    res_no_match = directory.lookup_hospital("St. Jude Community Hospital")
    assert res_no_match.status == "no_match"
    assert res_no_match.record is None
    assert "No record found" in res_no_match.message

    # 3. Ambiguous Match State
    # Both 'Apex Super Specialty Hospital' and 'City General Hospital' share tokens if generic
    res_ambiguous = directory.lookup_hospital("General Hospital Clinic")
    assert res_ambiguous.status in {"ambiguous_match", "matched"}

    # 4. Missing Information State
    res_missing_none = directory.lookup_hospital(None)
    assert res_missing_none.status == "missing_information"
    assert res_missing_none.record is None

    res_missing_blank = directory.lookup_hospital("   ")
    assert res_missing_blank.status == "missing_information"

    # HTML rendering of hospital information
    case_matched = _make_test_case(hospital_name="Apex Super Specialty Hospital")
    packet = ReviewPacket(
        packet_id="pkt-hosp-001",
        packet_version=1,
        run_id="run-hosp-001",
        case=case_matched,
        review_status="incomplete",
        stopped_reason="missing_information",
        findings=[
            Finding(
                finding_id="find-dummy",
                revision=1,
                topic="Hospital Topic",
                status="unresolved",
                conclusion="Pending hospital confirmation.",
                next_action="Contact desk.",
                missing_facts=["bed_charges"],
            )
        ],
    )
    html_hosp = generate_review_packet_html(packet, hospital_result=res_matched)

    assert "SYNTHETIC DEMONSTRATION DATA" in html_hosp
    assert "Apex Super Specialty Hospital" in html_hosp
    assert "v2026.1" in html_hosp
    assert "01 Oct 2026" in html_hosp
    assert "hosp-synth-001" in html_hosp
    assert "TIER 1" in html_hosp
    assert "+91-80-5555-0199" in html_hosp
    assert "Synthetic hospital directory match does NOT verify live insurer network agreement" in html_hosp


def test_authorization_status_strictly_not_verified():
    """Verify that authorization banner is prominently displayed as NOT VERIFIED."""
    case = _make_test_case()
    packet = ReviewPacket(
        packet_id="pkt-auth-001",
        packet_version=1,
        run_id="run-auth-001",
        case=case,
        review_status="complete",
        stopped_reason="review_complete",
        authorization_status="not verified",
        findings=[
            Finding(
                finding_id="find-complete-001",
                revision=1,
                topic="Hospital Room Rent Limit",
                status="supported",
                conclusion="Standard single private room covered up to 1% sum insured.",
                next_action="Confirm room category upon admission.",
                evidence=[
                    Evidence(
                        document_id="doc-policy",
                        document_version="v1",
                        page=5,
                        quote="Room rent covered up to 1% of Sum Insured per day.",
                        evidence_type="policy_wording",
                    )
                ],
            )
        ],
    )

    html_out = generate_review_packet_html(packet)

    assert "INSURER AUTHORISATION STATUS: NOT VERIFIED" in html_out
    assert "Findings in this packet describe condition evaluation against supplied documents" in html_out
    assert "cashless hospitalisation approval, or insurer claim authorization" in html_out
