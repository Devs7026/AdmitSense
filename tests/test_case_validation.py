"""Tests for Milestone M1-B: Case model validation, provenance rules, and sample review outputs."""

from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from admitsense.schemas import (
    CaseDetails,
    Evidence,
    FactSource,
    Finding,
    ReviewPacket,
)
from tests.fixtures import (
    ALL_SAMPLE_PACKETS,
    SAMPLE_CONFLICT_PACKET,
    SAMPLE_INCOMPLETE_REVIEW_PACKET,
    SAMPLE_REVISED_FINDING_PACKET,
    SAMPLE_SUPPORTED_FINDING_PACKET,
    get_sample_packet,
    list_sample_packet_names,
    load_sample_packet_from_json,
)


class TestCaseModelValidation:
    """Verifies that CaseDetails supports partial/missing data and strict provenance tracking."""

    def test_minimal_case_creation_with_only_case_id(self):
        """Verify that a case can be initialized with ONLY case_id, leaving all facts None."""
        case = CaseDetails(case_id="case-minimal-001")
        assert case.case_id == "case-minimal-001"
        assert case.member_name is None
        assert case.policy_id is None
        assert case.policy_start_date is None
        assert case.continuous_coverage_start_date is None
        assert case.planned_admission_date is None
        assert case.policy_age_months is None
        assert case.procedure is None
        assert case.hospital_name is None
        assert case.estimated_cost is None
        assert case.currency == "INR"
        assert case.fact_sources == {}

    def test_missing_policy_id_dates_procedure_hospital_does_not_block_case(self):
        """Verify case creation with partial facts (e.g., only member_name provided)."""
        case = CaseDetails(
            case_id="case-partial-002",
            member_name="Aarav Sharma",
            fact_sources={
                "member_name": FactSource(source_type="user_provided"),
            },
        )
        assert case.member_name == "Aarav Sharma"
        assert case.policy_id is None
        assert case.policy_start_date is None
        assert case.continuous_coverage_start_date is None
        assert case.planned_admission_date is None
        assert case.procedure is None
        assert case.hospital_name is None

    def test_user_provided_fact_provenance(self):
        """Verify user_provided fact provenance requires no extra evidence."""
        source = FactSource(source_type="user_provided")
        assert source.source_type == "user_provided"
        assert source.evidence == []
        assert source.explanation is None

    def test_document_derived_fact_provenance_requires_evidence(self):
        """Verify document fact provenance strictly requires Evidence."""
        # Valid with evidence
        valid_source = FactSource(
            source_type="document",
            evidence=[
                Evidence(
                    document_id="doc-pol-01",
                    document_version="v1",
                    page=1,
                    quote="Policy Commencement Date: 01-Jan-2024",
                    evidence_type="policy_schedule",
                )
            ],
        )
        assert valid_source.source_type == "document"
        assert len(valid_source.evidence) == 1

        # Invalid without evidence
        with pytest.raises(ValidationError, match="Document-derived facts require evidence"):
            FactSource(source_type="document", evidence=[])

    def test_derived_fact_provenance_requires_explanation(self):
        """Verify derived fact provenance strictly requires an explanation string."""
        # Valid with explanation
        valid_source = FactSource(
            source_type="derived",
            explanation="Calculated 34 months between start date and planned admission date.",
        )
        assert valid_source.source_type == "derived"
        assert valid_source.explanation is not None

        # Invalid without explanation
        with pytest.raises(ValidationError, match="Derived facts require a derivation explanation"):
            FactSource(source_type="derived", explanation=None)

    def test_case_rejects_fact_without_source(self):
        """Invariant: Every provided non-null fact must be registered in fact_sources."""
        with pytest.raises(ValidationError, match="Provided fact 'procedure' requires a source"):
            CaseDetails(
                case_id="case-err-01",
                procedure="Cholecystectomy",
                fact_sources={},  # Missing 'procedure' source
            )

    def test_case_rejects_source_for_missing_fact(self):
        """Invariant: Cannot register a source for a fact that is None."""
        with pytest.raises(ValidationError, match="Source provided for missing fact 'hospital_name'"):
            CaseDetails(
                case_id="case-err-02",
                hospital_name=None,
                fact_sources={
                    "hospital_name": FactSource(source_type="user_provided"),
                },
            )

    def test_numeric_constraints(self):
        """Verify ge=0 constraints on policy_age_months and estimated_cost."""
        with pytest.raises(ValidationError):
            CaseDetails(
                case_id="case-err-03",
                policy_age_months=-1,
                fact_sources={"policy_age_months": FactSource(source_type="user_provided")},
            )

        with pytest.raises(ValidationError):
            CaseDetails(
                case_id="case-err-04",
                estimated_cost=Decimal("-100.00"),
                fact_sources={"estimated_cost": FactSource(source_type="user_provided")},
            )


class TestSampleReviewOutputsM1:
    """Verifies complete, incomplete, supported, unresolved, and conflict sample packets."""

    def test_list_and_get_sample_packets(self):
        """Verify documented loader API works as expected for Owner A."""
        names = list_sample_packet_names()
        expected = ["incomplete_review", "supported_finding", "conflict_review", "revised_finding"]
        assert set(names) == set(expected)

        for name in names:
            packet = get_sample_packet(name)
            assert isinstance(packet, ReviewPacket)
            # Verify it returns a deep copy
            copy_packet = get_sample_packet(name)
            assert copy_packet is not packet

    def test_load_sample_packet_from_json(self):
        """Verify JSON loader helper loads valid ReviewPackets by name or path."""
        for name in list_sample_packet_names():
            packet = load_sample_packet_from_json(name)
            assert isinstance(packet, ReviewPacket)
            assert packet.authorization_status == "not verified"

    def test_complete_review_sample_has_supported_finding_and_proper_status(self):
        """Verify SAMPLE_SUPPORTED_FINDING_PACKET represents a complete review."""
        packet = SAMPLE_SUPPORTED_FINDING_PACKET
        assert packet.review_status == "complete"
        assert packet.stopped_reason == "review_complete"
        assert len(packet.findings) >= 1

        finding = packet.findings[0]
        assert finding.status == "supported"
        assert len(finding.evidence) >= 1
        assert finding.evidence[0].page > 0
        assert len(finding.next_action) > 0

        # Insurer authorization is strictly decoupled and unverified
        assert packet.authorization_status == "not verified"

    def test_incomplete_review_sample_has_unresolved_finding_and_checklist(self):
        """Verify SAMPLE_INCOMPLETE_REVIEW_PACKET represents an incomplete review with gaps."""
        packet = SAMPLE_INCOMPLETE_REVIEW_PACKET
        assert packet.review_status == "incomplete"
        assert packet.stopped_reason == "missing_information"
        assert packet.stop_details is not None

        finding = packet.findings[0]
        assert finding.status == "unresolved"
        assert len(finding.missing_facts) > 0
        assert len(packet.missing_evidence_checklist) >= 1
        assert len(packet.unresolved_questions) >= 1

    def test_conflict_review_sample_has_conflict_finding_and_uncertain_applicability(self):
        """Verify SAMPLE_CONFLICT_PACKET represents conflicting evidence between documents."""
        packet = SAMPLE_CONFLICT_PACKET
        assert packet.review_status == "incomplete"
        assert packet.stopped_reason == "conflicting_evidence"

        finding = packet.findings[0]
        assert finding.status == "conflict"
        assert len(finding.evidence) >= 2  # Cites both conflicting documents

        # Document applicability explains the uncertainty
        assert len(packet.document_applicability) >= 1
        assert packet.document_applicability[0].status == "uncertain"

    def test_revised_finding_sample_has_replay_audit_trail(self):
        """Verify SAMPLE_REVISED_FINDING_PACKET captures Evidence Change Replay."""
        packet = SAMPLE_REVISED_FINDING_PACKET
        assert packet.packet_version == 2
        assert len(packet.revisions) == 1

        rev = packet.revisions[0]
        assert rev.old_status == "unresolved"
        assert rev.new_status == "supported"
        assert rev.old_finding_revision == 1
        assert rev.new_finding_revision == 2
        assert rev.trigger_type == "new_document"
        assert len(rev.triggering_evidence) >= 1

    def test_sample_fixtures_are_explicitly_identified_as_fixtures(self):
        """Verify that all sample packets clearly identify as development fixtures."""
        for name, packet in ALL_SAMPLE_PACKETS.items():
            assert packet.packet_id.startswith("pkt-fixture-")
            assert packet.run_id.startswith("run-fixture-")
            assert packet.case.case_id.startswith("case-fixture-")
