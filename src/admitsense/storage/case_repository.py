from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.database import Database


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseRepository:
    """SQLite repository for CaseDetails persistence, retrieval, and updates."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def create_case(self, case: CaseDetails) -> CaseDetails:
        """
        Persist a new case.
        Raises ValueError if a case with the same case_id already exists.
        """
        now = _utc_now_iso()
        fact_sources_json = json.dumps(
            {k: v.model_dump(mode="json") for k, v in case.fact_sources.items()}
        )

        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT case_id FROM cases WHERE case_id = ?", (case.case_id,)
            ).fetchone()
            if existing:
                raise ValueError(f"Case with ID '{case.case_id}' already exists.")

            conn.execute(
                """
                INSERT INTO cases (
                    case_id,
                    member_name,
                    policy_id,
                    policy_start_date,
                    continuous_coverage_start_date,
                    planned_admission_date,
                    policy_age_months,
                    procedure,
                    hospital_name,
                    estimated_cost,
                    currency,
                    fact_sources_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.member_name,
                    case.policy_id,
                    case.policy_start_date.isoformat() if case.policy_start_date else None,
                    case.continuous_coverage_start_date.isoformat()
                    if case.continuous_coverage_start_date
                    else None,
                    case.planned_admission_date.isoformat()
                    if case.planned_admission_date
                    else None,
                    case.policy_age_months,
                    case.procedure,
                    case.hospital_name,
                    str(case.estimated_cost) if case.estimated_cost is not None else None,
                    case.currency,
                    fact_sources_json,
                    now,
                    now,
                ),
            )

        return case

    def get_case(self, case_id: str) -> CaseDetails | None:
        """Retrieve a case by ID. Returns None if not found."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_case(row)

    def update_case(self, case: CaseDetails) -> CaseDetails:
        """
        Update an existing case's facts and fact sources.
        Raises KeyError if the case does not exist.
        """
        now = _utc_now_iso()
        fact_sources_json = json.dumps(
            {k: v.model_dump(mode="json") for k, v in case.fact_sources.items()}
        )

        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE cases SET
                    member_name = ?,
                    policy_id = ?,
                    policy_start_date = ?,
                    continuous_coverage_start_date = ?,
                    planned_admission_date = ?,
                    policy_age_months = ?,
                    procedure = ?,
                    hospital_name = ?,
                    estimated_cost = ?,
                    currency = ?,
                    fact_sources_json = ?,
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    case.member_name,
                    case.policy_id,
                    case.policy_start_date.isoformat() if case.policy_start_date else None,
                    case.continuous_coverage_start_date.isoformat()
                    if case.continuous_coverage_start_date
                    else None,
                    case.planned_admission_date.isoformat()
                    if case.planned_admission_date
                    else None,
                    case.policy_age_months,
                    case.procedure,
                    case.hospital_name,
                    str(case.estimated_cost) if case.estimated_cost is not None else None,
                    case.currency,
                    fact_sources_json,
                    now,
                    case.case_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Case with ID '{case.case_id}' not found.")

        return case

    def list_cases(self) -> list[CaseDetails]:
        """Return all persisted cases ordered by updated_at descending."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cases ORDER BY updated_at DESC"
            ).fetchall()
            return [self._row_to_case(row) for row in rows]

    def delete_case(self, case_id: str) -> bool:
        """Delete a case by ID. Returns True if deleted, False if not found."""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM cases WHERE case_id = ?", (case_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_case(row: Any) -> CaseDetails:
        raw_sources = json.loads(row["fact_sources_json"] or "{}")
        fact_sources = {
            k: FactSource.model_validate(v) for k, v in raw_sources.items()
        }

        policy_start_date = (
            date.fromisoformat(row["policy_start_date"])
            if row["policy_start_date"]
            else None
        )
        continuous_coverage_start_date = (
            date.fromisoformat(row["continuous_coverage_start_date"])
            if row["continuous_coverage_start_date"]
            else None
        )
        planned_admission_date = (
            date.fromisoformat(row["planned_admission_date"])
            if row["planned_admission_date"]
            else None
        )
        estimated_cost = (
            Decimal(str(row["estimated_cost"]))
            if row["estimated_cost"] is not None
            else None
        )

        return CaseDetails(
            case_id=row["case_id"],
            member_name=row["member_name"],
            policy_id=row["policy_id"],
            policy_start_date=policy_start_date,
            continuous_coverage_start_date=continuous_coverage_start_date,
            planned_admission_date=planned_admission_date,
            policy_age_months=row["policy_age_months"],
            procedure=row["procedure"],
            hospital_name=row["hospital_name"],
            estimated_cost=estimated_cost,
            currency=row["currency"] or "INR",
            fact_sources=fact_sources,
        )
