"""Integration tests connecting Owner A's PDF extraction/storage with Owner B's agent retrieval service (M2-I)."""

import tempfile
from pathlib import Path
import pytest

from admitsense.agent.retrieval import (
    CaseOwnershipError,
    EvidenceRetrievalService,
    PageOutOfBoundsError,
)
from admitsense.documents.extractor import extract_pdf_pages
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    build_synthetic_unreadable_pdf,
)
from admitsense.schemas import CaseDetails, Evidence, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


@pytest.fixture
def integration_env():
    """Sets up an isolated database and storage directory with synthetic cases and extracted documents."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "m2_integration.db"
        storage_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=storage_dir)

        # 1. Create two test cases
        case_repo.create_case(
            CaseDetails(
                case_id="case-integ-001",
                member_name="Ramesh Sharma",
                fact_sources={"member_name": FactSource(source_type="user_provided")},
            )
        )
        case_repo.create_case(
            CaseDetails(
                case_id="case-integ-002",
                member_name="Priya Patel",
                fact_sources={"member_name": FactSource(source_type="user_provided")},
            )
        )

        # 2. Ingest and extract synthetic policy PDF for case 1
        policy_pdf = build_synthetic_policy_pdf()
        doc_policy, _ = doc_storage.save_document(
            case_id="case-integ-001",
            filename="Care_Health_Gold_Policy_Wording.pdf",
            content=policy_pdf,
            evidence_type="policy_wording",
        )

        # 3. Ingest and extract synthetic schedule PDF for case 1
        sched_pdf = build_synthetic_schedule_pdf()
        doc_sched, _ = doc_storage.save_document(
            case_id="case-integ-001",
            filename="Policy_Renewal_Schedule.pdf",
            content=sched_pdf,
            evidence_type="policy_schedule",
        )

        # 4. Ingest endorsement for case 1
        end_pdf = build_synthetic_endorsement_pdf()
        doc_end, _ = doc_storage.save_document(
            case_id="case-integ-001",
            filename="Joint_Replacement_Endorsement.pdf",
            content=end_pdf,
            evidence_type="endorsement",
        )

        # 5. Ingest unreadable scan for case 1
        unread_pdf = build_synthetic_unreadable_pdf()
        doc_unread, _ = doc_storage.save_document(
            case_id="case-integ-001",
            filename="Scanned_Corrupted.pdf",
            content=unread_pdf,
            evidence_type="other",
        )

        # 6. Ingest document for case 2 (isolation check)
        doc_case2, _ = doc_storage.save_document(
            case_id="case-integ-002",
            filename="Case_2_Policy.pdf",
            content=policy_pdf,
            evidence_type="policy_wording",
        )

        # 7. Create EvidenceRetrievalService bound to SQLite DB
        retrieval_service = EvidenceRetrievalService(db=db)

        yield {
            "db": db,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "retrieval": retrieval_service,
            "doc_policy": doc_policy,
            "doc_sched": doc_sched,
            "doc_end": doc_end,
            "doc_unread": doc_unread,
            "doc_case2": doc_case2,
        }


def test_retrieval_service_reads_actual_extracted_pdf_pages(integration_env):
    """Verify EvidenceRetrievalService reads actual physical pages extracted by pypdf."""
    retrieval: EvidenceRetrievalService = integration_env["retrieval"]
    doc_policy = integration_env["doc_policy"]

    # Read page 14 of Care_Health_Gold_Policy_Wording.pdf (Degenerative joint disorders / Knee replacement)
    page_14 = retrieval.read_page(
        document_id=doc_policy.document_id,
        version=doc_policy.version,
        page_number=14,
        case_id="case-integ-001",
    )
    assert page_14.page_number == 14
    assert not page_14.is_blank
    assert "waiting period of twenty-four (24) continuous months" in page_14.text.lower()
    assert "total knee replacement" in page_14.text.lower()

    # Read page 7 (blank page in synthetic policy)
    page_7 = retrieval.read_page(
        document_id=doc_policy.document_id,
        version=doc_policy.version,
        page_number=7,
        case_id="case-integ-001",
    )
    assert page_7.page_number == 7
    assert page_7.is_blank is True


def test_retrieval_service_searches_sqlite_extracted_documents(integration_env):
    """Verify search_pages finds matching clauses across extracted documents in SQLite."""
    retrieval: EvidenceRetrievalService = integration_env["retrieval"]

    # Search for knee replacement waiting period (page 14)
    results = retrieval.search_pages(
        case_id="case-integ-001",
        query="knee replacement waiting period",
    )
    assert len(results) > 0
    top = results[0]
    assert top.page_number == 14
    assert "knee replacement" in top.matching_snippet.lower()

    # Search for cataract surgery waiting period (page 11)
    cataract_results = retrieval.search_pages(
        case_id="case-integ-001",
        query="cataract surgery waiting period",
    )
    assert len(cataract_results) > 0
    assert cataract_results[0].page_number == 11


def test_retrieval_service_verifies_real_pdf_citation(integration_env):
    """Verify citation verification against actual extracted text from SQLite."""
    retrieval: EvidenceRetrievalService = integration_env["retrieval"]
    doc_policy = integration_env["doc_policy"]

    # Authentic citation on page 14
    valid_evidence = Evidence(
        document_id=doc_policy.document_id,
        document_version=doc_policy.version,
        page=14,
        quote="Treatment for degenerative joint disorders including total knee replacement is covered subject to a specific waiting period of twenty-four (24) continuous months",
        evidence_type="policy_wording",
    )
    result = retrieval.verify_citation(valid_evidence, case_id="case-integ-001")
    assert result.is_valid is True
    assert "Citation verified" in result.reason

    # Fabricated citation
    fabricated_evidence = Evidence(
        document_id=doc_policy.document_id,
        document_version=doc_policy.version,
        page=14,
        quote="The insurer guarantees 100% cashless approval with zero waiting period.",
        evidence_type="policy_wording",
    )
    fab_result = retrieval.verify_citation(fabricated_evidence, case_id="case-integ-001")
    assert fab_result.is_valid is False
    assert "Fabricated quotation" in fab_result.reason


def test_retrieval_service_enforces_case_isolation_on_sqlite_documents(integration_env):
    """Verify that documents belonging to case 2 cannot be accessed or searched in case 1."""
    retrieval: EvidenceRetrievalService = integration_env["retrieval"]
    doc_case2 = integration_env["doc_case2"]

    # Attempting to read doc_case2 with case-integ-001 must raise CaseOwnershipError
    with pytest.raises(CaseOwnershipError, match="Access denied: Document"):
        retrieval.read_page(
            document_id=doc_case2.document_id,
            version=doc_case2.version,
            page_number=1,
            case_id="case-integ-001",
        )

    # Citation citing doc_case2 under case-integ-001 must fail verification
    cross_evidence = Evidence(
        document_id=doc_case2.document_id,
        document_version=doc_case2.version,
        page=1,
        quote="Care Health Gold Policy",
        evidence_type="policy_wording",
    )
    ver_res = retrieval.verify_citation(cross_evidence, case_id="case-integ-001")
    assert ver_res.is_valid is False
    assert "Wrong-case reference" in ver_res.reason
