from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from admitsense.schemas import Finding, MissingEvidenceItem, ReviewPacket, Revision
from admitsense.storage.database import Database


class StaleReviewError(RuntimeError):
    """Raised when an execution attempts to save against an outdated case/packet state."""
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewRepository:
    """SQLite repository for persistent ReviewPacket storage and audit trails."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def save_review_packet(
        self,
        packet: ReviewPacket,
        expected_prior_packet_version: int | None = None,
    ) -> ReviewPacket:
        """
        Persists a review packet snapshot atomically in a single SQLite transaction.
        1. If expected_prior_packet_version is given, validates that no newer packet has been committed.
        2. Inserts review_packets metadata and serialized JSON snapshot.
        3. Inserts current findings with their revision number.
        4. Inserts new Revision entries linking old and new finding revisions.
        5. Inserts missing evidence checklist items.
        Rolls back completely if any step fails.
        """
        now = _utc_now_iso()
        case_id = packet.case.case_id

        # Preserve user-declared statuses (e.g. "user_does_not_have") across re-reviews
        with self.db.get_connection() as conn:
            user_declared = conn.execute(
                """
                SELECT item_id, status, resolution_note FROM checklist_items
                WHERE case_id = ? AND status IN ('user_does_not_have', 'provided_pending_review')
                """,
                (case_id,),
            ).fetchall()
            user_decl_map = {r["item_id"]: (r["status"], r["resolution_note"]) for r in user_declared}

        if user_decl_map and packet.missing_evidence_checklist:
            updated_items = []
            for item in packet.missing_evidence_checklist:
                if item.item_id in user_decl_map:
                    prev_status, prev_note = user_decl_map[item.item_id]
                    updated_items.append(
                        item.model_copy(update={"status": prev_status, "resolution_note": prev_note})
                    )
                else:
                    updated_items.append(item)
            packet = packet.model_copy(update={"missing_evidence_checklist": updated_items})

        packet_dict = packet.model_dump(mode="json")
        packet_json = json.dumps(packet_dict)

        with self.db.get_connection() as conn:
            # 0. Stale result optimistic concurrency check
            if expected_prior_packet_version is not None:
                latest_row = conn.execute(
                    """
                    SELECT packet_version FROM review_packets
                    WHERE case_id = ?
                    ORDER BY packet_version DESC, created_at DESC
                    LIMIT 1
                    """,
                    (case_id,),
                ).fetchone()
                latest_version = latest_row["packet_version"] if latest_row else 0
                if latest_version != expected_prior_packet_version:
                    raise StaleReviewError(
                        f"Stale review rejected: Expected prior packet version {expected_prior_packet_version}, "
                        f"but case '{case_id}' already has newer packet version {latest_version}. Aborting update."
                    )
            # 1. Insert review_packets
            conn.execute(
                """
                INSERT INTO review_packets (
                    packet_id,
                    case_id,
                    packet_version,
                    run_id,
                    review_status,
                    tool_steps_used,
                    stopped_reason,
                    stop_details,
                    authorization_status,
                    packet_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    packet.packet_id,
                    case_id,
                    packet.packet_version,
                    packet.run_id,
                    packet.review_status,
                    packet.tool_steps_used,
                    packet.stopped_reason,
                    packet.stop_details,
                    packet.authorization_status,
                    packet_json,
                    now,
                ),
            )

            # 2. Insert findings
            for finding in packet.findings:
                conn.execute(
                    """
                    INSERT INTO findings (
                        finding_id,
                        packet_id,
                        case_id,
                        revision,
                        topic,
                        status,
                        conclusion,
                        next_action,
                        evidence_json,
                        relevant_case_facts_json,
                        missing_facts_json,
                        limitations_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding.finding_id,
                        packet.packet_id,
                        case_id,
                        finding.revision,
                        finding.topic,
                        finding.status,
                        finding.conclusion,
                        finding.next_action,
                        json.dumps([e.model_dump(mode="json") for e in finding.evidence]),
                        json.dumps(finding.relevant_case_facts),
                        json.dumps(finding.missing_facts),
                        json.dumps(finding.limitations),
                        now,
                    ),
                )

            # 3. Insert revisions
            for rev in packet.revisions:
                conn.execute(
                    """
                    INSERT INTO revisions (
                        revision_id,
                        packet_id,
                        finding_id,
                        case_id,
                        old_finding_revision,
                        new_finding_revision,
                        old_conclusion,
                        new_conclusion,
                        old_status,
                        new_status,
                        trigger_type,
                        triggering_evidence_json,
                        changed_case_facts_json,
                        reason,
                        affected_topics_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rev.revision_id,
                        packet.packet_id,
                        rev.finding_id,
                        case_id,
                        rev.old_finding_revision,
                        rev.new_finding_revision,
                        rev.old_conclusion,
                        rev.new_conclusion,
                        rev.old_status,
                        rev.new_status,
                        rev.trigger_type,
                        json.dumps([e.model_dump(mode="json") for e in rev.triggering_evidence]),
                        json.dumps(rev.changed_case_facts),
                        rev.reason,
                        json.dumps(rev.affected_topics),
                        now,
                    ),
                )

            # 4. Insert checklist items
            for item in packet.missing_evidence_checklist:
                conn.execute(
                    """
                    INSERT INTO checklist_items (
                        item_id,
                        packet_id,
                        case_id,
                        related_finding_ids_json,
                        requested_information,
                        why_it_matters,
                        suggested_source,
                        status,
                        resolution_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.item_id,
                        packet.packet_id,
                        case_id,
                        json.dumps(item.related_finding_ids),
                        item.requested_information,
                        item.why_it_matters,
                        item.suggested_source,
                        item.status,
                        item.resolution_note,
                    ),
                )

        return packet

    def get_latest_review_packet(self, case_id: str) -> ReviewPacket | None:
        """Fetch the most recent review packet snapshot for a case."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT packet_json FROM review_packets
                WHERE case_id = ?
                ORDER BY packet_version DESC, created_at DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()

            if not row:
                return None

            data = json.loads(row["packet_json"])
            return ReviewPacket.model_validate(data)

    def list_review_packets(self, case_id: str) -> list[ReviewPacket]:
        """List all review packet snapshots for a case in reverse chronological order."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT packet_json FROM review_packets
                WHERE case_id = ?
                ORDER BY packet_version DESC, created_at DESC
                """,
                (case_id,),
            ).fetchall()

            return [ReviewPacket.model_validate(json.loads(r["packet_json"])) for r in rows]

    def get_finding_history(self, case_id: str, finding_id: str) -> list[Revision]:
        """Retrieve chronological audit trail of all revisions for a specific finding."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM revisions
                WHERE case_id = ? AND finding_id = ?
                GROUP BY revision_id
                ORDER BY new_finding_revision ASC, created_at ASC
                """,
                (case_id, finding_id),
            ).fetchall()

            revisions: list[Revision] = []
            for r in rows:
                rev_dict = {
                    "revision_id": r["revision_id"],
                    "finding_id": r["finding_id"],
                    "old_finding_revision": r["old_finding_revision"],
                    "new_finding_revision": r["new_finding_revision"],
                    "old_conclusion": r["old_conclusion"],
                    "new_conclusion": r["new_conclusion"],
                    "old_status": r["old_status"],
                    "new_status": r["new_status"],
                    "trigger_type": r["trigger_type"],
                    "triggering_evidence": json.loads(r["triggering_evidence_json"]),
                    "changed_case_facts": json.loads(r["changed_case_facts_json"]),
                    "reason": r["reason"],
                    "affected_topics": json.loads(r["affected_topics_json"]),
                    "created_at": r["created_at"],
                }
                revisions.append(Revision.model_validate(rev_dict))
            return revisions

    def get_finding_snapshot(
        self,
        case_id: str,
        finding_id: str,
        revision: int,
    ) -> Finding | None:
        """Fetch the exact historical finding record and its evidence at a specific revision."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT f.*, p.packet_version
                FROM findings f
                JOIN review_packets p ON f.packet_id = p.packet_id
                WHERE f.case_id = ? AND f.finding_id = ? AND f.revision = ?
                ORDER BY p.packet_version DESC, f.created_at DESC
                LIMIT 1
                """,
                (case_id, finding_id, revision),
            ).fetchone()

            if not row:
                return None

            finding_dict = {
                "finding_id": row["finding_id"],
                "revision": row["revision"],
                "topic": row["topic"],
                "status": row["status"],
                "conclusion": row["conclusion"],
                "next_action": row["next_action"],
                "evidence": json.loads(row["evidence_json"]),
                "relevant_case_facts": json.loads(row["relevant_case_facts_json"]),
                "missing_facts": json.loads(row["missing_facts_json"]),
                "limitations": json.loads(row["limitations_json"]),
                "created_at": row["created_at"],
            }
            return Finding.model_validate(finding_dict)

    def list_all_revisions(self, case_id: str) -> list[Revision]:
        """Retrieve chronological audit trail of all revisions across all findings for a case."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM revisions
                WHERE case_id = ?
                GROUP BY revision_id
                ORDER BY created_at ASC
                """,
                (case_id,),
            ).fetchall()

            revisions: list[Revision] = []
            for r in rows:
                rev_dict = {
                    "revision_id": r["revision_id"],
                    "finding_id": r["finding_id"],
                    "old_finding_revision": r["old_finding_revision"],
                    "new_finding_revision": r["new_finding_revision"],
                    "old_conclusion": r["old_conclusion"],
                    "new_conclusion": r["new_conclusion"],
                    "old_status": r["old_status"],
                    "new_status": r["new_status"],
                    "trigger_type": r["trigger_type"],
                    "triggering_evidence": json.loads(r["triggering_evidence_json"]),
                    "changed_case_facts": json.loads(r["changed_case_facts_json"]),
                    "reason": r["reason"],
                    "affected_topics": json.loads(r["affected_topics_json"]),
                    "created_at": r["created_at"],
                }
                revisions.append(Revision.model_validate(rev_dict))
            return revisions

    def update_checklist_item_status(
        self,
        case_id: str,
        item_id: str,
        status: str,
        resolution_note: str | None = None,
    ) -> ReviewPacket | None:
        """
        Updates a checklist item's status (e.g. 'user_does_not_have' or 'provided_pending_review')
        and persists atomically into both the relational table and the latest ReviewPacket JSON.
        """
        with self.db.get_connection() as conn:
            # 1. Update relational table
            conn.execute(
                """
                UPDATE checklist_items
                SET status = ?, resolution_note = ?
                WHERE case_id = ? AND item_id = ?
                """,
                (status, resolution_note, case_id, item_id),
            )

            # 2. Update snapshot JSON in latest review_packets row
            row = conn.execute(
                """
                SELECT packet_id, packet_json FROM review_packets
                WHERE case_id = ?
                ORDER BY packet_version DESC, created_at DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()

            if not row:
                return None

            packet_data = json.loads(row["packet_json"])
            chk_list = packet_data.get("missing_evidence_checklist", [])
            item_found = False
            for chk in chk_list:
                if chk.get("item_id") == item_id:
                    chk["status"] = status
                    chk["resolution_note"] = resolution_note
                    item_found = True
                    break

            if item_found:
                new_json = json.dumps(packet_data)
                conn.execute(
                    """
                    UPDATE review_packets
                    SET packet_json = ?
                    WHERE packet_id = ?
                    """,
                    (new_json, row["packet_id"]),
                )

            return ReviewPacket.model_validate(packet_data)

    def save_activity_event(self, event: Any, case_id: str) -> None:
        """Persist a tool activity event into the database."""
        run_id = getattr(event, "run_id", "") or (event.get("run_id", "") if isinstance(event, dict) else "")
        step_number = getattr(event, "step_number", 0) or (event.get("step_number", 0) if isinstance(event, dict) else 0)
        tool_name = getattr(event, "tool_name", "") or (event.get("tool_name", "") if isinstance(event, dict) else "")
        tool_args = getattr(event, "tool_arguments", {}) or (event.get("tool_arguments", {}) if isinstance(event, dict) else {})
        status = getattr(event, "status", "completed") or (event.get("status", "completed") if isinstance(event, dict) else "completed")
        summary = getattr(event, "summary", "") or (event.get("summary", "") if isinstance(event, dict) else "")
        error = getattr(event, "error", None) or (event.get("error", None) if isinstance(event, dict) else None)
        created_at = getattr(event, "timestamp", None)
        created_at_iso = created_at.isoformat() if isinstance(created_at, datetime) else _utc_now_iso()

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tool_activity_events (
                    run_id, case_id, step_number, tool_name, tool_arguments_json, status, summary, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    case_id,
                    step_number,
                    tool_name,
                    json.dumps(tool_args),
                    status,
                    summary,
                    error,
                    created_at_iso,
                ),
            )

    def list_activity_events(
        self,
        run_id: str | None = None,
        case_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tool activity events matching run_id or case_id in chronological order."""
        with self.db.get_connection() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM tool_activity_events WHERE run_id = ? ORDER BY id ASC",
                    (run_id,),
                ).fetchall()
            elif case_id:
                rows = conn.execute(
                    "SELECT * FROM tool_activity_events WHERE case_id = ? ORDER BY id ASC",
                    (case_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tool_activity_events ORDER BY id ASC"
                ).fetchall()

            events = []
            for r in rows:
                events.append({
                    "id": r["id"],
                    "run_id": r["run_id"],
                    "case_id": r["case_id"],
                    "step_number": r["step_number"],
                    "tool_name": r["tool_name"],
                    "tool_arguments": json.loads(r["tool_arguments_json"]),
                    "status": r["status"],
                    "summary": r["summary"],
                    "error": r["error"],
                    "created_at": r["created_at"],
                })
            return events

