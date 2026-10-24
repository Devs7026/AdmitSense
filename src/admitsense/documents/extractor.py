from __future__ import annotations

import io
from typing import Tuple

import pypdf
from pypdf.errors import PdfReadError

from admitsense.documents.models import ExtractedPage, ExtractionStatus, UploadValidationConfig


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace by collapsing multiple spaces, tabs, and newlines into single spaces."""
    return " ".join(text.split())


def extract_pdf_pages(
    pdf_bytes: bytes,
    config: UploadValidationConfig | None = None,
) -> Tuple[list[ExtractedPage], ExtractionStatus, str | None]:
    """
    Extracts text from PDF bytes using pypdf, preserving physical 1-based page positions.

    Invariants:
    1. Physical 1-based page numbering: page 1 is index 0; blank pages are retained
       so page numbering does not drift.
    2. Document text is treated strictly as untrusted data.
    3. Explicit unreadable / partial / error statuses.
    4. Size and page limits enforced.

    Returns:
        (pages, extraction_status, error_message)
    """
    cfg = config or UploadValidationConfig()

    # Size limit check
    if len(pdf_bytes) > cfg.max_file_size_bytes:
        raise ValueError(
            f"File size ({len(pdf_bytes):,} bytes) exceeds maximum allowed limit of "
            f"{cfg.max_file_size_bytes:,} bytes."
        )

    # Magic bytes check
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Invalid file format: File does not start with standard %PDF header.")

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes), strict=False)
    except (PdfReadError, Exception) as e:
        return [], "error", f"Failed to parse PDF document: {e}"

    if reader.is_encrypted:
        return [], "error", "PDF is encrypted or password-protected and cannot be processed."

    total_pages = len(reader.pages)
    if total_pages == 0:
        return [], "unreadable", "PDF document contains 0 pages."

    if total_pages > cfg.max_pages:
        raise ValueError(
            f"Document has {total_pages} pages, which exceeds the maximum configured limit of "
            f"{cfg.max_pages} pages."
        )

    pages: list[ExtractedPage] = []
    blank_count = 0

    for idx, page_obj in enumerate(reader.pages):
        page_number = idx + 1  # 1-based physical page number
        try:
            raw_text = page_obj.extract_text() or ""
        except Exception:
            raw_text = ""

        cleaned = normalize_whitespace(raw_text)
        is_blank = len(cleaned) == 0

        if is_blank:
            blank_count += 1
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text="",
                    is_blank=True,
                    character_count=0,
                )
            )
        else:
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=cleaned,
                    is_blank=False,
                    character_count=len(cleaned),
                )
            )

    if blank_count == total_pages:
        status: ExtractionStatus = "unreadable"
        error_msg = (
            "No extractable text found across all pages. The document may be a scanned image "
            "or raster PDF."
        )
    elif blank_count > 0:
        status = "partial"
        error_msg = f"{blank_count} of {total_pages} pages contain no extractable text."
    else:
        status = "extracted"
        error_msg = None

    return pages, status, error_msg
