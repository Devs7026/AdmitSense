"""Tests for Milestone M2-A: PDF ingestion, extraction, versioning, and evidence retrieval."""

import tempfile
from pathlib import Path
import pytest

from admitsense.documents.extractor import extract_pdf_pages, normalize_whitespace
from admitsense.documents.models import UploadValidationConfig
from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_hospital_estimate_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    build_synthetic_unreadable_pdf,
)
from admitsense.schemas import CaseDetails, Evidence, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m2.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        retrieval = SqliteEvidenceRetrieval(db=db)

        # Create two isolated cases
        case_repo.create_case(
            CaseDetails(
                case_id="case-m2-001",
                member_name="Ramesh Sharma",
                fact_sources={"member_name": FactSource(source_type="user_provided")},
            )
        )
        case_repo.create_case(
            CaseDetails(
                case_id="case-m2-002",
                member_name="Priya Patel",
                fact_sources={"member_name": FactSource(source_type="user_provided")},
            )
        )

        yield {
            "db": db,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "retrieval": retrieval,
            "doc_dir": doc_dir,
        }


def test_pdf_extraction_physical_pages_and_blank_retention():
    """Verify physical 1-based numbering and empty page retention."""
    pdf_bytes = build_synthetic_policy_pdf()
    pages, status, error_msg = extract_pdf_pages(pdf_bytes)

    assert status == "partial"  # Because Page 7 is an explicit blank page
    assert len(pages) == 15

    # Physical page numbers must start at 1 and match index + 1
    for idx, p in enumerate(pages):
        assert p.page_number == idx + 1

    # Page 7 is blank
    p7 = pages[6]
    assert p7.page_number == 7
    assert p7.is_blank is True
    assert p7.text == ""
    assert p7.character_count == 0

    # Page 14 has Section 4.2(b) waiting period clause
    p14 = pages[13]
    assert p14.page_number == 14
    assert p14.is_blank is False
    assert "Section 4.2(b)" in p14.text
    assert "twenty-four (24) continuous months" in p14.text


def test_unreadable_pdf_extraction():
    """Verify explicit unreadable status for empty / raster-only PDF."""
    pdf_bytes = build_synthetic_unreadable_pdf()
    pages, status, error_msg = extract_pdf_pages(pdf_bytes)

    assert status == "unreadable"
    assert len(pages) == 2
    assert all(p.is_blank for p in pages)
    assert error_msg is not None
    assert "No extractable text found" in error_msg


def test_pdf_upload_limits_and_validation():
    """Verify configured file size and page count limits."""
    cfg = UploadValidationConfig(max_file_size_bytes=1000, max_pages=5)

    # Size limit violation
    large_pdf = build_synthetic_policy_pdf()  # > 5000 bytes
    with pytest.raises(ValueError, match="exceeds maximum allowed limit"):
        extract_pdf_pages(large_pdf, config=cfg)

    # Invalid format (non-PDF)
    with pytest.raises(ValueError, match="does not start with standard %PDF header"):
        extract_pdf_pages(b"Not a PDF content at all", config=cfg)

    # Page limit violation
    cfg_pages = UploadValidationConfig(max_file_size_bytes=100000, max_pages=5)
    with pytest.raises(ValueError, match="exceeds the maximum configured limit of 5 pages"):
        extract_pdf_pages(large_pdf, config=cfg_pages)


def test_duplicate_upload_handling(test_env):
    """Verify that uploading the identical file twice does not create duplicate versions."""
    storage: DocumentStorage = test_env["doc_storage"]
    pdf_bytes = build_synthetic_schedule_pdf()

    # First upload: creates v1
    doc1, is_dup1 = storage.save_document(
        case_id="case-m2-001",
        filename="Policy_Renewal_Schedule.pdf",
        content=pdf_bytes,
        evidence_type="policy_schedule",
    )
    assert is_dup1 is False
    assert doc1.version == "v1"

    # Second upload with exact same bytes: detected as duplicate
    doc2, is_dup2 = storage.save_document(
        case_id="case-m2-001",
        filename="Policy_Renewal_Schedule.pdf",
        content=pdf_bytes,
        evidence_type="policy_schedule",
    )
    assert is_dup2 is True
    assert doc2.document_id == doc1.document_id
    assert doc2.version == "v1"
    assert doc2.sha256 == doc1.sha256

    # Verify document list only has 1 record
    docs = storage.list_documents("case-m2-001")
    assert len(docs) == 1


def test_immutable_version_increment(test_env):
    """Verify that uploading a modified document increments version and preserves v1."""
    storage: DocumentStorage = test_env["doc_storage"]
    pdf_v1 = build_synthetic_policy_pdf()
    pdf_v2 = build_synthetic_endorsement_pdf()  # Different content with same filename

    # Upload v1
    doc_v1, _ = storage.save_document(
        case_id="case-m2-001",
        filename="Master_Policy.pdf",
        content=pdf_v1,
        evidence_type="policy_wording",
    )
    assert doc_v1.version == "v1"

    # Upload revised version under same filename
    doc_v2, is_dup = storage.save_document(
        case_id="case-m2-001",
        filename="Master_Policy.pdf",
        content=pdf_v2,
        evidence_type="endorsement",
    )
    assert is_dup is False
    assert doc_v2.version == "v2"
    assert doc_v2.document_id == doc_v1.document_id
    assert doc_v2.sha256 != doc_v1.sha256

    # Retrieve v1: must remain unchanged
    retrieved_v1 = storage.get_document(doc_v1.document_id, "v1")
    assert retrieved_v1 is not None
    assert retrieved_v1.total_pages == 15

    # Retrieve v2: must have its own pages
    retrieved_v2 = storage.get_document(doc_v2.document_id, "v2")
    assert retrieved_v2 is not None
    assert retrieved_v2.total_pages == 1


def test_case_isolation_for_documents(test_env):
    """Verify documents uploaded to Case A are completely isolated from Case B."""
    storage: DocumentStorage = test_env["doc_storage"]
    pdf_bytes = build_synthetic_hospital_estimate_pdf()

    storage.save_document(
        case_id="case-m2-001",
        filename="Estimate.pdf",
        content=pdf_bytes,
        evidence_type="hospital_estimate",
    )

    docs_case_1 = storage.list_documents("case-m2-001")
    docs_case_2 = storage.list_documents("case-m2-002")

    assert len(docs_case_1) == 1
    assert len(docs_case_2) == 0


def test_evidence_retrieval_and_citation_verification(test_env):
    """Verify get_page_text, verify_citation, and search_pages."""
    storage: DocumentStorage = test_env["doc_storage"]
    retrieval: SqliteEvidenceRetrieval = test_env["retrieval"]

    pdf_bytes = build_synthetic_policy_pdf()
    doc, _ = storage.save_document(
        case_id="case-m2-001",
        filename="Care_Health_Gold_Policy_Wording.pdf",
        content=pdf_bytes,
        evidence_type="policy_wording",
    )

    # 1. get_page_text
    page_14_text = retrieval.get_page_text(doc.document_id, doc.version, 14)
    assert page_14_text is not None
    assert "Section 4.2(b)" in page_14_text

    blank_page_7 = retrieval.get_page_text(doc.document_id, doc.version, 7)
    assert blank_page_7 == ""

    non_existent = retrieval.get_page_text(doc.document_id, doc.version, 99)
    assert non_existent is None

    # 2. verify_citation: valid quote on Page 14
    valid_ev = Evidence(
        document_id=doc.document_id,
        document_version=doc.version,
        page=14,
        quote="Section 4.2(b): Treatment for degenerative joint disorders including total knee replacement",
        evidence_type="policy_wording",
    )
    is_valid, reason = retrieval.verify_citation(valid_ev)
    assert is_valid is True
    assert "Citation verified" in reason

    # 3. verify_citation: valid quote on WRONG page (e.g. Page 13)
    wrong_page_ev = Evidence(
        document_id=doc.document_id,
        document_version=doc.version,
        page=13,
        quote="Section 4.2(b): Treatment for degenerative joint disorders including total knee replacement",
        evidence_type="policy_wording",
    )
    is_valid, reason = retrieval.verify_citation(wrong_page_ev)
    assert is_valid is False
    assert "Quote not found on physical page" in reason

    # 4. verify_citation: fabricated quote
    fabricated_ev = Evidence(
        document_id=doc.document_id,
        document_version=doc.version,
        page=14,
        quote="The insurer guarantees 100 percent reimbursement without conditions.",
        evidence_type="policy_wording",
    )
    is_valid, reason = retrieval.verify_citation(fabricated_ev)
    assert is_valid is False

    # 5. search_pages across documents for case
    matches = retrieval.search_pages(
        case_id="case-m2-001",
        query="joint replacement",
    )
    assert len(matches) >= 1
    doc_id, ver, page_num, snippet = matches[0]
    assert doc_id == doc.document_id
    assert ver == doc.version
    assert page_num == 14
    assert "joint" in snippet.lower() and "replacement" in snippet.lower()
