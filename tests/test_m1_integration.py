"""Integration and contract tests for Milestone M1 (Case Persistence & Fixture Loading)."""

import json
from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError

from admitsense.schemas import CaseDetails, FactSource, ReviewPacket
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


def test_sample_packet_fixture_loads_valid():
    """Verify that Owner B's development sample packet fixture conforms to ReviewPacket."""
    fixture_path = Path("tests") / "fixtures" / "sample_packet.json"
    assert fixture_path.exists(), "Sample packet fixture must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    packet = ReviewPacket.model_validate(data)
    assert packet.packet_id == "pkt-sample-001"
    assert packet.packet_version == 1
    assert packet.authorization_status == "not verified"
    assert packet.tool_steps_used <= 8
    assert len(packet.findings) >= 1
    assert packet.findings[0].status == "unresolved"
    assert len(packet.missing_evidence_checklist) >= 1
    assert packet.case.case_id == "case-sample-001"


def test_case_details_fact_source_invariants():
    """Verify that missing facts cannot have sources, and provided facts require sources."""
    # Provided fact without source raises error
    with pytest.raises(ValidationError):
        CaseDetails(
            case_id="case-invalid-1",
            member_name="Ramesh Sharma",
            fact_sources={},  # Missing source for member_name
        )

    # Source provided for missing fact raises error
    with pytest.raises(ValidationError):
        CaseDetails(
            case_id="case-invalid-2",
            member_name=None,
            fact_sources={
                "member_name": FactSource(source_type="user_provided")
            },
        )


def test_empty_case_with_no_facts_persists(tmp_path):
    """Verify that an almost empty case (only case_id known) creates and reloads cleanly."""
    db_path = tmp_path / "empty_case.db"
    repo = CaseRepository(Database(db_path=db_path))

    case = CaseDetails(
        case_id="case-bare-bones",
        fact_sources={},
    )
    repo.create_case(case)

    reloaded = repo.get_case("case-bare-bones")
    assert reloaded is not None
    assert reloaded.case_id == "case-bare-bones"
    assert reloaded.member_name is None
    assert reloaded.policy_id is None
    assert reloaded.procedure is None
    assert reloaded.hospital_name is None
    assert reloaded.estimated_cost is None
    assert len(reloaded.fact_sources) == 0
