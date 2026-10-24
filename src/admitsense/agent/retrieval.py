"""Evidence retrieval and citation verification service for AdmitSense bounded agent."""

from __future__ import annotations

import re
from typing import Any, Iterator, Literal, NamedTuple
from pydantic import BaseModel, ConfigDict, Field

from admitsense.schemas import Evidence, EvidenceType

from admitsense.documents.models import DocumentRecord, ExtractedPage, ExtractionStatus
from admitsense.schemas import Evidence, EvidenceType
from admitsense.storage.database import Database

__all__ = [
    "DocumentRecord",
    "ExtractedPage",
    "ExtractionStatus",
    "RetrievalError",
    "DocumentNotFoundError",
    "CaseOwnershipError",
    "VersionMismatchError",
    "PageOutOfBoundsError",
    "DocumentUnreadableError",
    "normalize_whitespace",
    "PageSearchResult",
    "CitationVerificationResult",
    "EvidenceRetrievalService",
]


class RetrievalError(Exception):
    """Base exception for evidence retrieval failures."""


class DocumentNotFoundError(RetrievalError):
    """Raised when a requested document does not exist in the case."""


class CaseOwnershipError(RetrievalError):
    """Raised when attempting to access a document belonging to a different case."""


class VersionMismatchError(RetrievalError):
    """Raised when a cited document version does not match the stored version."""


class PageOutOfBoundsError(RetrievalError):
    """Raised when a page number is <= 0 or exceeds total document pages."""


class DocumentUnreadableError(RetrievalError):
    """Raised when attempting to read from an unreadable or error-state document."""


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace and Unicode punctuation for robust quotation matching.

    Replaces non-breaking spaces, typographical single/double quotes,
    em/en dashes, and collapses any whitespace sequence (spaces, tabs, newlines)
    into a single ASCII space.
    """
    if not text:
        return ""

    # Replace typographical quotes and symbols with standard ASCII
    replacements = {
        "\u00a0": " ",  # Non-breaking space
        "\u2018": "'",  # Left single quotation mark
        "\u2019": "'",  # Right single quotation mark
        "\u201c": '"',  # Left double quotation mark
        "\u201d": '"',  # Right double quotation mark
        "\u2013": "-",  # En dash
        "\u2014": "-",  # Em dash
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Collapse any sequence of whitespace characters into a single space
    return " ".join(text.split())


class PageSearchResult(BaseModel):
    """Structured result returned by search_pages.

    Supports tuple unpacking (document_id, version, page_number, matching_snippet)
    to satisfy the CONTRACTS.md protocol while providing rich metadata.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str
    version: str
    page_number: int
    matching_snippet: str
    case_id: str
    score: float = 1.0
    match_count: int = 1

    def __iter__(self) -> Iterator[Any]:
        """Allows tuple unpacking: doc_id, ver, pg, snip = result"""
        return iter(
            (
                self.document_id,
                self.version,
                self.page_number,
                self.matching_snippet,
            )
        )

    def __getitem__(self, index: int) -> Any:
        return (
            self.document_id,
            self.version,
            self.page_number,
            self.matching_snippet,
        )[index]


class CitationVerificationResult(NamedTuple):
    """Result of citation verification against physical page text.

    Unpacks as `(is_valid, reason)`.
    """

    is_valid: bool
    reason: str
    document_id: str | None = None
    version: str | None = None
    page_number: int | None = None
    matched_quote: str | None = None


class EvidenceRetrievalService:
    """Case-scoped retrieval and citation verification service.

    Implements the EvidenceRetrieval contract defined in docs/CONTRACTS.md.
    Enforces strict case boundaries, physical page numbering (1-based),
    whitespace normalization, and explicit failures for fabricated quotes.
    """

    def __init__(
        self,
        initial_documents: list[DocumentRecord] | None = None,
        db: Database | None = None,
    ) -> None:
        # Keyed by (case_id, document_id, version)
        self._documents: dict[tuple[str, str, str], DocumentRecord] = {}
        self._db = db
        if initial_documents:
            for doc in initial_documents:
                self.add_document(doc)

    def _load_from_db(self, case_id: str | None = None) -> None:
        """Load document records and extracted pages from SQLite database."""
        if not self._db:
            return
        with self._db.get_connection() as conn:
            query = "SELECT * FROM documents"
            params: list[object] = []
            if case_id:
                query += " WHERE case_id = ?"
                params.append(case_id)
            doc_rows = conn.execute(query, params).fetchall()
            for d in doc_rows:
                pages_query = """
                    SELECT page_number, text, is_blank, character_count
                    FROM document_pages
                    WHERE document_id = ? AND version = ?
                    ORDER BY page_number ASC
                """
                page_rows = conn.execute(
                    pages_query, (d["document_id"], d["version"])
                ).fetchall()
                pages = [
                    ExtractedPage(
                        page_number=p["page_number"],
                        text=p["text"],
                        is_blank=bool(p["is_blank"]),
                        character_count=p["character_count"],
                    )
                    for p in page_rows
                ]
                rec = DocumentRecord(
                    document_id=d["document_id"],
                    case_id=d["case_id"],
                    filename=d["filename"],
                    version=d["version"],
                    sha256=d["sha256"],
                    evidence_type=d["evidence_type"],
                    uploaded_at=d["uploaded_at"],
                    extraction_status=d["extraction_status"],
                    total_pages=d["total_pages"],
                    file_path=d["file_path"],
                    pages=pages,
                    error_message=d["error_message"],
                )
                self.add_document(rec)

    def add_document(self, doc: DocumentRecord) -> None:
        """Register an immutable document version in the store."""
        key = (doc.case_id, doc.document_id, doc.version)
        self._documents[key] = doc

    def get_document(
        self,
        document_id: str,
        version: str | None = None,
        case_id: str | None = None,
    ) -> DocumentRecord | None:
        """Retrieve a document record matching the ID, version, and case."""
        for (c_id, d_id, v), doc in self._documents.items():
            if d_id == document_id:
                if case_id is not None and c_id != case_id:
                    continue
                if version is not None and v != version:
                    continue
                return doc

        # Fallback to DB if not found in memory
        if self._db:
            self._load_from_db(case_id)
            for (c_id, d_id, v), doc in self._documents.items():
                if d_id == document_id:
                    if case_id is not None and c_id != case_id:
                        continue
                    if version is not None and v != version:
                        continue
                    return doc

        return None

    def list_documents(self, case_id: str | None = None) -> list[DocumentRecord]:
        """List all documents, optionally filtered by case_id."""
        if self._db:
            self._load_from_db(case_id)
        if case_id is None:
            return list(self._documents.values())
        return [doc for (c_id, _, _), doc in self._documents.items() if c_id == case_id]

    def read_page(
        self,
        document_id: str,
        version: str,
        page_number: int,
        case_id: str | None = None,
    ) -> ExtractedPage:
        """Read an exact physical page. Raises explicit errors on contract violations."""
        if page_number < 1:
            raise PageOutOfBoundsError(
                f"Page number {page_number} is invalid. PDF pages are 1-based (gt=0)."
            )

        # Check cross-case leaks
        doc_any_case = self.get_document(document_id, version)
        if doc_any_case is not None and case_id is not None and doc_any_case.case_id != case_id:
            raise CaseOwnershipError(
                f"Access denied: Document '{document_id}' belongs to case "
                f"'{doc_any_case.case_id}', not '{case_id}'."
            )

        # Check existence
        doc = self.get_document(document_id, version, case_id)
        if doc is None:
            # Check if document exists under another version
            alt_version_doc = self.get_document(document_id, case_id=case_id)
            if alt_version_doc is not None:
                raise VersionMismatchError(
                    f"Version mismatch for document '{document_id}': "
                    f"requested '{version}', available '{alt_version_doc.version}'."
                )
            raise DocumentNotFoundError(
                f"Document '{document_id}' (version '{version}') not found"
                + (f" for case '{case_id}'." if case_id else ".")
            )

        # Check extraction status
        if doc.extraction_status in {"unreadable", "error"}:
            raise DocumentUnreadableError(
                f"Document '{document_id}' cannot be read: extraction status is "
                f"'{doc.extraction_status}' ({doc.error_message or 'unreadable scan'})."
            )

        # Check page bounds
        if page_number > doc.total_pages:
            raise PageOutOfBoundsError(
                f"Page {page_number} is out of bounds for document '{document_id}' "
                f"which has {doc.total_pages} total pages."
            )

        # Find page in pages list
        for page in doc.pages:
            if page.page_number == page_number:
                return page

        # If pages list was not populated up to total_pages
        raise PageOutOfBoundsError(
            f"Page {page_number} is not recorded in extracted pages for '{document_id}'."
        )

    def get_page_text(
        self,
        document_id: str,
        version: str,
        page_number: int,
        case_id: str | None = None,
    ) -> str | None:
        """Retrieve physical page text. Returns None if unreadable or out of bounds."""
        try:
            page = self.read_page(document_id, version, page_number, case_id)
            return page.text
        except (RetrievalError, Exception):
            return None

    def search_pages(
        self,
        case_id: str,
        query: str,
        document_id: str | None = None,
        max_results: int = 5,
    ) -> list[PageSearchResult]:
        """Search page texts for a specific case using case-insensitive term matching.

        Enforces strict case scoping and excludes unreadable/error documents.
        Returns snippets with surrounding context.
        """
        if not query or not query.strip():
            return []

        norm_query = normalize_whitespace(query).lower()
        query_terms = [t for t in re.split(r"\W+", norm_query) if t]
        if not query_terms:
            return []

        results: list[PageSearchResult] = []
        candidate_docs = self.list_documents(case_id)
        if document_id:
            candidate_docs = [d for d in candidate_docs if d.document_id == document_id]

        stopwords = {
            "the", "a", "an", "and", "or", "of", "in", "for", "to", "with",
            "is", "are", "shall", "all", "apply", "applies", "under", "section", "clause",
        }

        for doc in candidate_docs:
            if doc.extraction_status in {"unreadable", "error"}:
                continue

            for page in doc.pages:
                if page.is_blank or not page.text:
                    continue

                norm_text = normalize_whitespace(page.text)
                norm_text_lower = norm_text.lower()

                # Count distinct terms matched
                matched_terms = [t for t in query_terms if t in norm_text_lower]
                if not matched_terms:
                    continue

                term_coverage = len(matched_terms) / len(query_terms)
                phrase_matches = norm_text_lower.count(norm_query)

                # Score distinct terms higher, downweight generic stopwords
                term_score = 0.0
                for t in matched_terms:
                    count = norm_text_lower.count(t)
                    weight = 0.5 if t in stopwords else 5.0
                    term_score += weight * count

                score = (phrase_matches * 25.0) + (term_coverage * 20.0) + term_score

                # Calculate snippet location around best match
                match_pos = norm_text_lower.find(norm_query)
                if match_pos == -1:
                    # Find first non-stopword match position
                    non_stopwords = [t for t in matched_terms if t not in stopwords]
                    best_term = non_stopwords[0] if non_stopwords else matched_terms[0]
                    match_pos = norm_text_lower.find(best_term)

                start_idx = max(0, match_pos - 60)
                end_idx = min(len(norm_text), match_pos + len(norm_query) + 100)

                snippet = norm_text[start_idx:end_idx].strip()
                if start_idx > 0:
                    snippet = "..." + snippet
                if end_idx < len(norm_text):
                    snippet = snippet + "..."

                results.append(
                    PageSearchResult(
                        document_id=doc.document_id,
                        version=doc.version,
                        page_number=page.page_number,
                        matching_snippet=snippet,
                        case_id=doc.case_id,
                        score=score,
                        match_count=phrase_matches or len(matched_terms),
                    )
                )

        # Sort by score descending and return top max_results
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    def verify_citation(
        self,
        evidence: Evidence,
        case_id: str | None = None,
    ) -> CitationVerificationResult:
        """Validate whether an Evidence citation is authentic and matches page text.

        Enforces:
        1. Physical page number > 0.
        2. Document exists within the specified case.
        3. Version matches cited document_version.
        4. Page number is within bounds.
        5. Document is readable (not unreadable/error).
        6. Normalized quote is a true substring of the normalized page text.
        """
        # 1. Page bounds check
        if evidence.page <= 0:
            return CitationVerificationResult(
                is_valid=False,
                reason=f"Invalid physical page number {evidence.page}. Page numbers must be > 0.",
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
            )

        # 2. Check cross-case ownership if case_id is supplied
        if case_id is not None:
            any_doc = self.get_document(evidence.document_id, evidence.document_version)
            if any_doc is not None and any_doc.case_id != case_id:
                return CitationVerificationResult(
                    is_valid=False,
                    reason=(
                        f"Wrong-case reference: Document '{evidence.document_id}' belongs to case "
                        f"'{any_doc.case_id}', not '{case_id}'."
                    ),
                    document_id=evidence.document_id,
                    version=evidence.document_version,
                    page_number=evidence.page,
                )

        # 3. Document existence and version check
        doc = self.get_document(evidence.document_id, evidence.document_version, case_id)
        if doc is None:
            alt_doc = self.get_document(evidence.document_id, case_id=case_id)
            if alt_doc is not None:
                return CitationVerificationResult(
                    is_valid=False,
                    reason=(
                        f"Version mismatch: document '{evidence.document_id}' exists as version "
                        f"'{alt_doc.version}', but citation specified '{evidence.document_version}'."
                    ),
                    document_id=evidence.document_id,
                    version=evidence.document_version,
                    page_number=evidence.page,
                )
            return CitationVerificationResult(
                is_valid=False,
                reason=f"Document '{evidence.document_id}' does not exist"
                + (f" in case '{case_id}'." if case_id else "."),
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
            )

        # 4. Unreadable status check
        if doc.extraction_status in {"unreadable", "error"}:
            return CitationVerificationResult(
                is_valid=False,
                reason=(
                    f"Document '{evidence.document_id}' extraction status is '{doc.extraction_status}'. "
                    "Unreadable documents cannot support evidence citations."
                ),
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
            )

        # 5. Page number bounds
        if evidence.page > doc.total_pages:
            return CitationVerificationResult(
                is_valid=False,
                reason=(
                    f"Page {evidence.page} is out of bounds for document '{evidence.document_id}' "
                    f"(total pages: {doc.total_pages})."
                ),
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
            )

        # 6. Retrieve page text
        page_text = self.get_page_text(evidence.document_id, evidence.document_version, evidence.page, case_id)
        if not page_text or not page_text.strip():
            return CitationVerificationResult(
                is_valid=False,
                reason=f"Page {evidence.page} of document '{evidence.document_id}' is blank.",
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
            )

        # 7. Quotation matching with whitespace normalisation
        norm_quote = normalize_whitespace(evidence.quote)
        norm_page = normalize_whitespace(page_text)

        if norm_quote in norm_page:
            return CitationVerificationResult(
                is_valid=True,
                reason=(
                    f"Citation verified: quotation found on page {evidence.page} of "
                    f"'{evidence.document_id}' ({evidence.document_version})."
                ),
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
                matched_quote=norm_quote,
            )

        # Case-insensitive fallback check for diagnostic clarity
        if norm_quote.lower() in norm_page.lower():
            return CitationVerificationResult(
                is_valid=True,
                reason=(
                    f"Citation verified (case-insensitive match): quotation found on page {evidence.page} of "
                    f"'{evidence.document_id}' ({evidence.document_version})."
                ),
                document_id=evidence.document_id,
                version=evidence.document_version,
                page_number=evidence.page,
                matched_quote=norm_quote,
            )

        # Fabricated quote failure
        return CitationVerificationResult(
            is_valid=False,
            reason=(
                f"Fabricated quotation: quote '{evidence.quote[:60]}...' was not found "
                f"on page {evidence.page} of document '{evidence.document_id}' ({evidence.document_version})."
            ),
            document_id=evidence.document_id,
            version=evidence.document_version,
            page_number=evidence.page,
        )
