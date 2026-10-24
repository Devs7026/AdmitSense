from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


DEFAULT_DB_PATH = Path("data") / "admitsense.db"


class Database:
    """Manages SQLite database connections and table schemas for AdmitSense."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = DEFAULT_DB_PATH

        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_tables()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self) -> None:
        with self.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    member_name TEXT,
                    policy_id TEXT,
                    policy_start_date TEXT,
                    continuous_coverage_start_date TEXT,
                    planned_admission_date TEXT,
                    policy_age_months INTEGER,
                    procedure TEXT,
                    hospital_name TEXT,
                    estimated_cost TEXT,
                    currency TEXT DEFAULT 'INR',
                    fact_sources_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_cases_updated_at ON cases(updated_at DESC);
                """
            )
