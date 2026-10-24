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

                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT 'v1',
                    sha256 TEXT NOT NULL,
                    evidence_type TEXT NOT NULL DEFAULT 'other',
                    uploaded_at TEXT NOT NULL,
                    extraction_status TEXT NOT NULL DEFAULT 'pending',
                    total_pages INTEGER NOT NULL DEFAULT 0,
                    file_path TEXT NOT NULL,
                    error_message TEXT,
                    PRIMARY KEY (document_id, version),
                    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_documents_case ON documents(case_id);
                CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(case_id, sha256);

                CREATE TABLE IF NOT EXISTS document_pages (
                    document_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    is_blank INTEGER NOT NULL DEFAULT 0,
                    character_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (document_id, version, page_number),
                    FOREIGN KEY (document_id, version) REFERENCES documents(document_id, version) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_pages_doc ON document_pages(document_id, version);
                CREATE INDEX IF NOT EXISTS idx_pages_case ON document_pages(case_id);
                """
            )
