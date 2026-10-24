"""Tests validating that sample review packet fixtures strictly comply with domain schemas and product invariants."""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from admitsense.schemas import (
    CaseDetails,
    Evidence,
    FactSource,
    Finding,
    ReviewPacket,
)
from tests.fixtures.sample_review_packets import (
    ALL_SAMPLE_PACKETS,
    SAMPLE_CONFLICT_PACKET,
    SAMPLE_INCOMPLETE_REVIEW_PACKET,
    SAMPLE_REVISED_FINDING_PACKET,
    SAMPLE_SUPPORTED_FINDING_PACKET,
)

FIXTURES_JSON_DIR = Path(__file__).parent / "fixtures" / "json"


class TestSampleReviewFixtures:
    """Validates the 4 sample review packets required for M0-B / M0-I."""

    def test_all_sample_packets_are_valid_review_packets(self):
        """Verify that all 4 fixtures pass Pydantic validation."""
        assert len(ALL_SAMPLE_PACKETS) == 4
        for name, packet in ALL_SAMPLE_PACKETS.items():
            assert isinstance(packet, ReviewPacket), f"{name} must be a ReviewPacket"
            assert packet.packet_id.startswith("pkt-fixture-")
            assert packet.tool_steps_used <= 8, "Tool budget must not exceed 8"
            assert packet.authorization_status == "not verified", (
                "Invariant: authorization status must default to 'not verified'"
            )

    def test_incomplete_review_with_missing_evidence(self):
        """Verify Fixture 1: Incomplete review with missing facts and checklist items."""
        packet = SAMPLE_INCOMPLETE_REVIEW_PACKET
        assert packet.review_status == "incomplete"
        assert packet.stopped_reason == "missing_information"
        assert packet.stop_details is not None

        # Verify missing case facts remain None
        assert packet.case.continuous_coverage_start_date is None
        assert packet.case.policy_start_date is None
        assert packet.case.policy_age_months is None

        # Verify unresolved finding explains missing facts
        finding = packet.findings[0]
        assert finding.status == "unresolved"
        assert "continuous_coverage_start_date" in finding.missing_facts
        assert len(finding.limitations) > 0
        assert len(finding.next_action) > 0

        # Verify missing evidence checklist item links to finding
        assert len(packet.missing_evidence_checklist) == 1
        item = packet.missing_evidence_checklist[0]
        assert item.related_finding_ids == [finding.finding_id]
        assert item.status == "requested"
        assert len(item.requested_information) > 0

    def test_supported_finding_with_citation(self):
        """Verify Fixture 2: Supported finding with exact physical page citation."""
        packet = SAMPLE_SUPPORTED_FINDING_PACKET
        assert packet.review_status == "complete"
        assert packet.stopped_reason == "review_complete"

        # Verify finding is supported and has evidence
        finding = packet.findings[0]
        assert finding.status == "supported"
        assert len(finding.evidence) >= 1

        # Invariant: Evidence citations must have physical page > 0
        citation = finding.evidence[0]
        assert citation.page == 14
        assert citation.page > 0
        assert citation.document_id == "doc-base-policy-star"
        assert citation.document_version == "v1"
        assert len(citation.quote) > 0

        # Invariant: Supported finding does NOT imply insurance approval
        assert packet.authorization_status == "not verified"
        assert packet.authorization_evidence == []

        # Verify fact sources
        assert "continuous_coverage_start_date" in packet.case.fact_sources
        source = packet.case.fact_sources["continuous_coverage_start_date"]
        assert source.source_type == "document"
        assert len(source.evidence) > 0

    def test_conflict_requiring_clarification(self):
        """Verify Fixture 3: Conflict between base policy and post-dated endorsement."""
        packet = SAMPLE_CONFLICT_PACKET
        assert packet.review_status == "incomplete"
        assert packet.stopped_reason == "conflicting_evidence"

        # Verify document applicability is marked uncertain
        assert len(packet.document_applicability) == 1
        app = packet.document_applicability[0]
        assert app.status == "uncertain"
        assert app.reason is not None

        # Verify conflict finding cites both contradictory documents
        finding = packet.findings[0]
        assert finding.status == "conflict"
        assert len(finding.evidence) == 2
        doc_ids = {e.document_id for e in finding.evidence}
        assert "doc-base-policy-silver" in doc_ids
        assert "doc-endorsement-2026-v1" in doc_ids

        # Verify actionable next action and unresolved questions
        assert len(finding.next_action) > 0
        assert len(packet.unresolved_questions) >= 1

    def test_revised_finding_with_evidence_replay(self):
        """Verify Fixture 4: Evidence Change Replay with incremented revision."""
        packet = SAMPLE_REVISED_FINDING_PACKET
        assert packet.packet_version == 2
        assert packet.review_status == "complete"
        assert packet.stopped_reason == "review_complete"

        # Verify finding is at revision 2
        finding = packet.findings[0]
        assert finding.revision == 2
        assert finding.status == "supported"

        # Verify Revision audit trail entry
        assert len(packet.revisions) == 1
        rev = packet.revisions[0]
        assert rev.finding_id == finding.finding_id
        assert rev.old_finding_revision == 1
        assert rev.new_finding_revision == 2
        assert rev.old_status == "unresolved"
        assert rev.new_status == "supported"
        assert rev.trigger_type == "new_document"
        assert len(rev.triggering_evidence) >= 1
        assert len(rev.reason) > 0

    def test_json_fixtures_roundtrip(self):
        """Verify JSON serialized fixtures can be reloaded and validate cleanly."""
        json_files = list(FIXTURES_JSON_DIR.glob("*.json"))
        assert len(json_files) == 4, "Must have 4 JSON fixtures"

        for json_path in json_files:
            with open(json_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            # Strip documentation comment before model validation
            raw_data.pop("_comment", None)

            # Re-validate via Pydantic model
            reloaded = ReviewPacket.model_validate(raw_data)
            assert isinstance(reloaded, ReviewPacket)
            assert reloaded.tool_steps_used <= 8
            assert reloaded.authorization_status == "not verified"

    def test_schema_rejection_rules(self):
        """Verify that invalid configurations are rejected by Pydantic models."""
        # 1. Supported finding without evidence must raise ValidationError
        with pytest.raises(ValidationError):
            Finding(
                finding_id="find-invalid",
                topic="Test Topic",
                status="supported",
                conclusion="No evidence provided",
                next_action="Action",
                evidence=[],  # Forbidden for supported findings
            )

        # 2. Page number <= 0 must raise ValidationError
        with pytest.raises(ValidationError):
            Evidence(
                document_id="doc-1",
                document_version="v1",
                page=0,  # Physical page must be > 0
                quote="Quote",
                evidence_type="policy_wording",
            )

        # 3. Tool steps > 8 must raise ValidationError
        with pytest.raises(ValidationError):
            ReviewPacket(
                packet_id="pkt-invalid",
                run_id="run-invalid",
                case=CaseDetails(case_id="case-1"),
                tool_steps_used=9,  # Capped at 8
                stopped_reason="tool_limit_reached",
            )

        # 4. Pending insurer review without submission evidence must raise ValidationError
        with pytest.raises(ValidationError):
            ReviewPacket(
                packet_id="pkt-invalid",
                run_id="run-invalid",
                case=CaseDetails(case_id="case-1"),
                authorization_status="pending insurer review",
                authorization_evidence=[],  # Forbidden without submission evidence
                stopped_reason="review_complete",
            )
