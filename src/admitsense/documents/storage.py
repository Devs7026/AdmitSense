from __future__ import annotations

import datetime
import hashlib
import re
from pathlib import Path
from typing import Any, Tuple

from admitsense.documents.extractor import extract_pdf_pages
from admitsense.documents.models import DocumentRecord, ExtractedPage, ExtractionStatus, UploadValidationConfig
from admitsense.storage.database import Database


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-_")
    return slug or "unnamed"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class DocumentStorage:
    """Manages immutable PDF file persistence, versioning, duplicate detection, and SQLite indexing."""

    def __init__(
        self,
        db: Database | None = None,
        storage_dir: Path | str | None = None,
        config: UploadValidationConfig | None = None,
    ) -> None:
        self.db = db or Database()
        self.storage_dir = Path(storage_dir or (Path("data") / "documents"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or UploadValidationConfig()

    def save_document(
        self,
        case_id: str,
        filename: str,
        content: bytes,
        evidence_type: str = "other",
    ) -> Tuple[DocumentRecord, bool]:
        """
        Processes and stores a PDF document for a case.

        Duplicate Handling:
        1. Calculates SHA-256 hash.
        2. If an identical file (matching sha256) was already uploaded for this case,
           returns the existing DocumentRecord and sets is_duplicate=True.
        3. If a different file with the same filename/doc_id was uploaded earlier,
           creates a new immutable version (v1 -> v2) without modifying prior versions.

        Returns:
            (DocumentRecord, is_duplicate)
        """
        # Enforce case exists
        with self.db.get_connection() as conn:
            case_row = conn.execute(
                "SELECT case_id FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if not case_row:
                raise ValueError(f"Cannot upload document: Case '{case_id}' does not exist.")

        file_sha256 = hashlib.sha256(content).hexdigest()

        # Check for existing duplicate by SHA-256 within the same case
        with self.db.get_connection() as conn:
            duplicate_row = conn.execute(
                """
                SELECT document_id, version FROM documents
                WHERE case_id = ? AND sha256 = ?
                """,
                (case_id, file_sha256),
            ).fetchone()

            if duplicate_row:
                existing_record = self.get_document(
                    duplicate_row["document_id"], duplicate_row["version"]
                )
                if existing_record:
                    return existing_record, True

        # Generate stable document_id based on base filename
        stem = Path(filename).stem
        doc_id = f"doc-{_slugify(stem)}"

        # Compute next immutable version
        with self.db.get_connection() as conn:
            version_rows = conn.execute(
                """
                SELECT version FROM documents
                WHERE case_id = ? AND document_id = ?
                """,
                (case_id, doc_id),
            ).fetchall()

            existing_versions = [r["version"] for r in version_rows]
            next_version = self._calculate_next_version(existing_versions)

        # Extract pages with pypdf
        pages, extraction_status, error_message = extract_pdf_pages(
            content, config=self.config
        )

        # Save binary file to disk
        dest_dir = self.storage_dir / case_id / doc_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_dest = dest_dir / f"{next_version}_{filename}"
        with open(file_dest, "wb") as f:
            f.write(content)

        now = _utc_now_iso()
        total_pages = len(pages)

        # Persist document metadata and extracted pages in SQLite transaction
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    document_id,
                    case_id,
                    filename,
                    version,
                    sha256,
                    evidence_type,
                    uploaded_at,
                    extraction_status,
                    total_pages,
                    file_path,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    case_id,
                    filename,
                    next_version,
                    file_sha256,
                    evidence_type,
                    now,
                    extraction_status,
                    total_pages,
                    str(file_dest),
                    error_message,
                ),
            )

            # Insert all pages retaining physical 1-based index and blank pages
            for page in pages:
                conn.execute(
                    """
                    INSERT INTO document_pages (
                        document_id,
                        version,
                        case_id,
                        page_number,
                        text,
                        is_blank,
                        character_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        next_version,
                        case_id,
                        page.page_number,
                        page.text,
                        1 if page.is_blank else 0,
                        page.character_count,
                    ),
                )

        record = DocumentRecord(
            document_id=doc_id,
            case_id=case_id,
            filename=filename,
            version=next_version,
            sha256=file_sha256,
            evidence_type=evidence_type,
            uploaded_at=now,
            extraction_status=extraction_status,
            total_pages=total_pages,
            file_path=str(file_dest),
            pages=pages,
            error_message=error_message,
        )

        return record, False

    def get_document(self, document_id: str, version: str) -> DocumentRecord | None:
        """Fetch an immutable document record along with its extracted pages."""
        with self.db.get_connection() as conn:
            doc_row = conn.execute(
                """
                SELECT * FROM documents
                WHERE document_id = ? AND version = ?
                """,
                (document_id, version),
            ).fetchone()

            if not doc_row:
                return None

            page_rows = conn.execute(
                """
                SELECT page_number, text, is_blank, character_count
                FROM document_pages
                WHERE document_id = ? AND version = ?
                ORDER BY page_number ASC
                """,
                (document_id, version),
            ).fetchall()

            pages = [
                ExtractedPage(
                    page_number=r["page_number"],
                    text=r["text"],
                    is_blank=bool(r["is_blank"]),
                    character_count=r["character_count"],
                )
                for r in page_rows
            ]

            return DocumentRecord(
                document_id=doc_row["document_id"],
                case_id=doc_row["case_id"],
                filename=doc_row["filename"],
                version=doc_row["version"],
                sha256=doc_row["sha256"],
                evidence_type=doc_row["evidence_type"],
                uploaded_at=doc_row["uploaded_at"],
                extraction_status=doc_row["extraction_status"],
                total_pages=doc_row["total_pages"],
                file_path=doc_row["file_path"],
                pages=pages,
                error_message=doc_row["error_message"],
            )

    def list_documents(self, case_id: str) -> list[DocumentRecord]:
        """List all documents and versions for a given case, ordered by upload time descending."""
        with self.db.get_connection() as conn:
            doc_rows = conn.execute(
                """
                SELECT * FROM documents
                WHERE case_id = ?
                ORDER BY uploaded_at DESC, version DESC
                """,
                (case_id,),
            ).fetchall()

            records: list[DocumentRecord] = []
            for r in doc_rows:
                records.append(
                    DocumentRecord(
                        document_id=r["document_id"],
                        case_id=r["case_id"],
                        filename=r["filename"],
                        version=r["version"],
                        sha256=r["sha256"],
                        evidence_type=r["evidence_type"],
                        uploaded_at=r["uploaded_at"],
                        extraction_status=r["extraction_status"],
                        total_pages=r["total_pages"],
                        file_path=r["file_path"],
                        pages=[],  # Lightweight summary; use get_document for pages
                        error_message=r["error_message"],
                    )
                )
            return records

    def get_document_pages(self, document_id: str, version: str) -> list[ExtractedPage]:
        """Fetch all extracted pages for a specific document version."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT page_number, text, is_blank, character_count
                FROM document_pages
                WHERE document_id = ? AND version = ?
                ORDER BY page_number ASC
                """,
                (document_id, version),
            ).fetchall()

            return [
                ExtractedPage(
                    page_number=r["page_number"],
                    text=r["text"],
                    is_blank=bool(r["is_blank"]),
                    character_count=r["character_count"],
                )
                for r in rows
            ]

    def get_raw_pdf_bytes(self, document_id: str, version: str) -> bytes | None:
        """Read the binary PDF content from disk."""
        doc = self.get_document(document_id, version)
        if not doc or not doc.file_path:
            return None
        p = Path(doc.file_path)
        if p.exists():
            return p.read_bytes()
        return None

    @staticmethod
    def _calculate_next_version(existing_versions: list[str]) -> str:
        if not existing_versions:
            return "v1"

        highest_num = 0
        for v in existing_versions:
            match = re.match(r"^v(\d+)$", v)
            if match:
                highest_num = max(highest_num, int(match.group(1)))

        return f"v{highest_num + 1}"
