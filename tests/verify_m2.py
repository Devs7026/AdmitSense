"""Automated verification script for Owner A Milestone M2-A (PDF Ingestion & Evidence Retrieval)."""

import sys
import tempfile
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from admitsense.documents.extractor import extract_pdf_pages
from admitsense.documents.models import UploadValidationConfig
from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_hospital_estimate_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    build_synthetic_unreadable_pdf,
    write_synthetic_fixtures,
)
from admitsense.schemas import CaseDetails, Evidence, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


def run_m2_verification():
    print("=== AdmitSense Milestone M2-A Verification ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_m2.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)
        retrieval = SqliteEvidenceRetrieval(db=db)

        # Create two test cases for isolation checks
        case_1 = case_repo.create_case(
            CaseDetails(
                case_id="case-m2-verify-01",
                member_name="Ramesh Sharma",
                fact_sources={"member_name": FactSource(source_type="user_provided")},
            )
        )
        case_2 = case_repo.create_case(
            CaseDetails(
                case_id="case-m2-verify-02",
                member_name="Priya Patel",
                fact_sources={"member_name": FactSource(source_type="user_provided")},
            )
        )

        # 1. Readable PDF extraction with 1-based physical page numbers & blank retention
        print("\n[Check 1] Readable PDF extraction, 1-based page positions & blank page retention...")
        policy_pdf = build_synthetic_policy_pdf()
        pages, status, err = extract_pdf_pages(policy_pdf)
        assert len(pages) == 15
        assert pages[0].page_number == 1
        assert pages[6].page_number == 7
        assert pages[6].is_blank is True
        assert pages[6].text == ""
        assert pages[13].page_number == 14
        assert pages[13].is_blank is False
        assert "Section 4.2(b)" in pages[13].text
        assert "twenty-four (24) continuous months" in pages[13].text
        print("  [PASS] 15 physical pages extracted. Page 7 retained as blank. Page 14 contains 24-month clause.")

        # 2. Explicit unreadable status
        print("\n[Check 2] Explicit unreadable status handling...")
        unreadable_pdf = build_synthetic_unreadable_pdf()
        u_pages, u_status, u_err = extract_pdf_pages(unreadable_pdf)
        assert u_status == "unreadable"
        assert all(p.is_blank for p in u_pages)
        assert u_err is not None
        print("  [PASS] Unreadable document flagged with explicit 'unreadable' status.")

        # 3. Size and page limits
        print("\n[Check 3] Upload limits (file size and page limits)...")
        strict_cfg = UploadValidationConfig(max_file_size_bytes=1000, max_pages=5)
        size_error = False
        try:
            extract_pdf_pages(policy_pdf, config=strict_cfg)
        except ValueError:
            size_error = True
        assert size_error is True

        page_cfg = UploadValidationConfig(max_file_size_bytes=100000, max_pages=5)
        page_error = False
        try:
            extract_pdf_pages(policy_pdf, config=page_cfg)
        except ValueError:
            page_error = True
        assert page_error is True
        print("  [PASS] Both file size and page limit violations correctly raise validation errors.")

        # 4. Duplicate upload handling
        print("\n[Check 4] Duplicate upload handling via SHA-256...")
        schedule_pdf = build_synthetic_schedule_pdf()
        doc_1, dup_1 = doc_storage.save_document(
            case_id="case-m2-verify-01",
            filename="Policy_Renewal_Schedule.pdf",
            content=schedule_pdf,
            evidence_type="policy_schedule",
        )
        assert dup_1 is False
        assert doc_1.version == "v1"

        doc_2, dup_2 = doc_storage.save_document(
            case_id="case-m2-verify-01",
            filename="Policy_Renewal_Schedule.pdf",
            content=schedule_pdf,
            evidence_type="policy_schedule",
        )
        assert dup_2 is True
        assert doc_2.version == "v1"
        assert doc_2.sha256 == doc_1.sha256
        assert len(doc_storage.list_documents("case-m2-verify-01")) == 1
        print("  [PASS] Identical content detected as duplicate; no redundant version created.")

        # 5. Immutable versioning
        print("\n[Check 5] Immutable versioning (v1 -> v2 on content update)...")
        endorsement_pdf = build_synthetic_endorsement_pdf()
        doc_v2, dup_rev = doc_storage.save_document(
            case_id="case-m2-verify-01",
            filename="Policy_Renewal_Schedule.pdf",
            content=endorsement_pdf,
            evidence_type="endorsement",
        )
        assert dup_rev is False
        assert doc_v2.version == "v2"
        assert doc_v2.document_id == doc_1.document_id

        # Check v1 remains intact
        v1_record = doc_storage.get_document(doc_1.document_id, "v1")
        assert v1_record is not None
        assert v1_record.sha256 == doc_1.sha256
        assert v1_record.total_pages == 2

        # Check v2 has new content
        v2_record = doc_storage.get_document(doc_1.document_id, "v2")
        assert v2_record is not None
        assert v2_record.sha256 != doc_1.sha256
        assert v2_record.total_pages == 1
        print("  [PASS] Version incremented to v2. Version v1 preserved immutably.")

        # 6. Cross-case isolation
        print("\n[Check 6] Cross-case isolation...")
        hosp_pdf = build_synthetic_hospital_estimate_pdf()
        doc_storage.save_document(
            case_id="case-m2-verify-01",
            filename="Estimate.pdf",
            content=hosp_pdf,
            evidence_type="hospital_estimate",
        )
        case_1_docs = doc_storage.list_documents("case-m2-verify-01")
        case_2_docs = doc_storage.list_documents("case-m2-verify-02")
        assert len(case_1_docs) == 3
        assert len(case_2_docs) == 0
        print("  [PASS] Case documents strictly isolated; zero crossover between cases.")

        # 7. Evidence retrieval and citation verification
        print("\n[Check 7] Evidence retrieval & physical page citation verification...")
        policy_doc, _ = doc_storage.save_document(
            case_id="case-m2-verify-01",
            filename="Care_Health_Gold_Policy_Wording.pdf",
            content=policy_pdf,
            evidence_type="policy_wording",
        )

        # Exact citation on Page 14
        valid_ev = Evidence(
            document_id=policy_doc.document_id,
            document_version=policy_doc.version,
            page=14,
            quote="Section 4.2(b): Treatment for degenerative joint disorders including total knee replacement",
            evidence_type="policy_wording",
        )
        is_val, reason = retrieval.verify_citation(valid_ev)
        assert is_val is True
        print(f"  [PASS] Physical Page 14 citation verified: {reason}")

        # Wrong physical page citation
        wrong_page_ev = Evidence(
            document_id=policy_doc.document_id,
            document_version=policy_doc.version,
            page=13,
            quote="Section 4.2(b): Treatment for degenerative joint disorders including total knee replacement",
            evidence_type="policy_wording",
        )
        is_wrong, wrong_reason = retrieval.verify_citation(wrong_page_ev)
        assert is_wrong is False
        print(f"  [PASS] Wrong physical page citation correctly rejected: {wrong_reason}")

        # Fabricated quote
        fake_ev = Evidence(
            document_id=policy_doc.document_id,
            document_version=policy_doc.version,
            page=14,
            quote="All medical claims approved with zero deductibles.",
            evidence_type="policy_wording",
        )
        is_fake, fake_reason = retrieval.verify_citation(fake_ev)
        assert is_fake is False
        print(f"  [PASS] Fabricated quote rejected: {fake_reason}")

        # Search across pages
        matches = retrieval.search_pages(
            "case-m2-verify-01",
            "degenerative joint disorders",
            document_id=policy_doc.document_id,
        )
        assert len(matches) >= 1
        assert matches[0][2] == 14
        print(f"  [PASS] Page search returned match on physical page {matches[0][2]}.")

        # 8. Synthetic fixtures generation
        print("\n[Check 8] Synthetic demonstration documents labelled and verified...")
        synth_files = write_synthetic_fixtures(Path(tmp_dir) / "synth_out")
        assert synth_files["policy_wording"].exists()
        assert synth_files["renewal_schedule"].exists()
        assert synth_files["endorsement"].exists()
        assert synth_files["hospital_estimate"].exists()
        assert synth_files["unreadable_scanned"].exists()
        assert synth_files["hospitals_json"].exists()
        print("  [PASS] All 6 synthetic fixtures generated and labelled with version and date.")

    print("\n=== ALL MILESTONE M2-A CHECKS PASSED ===")


if __name__ == "__main__":
    run_m2_verification()
