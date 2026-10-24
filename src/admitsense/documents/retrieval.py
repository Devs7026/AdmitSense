from __future__ import annotations

import re
from typing import Tuple

from admitsense.documents.extractor import normalize_whitespace
from admitsense.schemas import Evidence
from admitsense.storage.database import Database


class SqliteEvidenceRetrieval:
    """Retrieval service for inspecting physical page text and verifying citations."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def get_page_text(
        self,
        document_id: str,
        version: str,
        page_number: int,
    ) -> str | None:
        """
        Returns physical page text (1-based page_number) for agent search
        or UI evidence inspection. Returns None if document/page does not exist.
        """
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT text FROM document_pages
                WHERE document_id = ? AND version = ? AND page_number = ?
                """,
                (document_id, version, page_number),
            ).fetchone()

            if not row:
                return None
            return row["text"]

    def verify_citation(
        self,
        evidence: Evidence,
    ) -> Tuple[bool, str]:
        """
        Validates that evidence.quote appears within the specified document_id,
        version, and 1-based page number (after standard whitespace normalisation).
        Returns (is_valid, reason).
        """
        page_text = self.get_page_text(
            document_id=evidence.document_id,
            version=evidence.document_version,
            page_number=evidence.page,
        )

        if page_text is None:
            return (
                False,
                f"Page {evidence.page} of document '{evidence.document_id}' "
                f"({evidence.document_version}) was not found in storage.",
            )

        norm_quote = normalize_whitespace(evidence.quote)
        norm_page = normalize_whitespace(page_text)

        if not norm_quote:
            return False, "Citation quote is empty."

        # Case-insensitive substring match with normalized whitespace
        if norm_quote.lower() in norm_page.lower():
            return True, "Citation verified: exact quote found on physical page."

        return (
            False,
            f"Quote not found on physical page {evidence.page}. Page text excerpt: "
            f"'{norm_page[:120]}...'",
        )

    def search_pages(
        self,
        case_id: str,
        query: str,
        document_id: str | None = None,
        max_results: int = 5,
    ) -> list[Tuple[str, str, int, str]]:
        """
        Search extracted page text across documents for a case.
        Returns list of (document_id, version, page_number, matching_snippet).
        """
        norm_query = normalize_whitespace(query)
        if not norm_query:
            return []

        words = norm_query.split()
        with self.db.get_connection() as conn:
            where_clauses = ["case_id = ?", "is_blank = 0"]
            params: list[object] = [case_id]

            if document_id:
                where_clauses.append("document_id = ?")
                params.append(document_id)

            # Match all words in query
            for w in words:
                where_clauses.append("LOWER(text) LIKE ?")
                params.append(f"%{w.lower()}%")

            sql = f"""
                SELECT document_id, version, page_number, text
                FROM document_pages
                WHERE {" AND ".join(where_clauses)}
                ORDER BY page_number ASC LIMIT ?
            """
            params.append(max_results)

            rows = conn.execute(sql, params).fetchall()

            results: list[Tuple[str, str, int, str]] = []
            for r in rows:
                doc_id = r["document_id"]
                ver = r["version"]
                p_num = r["page_number"]
                full_text = r["text"]

                # Extract surrounding snippet around first matching word
                first_word = words[0].lower()
                idx = full_text.lower().find(first_word)
                if idx == -1:
                    idx = 0
                start = max(0, idx - 40)
                end = min(len(full_text), idx + len(first_word) + 60)
                snippet = full_text[start:end].strip()
                if start > 0:
                    snippet = f"...{snippet}"
                if end < len(full_text):
                    snippet = f"{snippet}..."

                results.append((doc_id, ver, p_num, snippet))

            return results
