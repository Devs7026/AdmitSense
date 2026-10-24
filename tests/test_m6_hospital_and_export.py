"""Milestone M6-B & M6-I Review-Data Test Suite.

Tests:
1. Exact hospital match.
2. No match.
3. Ambiguous hospital names (does not silently select an uncertain match).
4. Missing or invalid record metadata handling.
5. Synthetic & source-date labels preserved in returned hospital data.
6. Resolved evidence gaps no longer produce obsolete questions.
7. Remaining unresolved gaps stay visible.
8. No unsupported network, cashless, or insurer approval claims.
9. Bounded execution when lookup is agent-invoked (consumes budget, <= 8 cap, timeout).
10. Lookup failure does not become a positive hospital finding.
11. Export-ready data snapshot generation without live model execution.
12. Export payload preserves incomplete and pending-reassessment states with HTML escaping.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import pytest

from admitsense.agent.hospital import HospitalLookupService
from admitsense.agent.questions import derive_desk_and_insurer_questions
from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import BoundedReviewAgent, ToolActivityEvent
from admitsense.documents.models import DocumentRecord, ExtractedPage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_hospital_estimate_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
)
from admitsense.review.export_data import build_review_export_payload, escape_html
from admitsense.schemas import (
    CaseDetails,
    DocumentApplicability,
    Evidence,
    FactSource,
    Finding,
    HospitalLookupResult,
    HospitalRecordReference,
    MissingEvidenceItem,
    ReviewPacket,
    Revision,
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database
from admitsense.documents.storage import DocumentStorage
from admitsense.storage.review_repository import ReviewRepository


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_m6.db"
    db = Database(db_path=db_path)
    return db


@pytest.fixture
def m6_env(test_db, tmp_path):
    case_repo = CaseRepository(db=test_db)
    doc_storage = DocumentStorage(db=test_db, storage_dir=tmp_path / "docs")
    review_repo = ReviewRepository(db=test_db)
    retrieval = EvidenceRetrievalService(db=test_db)
    hospital_svc = HospitalLookupService()

    return {
        "db": test_db,
        "case_repo": case_repo,
        "doc_storage": doc_storage,
        "review_repo": review_repo,
        "retrieval": retrieval,
        "hospital_svc": hospital_svc,
    }


# ==============================================================================
# 1. Hospital Lookup Tests (Milestone M6-B)
# ==============================================================================

def test_hospital_lookup_exact_match(m6_env):
    """Verify exact hospital match returns stable record ID, metadata, and synthetic disclaimer."""
    svc: HospitalLookupService = m6_env["hospital_svc"]
    result = svc.lookup("Apex Super Specialty Hospital")

    assert result.status == "exact_match"
    assert result.hospital is not None
    assert result.hospital.record_id == "hosp-synth-001"
    assert result.hospital.hospital_name == "Apex Super Specialty Hospital"
    assert result.hospital.city == "Bengaluru"
    assert result.hospital.network_tier == "tier_1"
    assert result.hospital.tpa_desk_contact == "+91-80-5555-0199 (Ext 402)"
    assert result.hospital.dataset_version == "v2026.1"
    assert result.hospital.dataset_date == date(2026, 10, 1)
    assert result.hospital.is_synthetic is True
    assert any("demonstration only" in lim.lower() for lim in result.hospital.limitations)
    assert any("does not establish" in lim.lower() for lim in result.hospital.limitations)


def test_hospital_lookup_no_match(m6_env):
    """Verify unknown hospital query produces an explicit 'no_match' result."""
    svc: HospitalLookupService = m6_env["hospital_svc"]
    result = svc.lookup("St. Jude Community Health Clinic")

    assert result.status == "no_match"
    assert result.hospital is None
    assert len(result.candidate_matches) == 0
    assert "no matching hospital record found" in result.explanation.lower()
    assert result.is_synthetic is True


def test_hospital_lookup_missing_input(m6_env):
    """Verify None or empty hospital input produces 'missing_input' status without crashing."""
    svc: HospitalLookupService = m6_env["hospital_svc"]

    res_none = svc.lookup(None)
    assert res_none.status == "missing_input"
    assert res_none.hospital is None
    assert "not provided" in res_none.explanation.lower()

    res_empty = svc.lookup("   ")
    assert res_empty.status == "missing_input"
    assert res_empty.hospital is None


def test_hospital_lookup_ambiguous_names(m6_env):
    """Verify ambiguous query matching multiple facilities returns 'ambiguous_match'

    and does NOT silently pick an uncertain match.
    """
    svc: HospitalLookupService = m6_env["hospital_svc"]
    # "City" matches both "City General Hospital" and "City Care Specialty Hospital"
    result = svc.lookup("City")

    assert result.status == "ambiguous_match"
    assert result.hospital is None  # MUST NOT silently select one!
    assert len(result.candidate_matches) >= 2
    match_names = [m.hospital_name for m in result.candidate_matches]
    assert "City General Hospital" in match_names
    assert "City Care Specialty Hospital" in match_names
    assert "disambiguation required" in result.explanation.lower()


def test_hospital_lookup_invalid_metadata_handling():
    """Verify corrupted or missing dataset metadata raises an explicit validation error."""
    corrupted_data_no_ver = {
        "dataset_date": "2026-10-01",
        "hospitals": [],
    }
    with pytest.raises(ValueError, match="missing required 'dataset_version'"):
        HospitalLookupService(dataset_dict=corrupted_data_no_ver)

    corrupted_data_invalid_date = {
        "dataset_version": "v2026.1",
        "dataset_date": "not-a-date",
        "hospitals": [],
    }
    with pytest.raises(ValueError, match="Invalid 'dataset_date'"):
        HospitalLookupService(dataset_dict=corrupted_data_invalid_date)

    corrupted_data_missing_id = {
        "dataset_version": "v2026.1",
        "dataset_date": "2026-10-01",
        "hospitals": [{"hospital_name": "Test Hospital", "city": "Bengaluru"}],
    }
    with pytest.raises(ValueError, match="missing required 'record_id'"):
        HospitalLookupService(dataset_dict=corrupted_data_missing_id)


def test_hospital_source_separated_from_pdf_citations(m6_env):
    """Verify hospital directory reference is represented separately from PDF page citations."""
    svc: HospitalLookupService = m6_env["hospital_svc"]
    h_res = svc.lookup("Apex Super Specialty Hospital")
    assert h_res.hospital is not None

    # Hospital reference is a HospitalRecordReference, not an Evidence object
    assert not isinstance(h_res.hospital, Evidence)
    assert hasattr(h_res.hospital, "record_id")
    assert hasattr(h_res.hospital, "dataset_version")
    assert not hasattr(h_res.hospital, "page")  # No PDF physical page on directory record


# ==============================================================================
# 2. Review Integration & Bounded Execution Tests
# ==============================================================================

def test_agent_invoked_hospital_lookup_bounded_execution(m6_env):
    """Verify agent invokes 'lookup_hospital' within the bounded 8-call budget and captures telemetry."""
    case_repo = m6_env["case_repo"]
    doc_storage = m6_env["doc_storage"]
    retrieval = m6_env["retrieval"]

    case = CaseDetails(
        case_id="case-m6-hosp-001",
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

    # Ingest Policy Wording and Schedule
    doc_storage.save_document(
        case_id=case.case_id,
        filename="Care_Health_Gold_Policy_Wording.pdf",
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
    # lookup_hospital tool activity captured
    hosp_events = [e for e in events if e.tool_name == "lookup_hospital"]
    assert len(hosp_events) >= 1
    assert any(e.status == "completed" for e in hosp_events)

    # Hospital reference attached to packet
    assert packet.hospital_reference is not None
    assert packet.hospital_reference.record_id == "hosp-synth-001"
    assert packet.hospital_reference.hospital_name == "Apex Super Specialty Hospital"
    assert packet.hospital_reference.is_synthetic is True

    # Invariants strictly preserved
    assert packet.authorization_status == "not verified"


def test_hospital_lookup_failure_does_not_become_positive_finding(m6_env):
    """Verify that when a hospital is not found, packet.hospital_reference is None

    and NO fabricated positive hospital finding is created.
    """
    case_repo = m6_env["case_repo"]
    doc_storage = m6_env["doc_storage"]
    retrieval = m6_env["retrieval"]

    case = CaseDetails(
        case_id="case-m6-hosp-fail-002",
        member_name="Ramesh Sharma",
        policy_id="POL-998877",
        procedure="Total Knee Replacement",
        planned_admission_date=date(2026, 11, 20),
        hospital_name="Unregistered Rural Nursing Home",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "planned_admission_date": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
        },
    )
    case_repo.create_case(case)

    agent = BoundedReviewAgent(default_tool_budget=8)
    packet = agent.run_review(case=case, retrieval=retrieval)

    # Hospital reference is None
    assert packet.hospital_reference is None
    # No finding claimed that the hospital was verified or approved
    for f in packet.findings:
        assert "rural nursing home" not in f.topic.lower()
        assert f.status != "supported" or "hospital" not in f.topic.lower()

    # Helpful question generated to verify network empanelment
    assert any("verify with the insurer helpline" in q.lower() for q in packet.unresolved_questions)


# ==============================================================================
# 3. Actionable Desk & Insurer Questions Tests
# ==============================================================================

def test_resolved_evidence_gaps_remove_obsolete_questions():
    """Verify that when an evidence gap resolves (e.g.

    endorsement reduces waiting period to 12 months, supported),
    the obsolete question asking for continuity proof is removed.
    """
    case = CaseDetails(
        case_id="case-m6-q-001",
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

    # Scenario 1: Unresolved finding (shortfall exists)
    unresolved_f = Finding(
        finding_id="find-waiting-period-knee",
        revision=1,
        topic="Specific Waiting Period: Total Knee Replacement",
        status="unresolved",
        conclusion="Policy terms impose a 24-month waiting period. Supplied history shows 18 months, leaving a 6-month shortfall.",
        relevant_case_facts=["procedure", "continuous_coverage_start_date"],
        missing_facts=["continuous_coverage_start_date"],
        limitations=["Coverage shortfall of 6 continuous months."],
        next_action="Obtain prior insurance continuity certificate.",
    )
    questions_unresolved = derive_desk_and_insurer_questions(
        case=case,
        findings=[unresolved_f],
    )
    assert any("continuity certificates or portability credits" in q for q in questions_unresolved)

    # Scenario 2: Finding becomes supported (endorsement applied, 12 months satisfied)
    supported_f = Finding(
        finding_id="find-waiting-period-knee",
        revision=2,
        topic="Specific Waiting Period: Total Knee Replacement",
        status="supported",
        conclusion="Policy terms specify a 12-month waiting period under Endorsement Schedule EW-2025-01. Supplied history satisfies this.",
        relevant_case_facts=["procedure", "continuous_coverage_start_date"],
        evidence=[
            Evidence(
                document_id="doc-endorse-001",
                document_version="v1",
                page=1,
                quote="Waiting period reduced from 24 to 12 continuous months.",
                evidence_type="endorsement",
            )
        ],
        next_action="Proceed with admission paperwork.",
    )
    questions_supported = derive_desk_and_insurer_questions(
        case=case,
        findings=[supported_f],
    )
    # The obsolete continuity question MUST be gone!
    assert not any("continuity certificates or portability credits" in q for q in questions_supported)


def test_remaining_unresolved_gaps_stay_visible():
    """Verify that when one topic resolves, unrelated unresolved findings remain in questions."""
    case = CaseDetails(
        case_id="case-m6-q-002",
        member_name="Ramesh Sharma",
        policy_id="POL-998877",
        procedure="Total Knee Replacement",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
        },
    )

    # Finding 1: Supported waiting period
    f_knee = Finding(
        finding_id="find-knee",
        revision=2,
        topic="Specific Waiting Period: Total Knee Replacement",
        status="supported",
        conclusion="12-month requirement satisfied.",
        relevant_case_facts=["procedure"],
        evidence=[
            Evidence(
                document_id="doc-endorse-001",
                document_version="v1",
                page=1,
                quote="Waiting period reduced from 24 to 12 continuous months.",
                evidence_type="endorsement",
            )
        ],
        next_action="None",
    )
    # Finding 2: Unresolved room rent limit
    f_room = Finding(
        finding_id="find-room-rent",
        revision=1,
        topic="Inpatient Room Rent Sub-Limit",
        status="unresolved",
        conclusion="Room rent capped at 1% of sum insured. Chosen category unknown.",
        relevant_case_facts=["procedure"],
        missing_facts=["room_category"],
        limitations=["Room rent category not specified."],
        next_action="Verify room category with hospital.",
    )

    questions = derive_desk_and_insurer_questions(case=case, findings=[f_knee, f_room])

    # Room rent question must be present
    assert any("room category complies with the policy's room rent limit" in q for q in questions)
    # Missing admission date question must be present
    assert any("scheduled hospital admission date" in q for q in questions)


def test_no_unsupported_network_cashless_or_approval_claims():
    """Verify that questions and hospital records NEVER claim live network status,

    cashless eligibility, or insurer approval.
    """
    case = CaseDetails(
        case_id="case-m6-q-003",
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

    hosp_ref = HospitalRecordReference(
        record_id="hosp-synth-001",
        dataset_version="v2026.1",
        dataset_date=date(2026, 10, 1),
        hospital_name="Apex Super Specialty Hospital",
        city="Bengaluru",
        network_tier="tier_1",
        tpa_desk_contact="+91-80-5555-0199",
        is_synthetic=True,
    )

    finding = Finding(
        finding_id="find-knee",
        revision=1,
        topic="Specific Waiting Period: Total Knee Replacement",
        status="unresolved",
        conclusion="Waiting period shortfall.",
        relevant_case_facts=["procedure"],
        missing_facts=["continuous_coverage_start_date"],
        limitations=["Shortfall remains."],
        next_action="Clarify with insurer.",
    )

    questions = derive_desk_and_insurer_questions(
        case=case,
        findings=[finding],
        hospital_reference=hosp_ref,
    )

    for q in questions:
        q_lower = q.lower()
        # Must never state claim is approved or guaranteed cashless
        assert "claim approved" not in q_lower
        assert "cashless guaranteed" not in q_lower
        assert "insurance confirmed" not in q_lower


# ==============================================================================
# 4. Export-Ready Data Tests (Milestone M6-I review-data side)
# ==============================================================================

def test_export_data_payload_deterministic_from_saved_snapshot(m6_env):
    """Verify export payload is generated directly from saved snapshot without model invocation."""
    case_repo = m6_env["case_repo"]
    review_repo = m6_env["review_repo"]

    case = CaseDetails(
        case_id="case-m6-export-001",
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

    hosp_ref = HospitalRecordReference(
        record_id="hosp-synth-001",
        dataset_version="v2026.1",
        dataset_date=date(2026, 10, 1),
        hospital_name="Apex Super Specialty Hospital",
        city="Bengaluru",
        network_tier="tier_1",
        tpa_desk_contact="+91-80-5555-0199",
        is_synthetic=True,
    )

    finding = Finding(
        finding_id="find-knee",
        revision=2,
        topic="Specific Waiting Period: Total Knee Replacement",
        status="supported",
        conclusion="12-month waiting period satisfied by Endorsement Schedule EW-2025-01.",
        relevant_case_facts=["procedure"],
        evidence=[
            Evidence(
                document_id="doc-endorse-001",
                document_version="v1",
                page=1,
                quote="Waiting period reduced from 24 to 12 continuous months.",
                evidence_type="endorsement",
            )
        ],
        next_action="Proceed to admission planning.",
    )

    revision = Revision(
        revision_id="rev-knee-001",
        finding_id="find-knee",
        old_finding_revision=1,
        new_finding_revision=2,
        old_conclusion="24-month waiting period with 6-month shortfall.",
        new_conclusion="12-month waiting period satisfied.",
        old_status="unresolved",
        new_status="supported",
        trigger_type="new_document",
        triggering_evidence=[
            Evidence(
                document_id="doc-endorse-001",
                document_version="v1",
                page=1,
                quote="Waiting period reduced from 24 to 12 continuous months.",
                evidence_type="endorsement",
            )
        ],
        reason="Applicable endorsement schedule reduces waiting period to 12 months.",
        affected_topics=["Specific Waiting Period: Total Knee Replacement"],
        created_at=datetime.now(timezone.utc),
    )

    packet = ReviewPacket(
        packet_id="pkt-m6-exp-001",
        packet_version=2,
        run_id="run-m6-exp-001",
        generated_at=datetime.now(timezone.utc),
        case=case,
        review_status="complete",
        findings=[finding],
        revisions=[revision],
        missing_evidence_checklist=[],
        unresolved_questions=["Contact hospital TPA desk to confirm pre-auth submission cutoff."],
        hospital_reference=hosp_ref,
        authorization_status="not verified",
        authorization_evidence=[],
        tool_steps_used=4,
        stopped_reason="review_complete",
    )

    # Persist in SQLite
    saved_packet = review_repo.save_review_packet(packet)
    assert saved_packet is not None

    # Retrieve from DB and generate export payload
    retrieved_packet = review_repo.get_latest_review_packet(case.case_id)
    assert retrieved_packet is not None

    payload = build_review_export_payload(retrieved_packet)

    assert payload["packet_id"] == "pkt-m6-exp-001"
    assert payload["packet_version"] == 2
    assert payload["review_status"] == "complete"
    assert payload["stopped_reason"] == "review_complete"
    assert payload["authorization_status"] == "not verified"

    # Case details
    assert payload["case"]["member_name"] == "Ramesh Sharma"
    assert payload["case"]["policy_id"] == "POL-998877"

    # Hospital reference with synthetic markers
    assert payload["hospital_reference"] is not None
    assert payload["hospital_reference"]["record_id"] == "hosp-synth-001"
    assert payload["hospital_reference"]["is_synthetic"] is True
    assert "Synthetic hospital data for demonstration only." in payload["hospital_reference"]["limitations"]

    # Findings and revisions
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["revision"] == 2
    assert payload["findings"][0]["citations"][0]["page"] == 1
    assert len(payload["revisions"]) == 1
    assert payload["revisions"][0]["old_finding_revision"] == 1
    assert payload["revisions"][0]["new_finding_revision"] == 2

    # Mandatory disclaimer present
    assert "DISCLAIMER" in payload["disclaimer"]
    assert "does NOT approve, pre-authorize, or guarantee" in payload["disclaimer"]


def test_export_data_preserves_incomplete_and_pending_reassessment():
    """Verify export payload honestly preserves incomplete and pending-reassessment states."""
    case = CaseDetails(
        case_id="case-m6-inc-001",
        member_name="Sunita Verma",
        fact_sources={"member_name": FactSource(source_type="user_provided")},
    )

    incomplete_finding = Finding(
        finding_id="find-proc",
        revision=1,
        topic="Procedure Waiting Period",
        status="unresolved",
        conclusion="Procedure unspecified. Waiting period cannot be established.",
        relevant_case_facts=[],
        limitations=["Reassessment pending: review run stopped before this topic could be re-evaluated."],
        next_action="Obtain planned procedure from attending doctor.",
    )

    packet = ReviewPacket(
        packet_id="pkt-m6-inc-001",
        packet_version=1,
        run_id="run-m6-inc-001",
        case=case,
        review_status="incomplete",
        findings=[incomplete_finding],
        revisions=[],
        missing_evidence_checklist=[
            MissingEvidenceItem(
                item_id="chk-proc",
                related_finding_ids=["find-proc"],
                requested_information="Planned surgical procedure",
                why_it_matters="Identifies applicable waiting period clause",
                status="requested",
            )
        ],
        unresolved_questions=["Confirm scheduled admission date with doctor."],
        hospital_reference=None,
        authorization_status="not verified",
        tool_steps_used=2,
        stopped_reason="missing_information",
    )

    payload = build_review_export_payload(packet)

    assert payload["review_status"] == "incomplete"
    assert payload["stopped_reason"] == "missing_information"
    assert payload["findings"][0]["limitations"][0].startswith("Reassessment pending")
    assert len(payload["missing_evidence_checklist"]) == 1
    assert payload["hospital_reference"] is None


def test_html_escape_utility():
    """Verify HTML escaping prevents injection attacks in dynamic export fields."""
    malicious = "<script>alert('pwned')</script> & 'quoted' \"test\""
    escaped = escape_html(malicious)

    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert "&amp;" in escaped
    assert "&quot;" in escaped
    assert "&#x27;" in escaped
