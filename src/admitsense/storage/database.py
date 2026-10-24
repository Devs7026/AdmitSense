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

                CREATE TABLE IF NOT EXISTS review_packets (
                    packet_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    packet_version INTEGER NOT NULL DEFAULT 1,
                    run_id TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    tool_steps_used INTEGER NOT NULL DEFAULT 0,
                    stopped_reason TEXT NOT NULL,
                    stop_details TEXT,
                    authorization_status TEXT NOT NULL DEFAULT 'not verified',
                    packet_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_packets_case ON review_packets(case_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS findings (
                    finding_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    next_action TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    relevant_case_facts_json TEXT NOT NULL DEFAULT '[]',
                    missing_facts_json TEXT NOT NULL DEFAULT '[]',
                    limitations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (finding_id, packet_id),
                    FOREIGN KEY (packet_id) REFERENCES review_packets(packet_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_findings_case ON findings(case_id);

                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    old_finding_revision INTEGER NOT NULL,
                    new_finding_revision INTEGER NOT NULL,
                    old_conclusion TEXT NOT NULL,
                    new_conclusion TEXT NOT NULL,
                    old_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    triggering_evidence_json TEXT NOT NULL DEFAULT '[]',
                    changed_case_facts_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT NOT NULL,
                    affected_topics_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (revision_id, packet_id),
                    FOREIGN KEY (packet_id) REFERENCES review_packets(packet_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_revisions_finding ON revisions(case_id, finding_id);

                CREATE TABLE IF NOT EXISTS checklist_items (
                    item_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    related_finding_ids_json TEXT NOT NULL DEFAULT '[]',
                    requested_information TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    suggested_source TEXT,
                    status TEXT NOT NULL DEFAULT 'requested',
                    resolution_note TEXT,
                    PRIMARY KEY (item_id, packet_id),
                    FOREIGN KEY (packet_id) REFERENCES review_packets(packet_id) ON DELETE CASCADE
                );
                """
            )
