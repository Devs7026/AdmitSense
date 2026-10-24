"""Tests for AdmitSense SQLite CaseRepository."""

from datetime import date
from decimal import Decimal
import tempfile
from pathlib import Path
import pytest

from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_admitsense.db"
        db = Database(db_path=db_path)
        yield CaseRepository(db=db), db_path


def test_create_incomplete_case_and_reopen(temp_repo):
    repo, db_path = temp_repo

    # 1. Case with incomplete information (unknown facts are None)
    case_1 = CaseDetails(
        case_id="case-001",
        member_name="Ramesh Sharma",
        procedure="Total Knee Replacement",
        hospital_name="Apex Super Specialty Hospital",
        estimated_cost=Decimal("250000.00"),
        # policy_id, dates, policy_age_months remain None/unknown
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
            "estimated_cost": FactSource(source_type="user_provided"),
        },
    )

    created = repo.create_case(case_1)
    assert created.case_id == "case-001"
    assert created.policy_id is None
    assert created.policy_start_date is None

    # 2. Save and reopen it
    loaded = repo.get_case("case-001")
    assert loaded is not None
    assert loaded.case_id == "case-001"
    assert loaded.member_name == "Ramesh Sharma"
    assert loaded.procedure == "Total Knee Replacement"
    assert loaded.estimated_cost == Decimal("250000.00")
    assert loaded.policy_id is None
    assert loaded.policy_start_date is None
    assert "member_name" in loaded.fact_sources
    assert loaded.fact_sources["member_name"].source_type == "user_provided"
    assert "policy_id" not in loaded.fact_sources


def test_persistence_across_restart(temp_repo):
    repo, db_path = temp_repo

    case = CaseDetails(
        case_id="case-persist-01",
        member_name="Priya Patel",
        policy_id="POL-998877",
        policy_start_date=date(2022, 1, 15),
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "policy_start_date": FactSource(source_type="user_provided"),
        },
    )
    repo.create_case(case)

    # 3. Simulate application restart by creating a new Database/Repository instance pointing to the same file
    new_db = Database(db_path=db_path)
    new_repo = CaseRepository(db=new_db)

    reopened = new_repo.get_case("case-persist-01")
    assert reopened is not None
    assert reopened.member_name == "Priya Patel"
    assert reopened.policy_id == "POL-998877"
    assert reopened.policy_start_date == date(2022, 1, 15)
    assert reopened.procedure is None


def test_case_isolation(temp_repo):
    repo, _ = temp_repo

    # 4. Create two distinct cases and confirm no data mixing
    case_a = CaseDetails(
        case_id="case-patient-a",
        member_name="Patient Alpha",
        procedure="Cataract Surgery",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
        },
    )
    case_b = CaseDetails(
        case_id="case-patient-b",
        member_name="Patient Beta",
        procedure="Coronary Angioplasty",
        hospital_name="Heart Care Institute",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
        },
    )

    repo.create_case(case_a)
    repo.create_case(case_b)

    retrieved_a = repo.get_case("case-patient-a")
    retrieved_b = repo.get_case("case-patient-b")

    assert retrieved_a.member_name == "Patient Alpha"
    assert retrieved_a.procedure == "Cataract Surgery"
    assert retrieved_a.hospital_name is None

    assert retrieved_b.member_name == "Patient Beta"
    assert retrieved_b.procedure == "Coronary Angioplasty"
    assert retrieved_b.hospital_name == "Heart Care Institute"

    all_cases = repo.list_cases()
    assert len(all_cases) == 2
    case_ids = [c.case_id for c in all_cases]
    assert "case-patient-a" in case_ids
    assert "case-patient-b" in case_ids


def test_update_case(temp_repo):
    repo, _ = temp_repo

    case = CaseDetails(
        case_id="case-update-01",
        member_name="Anil Kumar",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
        },
    )
    repo.create_case(case)

    # Update with new fact
    updated_case = CaseDetails(
        case_id="case-update-01",
        member_name="Anil Kumar",
        hospital_name="City General Hospital",
        planned_admission_date=date(2026, 11, 1),
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
            "planned_admission_date": FactSource(source_type="user_provided"),
        },
    )
    repo.update_case(updated_case)

    reloaded = repo.get_case("case-update-01")
    assert reloaded.hospital_name == "City General Hospital"
    assert reloaded.planned_admission_date == date(2026, 11, 1)
