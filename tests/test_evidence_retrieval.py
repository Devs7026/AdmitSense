"""Tests for Milestone M2-B: Evidence retrieval, case scoping, and citation verification."""

import pytest

from admitsense.agent.retrieval import (
    CaseOwnershipError,
    CitationVerificationResult,
    DocumentNotFoundError,
    DocumentRecord,
    DocumentUnreadableError,
    EvidenceRetrievalService,
    ExtractedPage,
    PageOutOfBoundsError,
    PageSearchResult,
    VersionMismatchError,
    normalize_whitespace,
)
from admitsense.schemas import Evidence
from tests.fixtures.expected_outcomes import (
    EXPECTED_CATARACT_OUTCOME,
    EXPECTED_HERNIA_OUTCOME,
    EXPECTED_JOINT_REPLACEMENT_BASE_OUTCOME,
    EXPECTED_JOINT_REPLACEMENT_ENDORSEMENT_OUTCOME,
    EXPECTED_MATERNITY_RIDER_OUTCOME,
    FABRICATED_APPROVAL_EVIDENCE,
    VALID_CATARACT_EVIDENCE,
    VALID_HERNIA_EVIDENCE,
    VALID_SCHEDULE_EVIDENCE,
    WRONG_CASE_EVIDENCE,
)
from tests.fixtures.synthetic_documents import (
    ALL_SYNTHETIC_DOCUMENTS,
    OTHER_CASE_ID,
    SYNTHETIC_BASE_POLICY_DOC,
    SYNTHETIC_CASE_ID,
    SYNTHETIC_ENDORSEMENT_DOC,
    SYNTHETIC_MATERNITY_RIDER_DOC,
    SYNTHETIC_OTHER_CASE_DOC,
    SYNTHETIC_POLICY_SCHEDULE_DOC,
    SYNTHETIC_UNREADABLE_DOC,
)


@pytest.fixture
def retrieval_service() -> EvidenceRetrievalService:
    """Fixture providing retrieval service populated with synthetic test documents."""
    return EvidenceRetrievalService(ALL_SYNTHETIC_DOCUMENTS)


class TestWhitespaceNormalization:
    """Verifies documented whitespace normalization rules."""

    def test_collapses_whitespace_sequences(self):
        raw = "Clause 4.3:\n\n   Cataract surgery    is covered\t\tafter 24 months."
        normalized = normalize_whitespace(raw)
        assert normalized == "Clause 4.3: Cataract surgery is covered after 24 months."

    def test_normalizes_typographical_quotes_and_dashes(self):
        raw = "“Section 4.2” – ‘Hernia, Hydrocele, and Piles’"
        normalized = normalize_whitespace(raw)
        assert normalized == '"Section 4.2" - \'Hernia, Hydrocele, and Piles\''

    def test_handles_non_breaking_spaces(self):
        raw = "Waiting\u00a0period\u00a0of 24\u00a0months"
        normalized = normalize_whitespace(raw)
        assert normalized == "Waiting period of 24 months"


class TestPageReadingAndBounds:
    """Verifies page reading, bounds checks, and document existence."""

    def test_read_valid_page(self, retrieval_service: EvidenceRetrievalService):
        page = retrieval_service.read_page(
            document_id="doc-base-policy-star",
            version="v1",
            page_number=14,
            case_id=SYNTHETIC_CASE_ID,
        )
        assert page.page_number == 14
        assert "Clause 4.3" in page.text
        assert page.character_count > 0
        assert not page.is_blank

    def test_page_number_zero_or_negative_raises_error(self, retrieval_service: EvidenceRetrievalService):
        with pytest.raises(PageOutOfBoundsError, match="PDF pages are 1-based"):
            retrieval_service.read_page("doc-base-policy-star", "v1", 0, SYNTHETIC_CASE_ID)

        with pytest.raises(PageOutOfBoundsError, match="PDF pages are 1-based"):
            retrieval_service.read_page("doc-base-policy-star", "v1", -2, SYNTHETIC_CASE_ID)

    def test_page_number_exceeding_total_pages_raises_error(self, retrieval_service: EvidenceRetrievalService):
        # Base policy has 18 pages; page 19 must fail
        with pytest.raises(PageOutOfBoundsError, match="out of bounds"):
            retrieval_service.read_page("doc-base-policy-star", "v1", 19, SYNTHETIC_CASE_ID)

    def test_nonexistent_document_raises_error(self, retrieval_service: EvidenceRetrievalService):
        with pytest.raises(DocumentNotFoundError, match="not found"):
            retrieval_service.read_page("doc-ghost-policy", "v1", 1, SYNTHETIC_CASE_ID)

    def test_version_mismatch_raises_error(self, retrieval_service: EvidenceRetrievalService):
        # doc-base-policy-star is v1; requesting v2 must fail
        with pytest.raises(VersionMismatchError, match="Version mismatch"):
            retrieval_service.read_page("doc-base-policy-star", "v2", 1, SYNTHETIC_CASE_ID)

    def test_unreadable_document_raises_error(self, retrieval_service: EvidenceRetrievalService):
        with pytest.raises(DocumentUnreadableError, match="extraction status is 'unreadable'"):
            retrieval_service.read_page("doc-unreadable-scan-v1", "v1", 1, SYNTHETIC_CASE_ID)

    def test_get_page_text_returns_none_on_error(self, retrieval_service: EvidenceRetrievalService):
        # get_page_text is safe and returns None on bounds violation or unreadable doc
        assert retrieval_service.get_page_text("doc-base-policy-star", "v1", 99, SYNTHETIC_CASE_ID) is None
        assert retrieval_service.get_page_text("doc-unreadable-scan-v1", "v1", 1, SYNTHETIC_CASE_ID) is None


class TestCaseScopedRetrieval:
    """Verifies that retrieval strictly isolates documents by case_id."""

    def test_read_page_from_other_case_raises_ownership_error(
        self, retrieval_service: EvidenceRetrievalService
    ):
        with pytest.raises(CaseOwnershipError, match="Access denied: Document 'doc-other-case-policy' belongs to case"):
            retrieval_service.read_page(
                document_id="doc-other-case-policy",
                version="v1",
                page_number=1,
                case_id=SYNTHETIC_CASE_ID,  # Wrong case!
            )

    def test_search_strictly_excludes_documents_from_other_cases(
        self, retrieval_service: EvidenceRetrievalService
    ):
        # Search for text that exists in doc-other-case-policy ("Confidential diagnostic reports")
        results = retrieval_service.search_pages(
            case_id=SYNTHETIC_CASE_ID,
            query="Confidential diagnostic reports",
        )
        # Must return 0 results because that document belongs to OTHER_CASE_ID
        assert len(results) == 0

        # When searching in the correct case, it is found
        other_results = retrieval_service.search_pages(
            case_id=OTHER_CASE_ID,
            query="Confidential diagnostic reports",
        )
        assert len(other_results) == 1
        assert other_results[0].document_id == "doc-other-case-policy"


class TestPageSearch:
    """Verifies search functionality and snippet extraction."""

    def test_search_finds_cataract_clause_on_expected_page(
        self, retrieval_service: EvidenceRetrievalService
    ):
        results = retrieval_service.search_pages(
            case_id=SYNTHETIC_CASE_ID,
            query="cataract surgery waiting period",
        )
        assert len(results) > 0
        top = results[0]
        assert top.document_id == "doc-base-policy-star"
        assert top.version == "v1"
        assert top.page_number in (12, 14)
        assert "cataract" in top.matching_snippet.lower()

    def test_search_finds_hernia_clause_on_page_8(
        self, retrieval_service: EvidenceRetrievalService
    ):
        results = retrieval_service.search_pages(
            case_id=SYNTHETIC_CASE_ID,
            query="hernia hydrocele piles waiting period",
        )
        assert len(results) > 0
        top = results[0]
        assert top.document_id == "doc-base-policy-star"
        assert top.page_number == 8
        assert "hernia" in top.matching_snippet.lower()

    def test_search_result_supports_tuple_unpacking(
        self, retrieval_service: EvidenceRetrievalService
    ):
        results = retrieval_service.search_pages(
            case_id=SYNTHETIC_CASE_ID,
            query="maternity rider schedule",
        )
        assert len(results) > 0
        doc_id, version, page_number, snippet = results[0]
        assert doc_id == "doc-maternity-rider-v1"
        assert version == "v1"
        assert page_number in (1, 2)
        assert isinstance(snippet, str)

    def test_unreadable_documents_are_excluded_from_search(
        self, retrieval_service: EvidenceRetrievalService
    ):
        # Even if a query matches error messages or metadata, unreadable docs are skipped
        results = retrieval_service.search_pages(
            case_id=SYNTHETIC_CASE_ID,
            query="scanned corrupted record",
        )
        doc_ids = {r.document_id for r in results}
        assert "doc-unreadable-scan-v1" not in doc_ids


class TestCitationVerification:
    """Verifies citation verification against authentic and fabricated quotations."""

    def test_valid_cataract_citation_passes(self, retrieval_service: EvidenceRetrievalService):
        result = retrieval_service.verify_citation(VALID_CATARACT_EVIDENCE, SYNTHETIC_CASE_ID)
        assert result.is_valid is True
        assert "Citation verified" in result.reason
        assert result.page_number == 14

    def test_valid_schedule_citation_passes(self, retrieval_service: EvidenceRetrievalService):
        result = retrieval_service.verify_citation(VALID_SCHEDULE_EVIDENCE, SYNTHETIC_CASE_ID)
        assert result.is_valid is True
        assert result.page_number == 1

    def test_citation_with_different_whitespace_passes(self, retrieval_service: EvidenceRetrievalService):
        evidence_with_newlines = Evidence(
            document_id="doc-base-policy-star",
            document_version="v1",
            page=14,
            quote="Clause 4.3 (Specific Ailment Waiting Period):\nExpenses related to the treatment of Cataract\nare covered after twenty-four (24) months of continuous coverage.",
            evidence_type="policy_wording",
        )
        result = retrieval_service.verify_citation(evidence_with_newlines, SYNTHETIC_CASE_ID)
        assert result.is_valid is True

    def test_fabricated_quote_fails_verification(self, retrieval_service: EvidenceRetrievalService):
        result = retrieval_service.verify_citation(FABRICATED_APPROVAL_EVIDENCE, SYNTHETIC_CASE_ID)
        assert result.is_valid is False
        assert "Fabricated quotation" in result.reason

    def test_wrong_case_citation_fails_verification(self, retrieval_service: EvidenceRetrievalService):
        result = retrieval_service.verify_citation(WRONG_CASE_EVIDENCE, SYNTHETIC_CASE_ID)
        assert result.is_valid is False
        assert "Wrong-case reference" in result.reason

    def test_wrong_version_citation_fails_verification(self, retrieval_service: EvidenceRetrievalService):
        evidence_wrong_version = Evidence(
            document_id="doc-base-policy-star",
            document_version="v2",  # Actual is v1
            page=14,
            quote=VALID_CATARACT_EVIDENCE.quote,
            evidence_type="policy_wording",
        )
        result = retrieval_service.verify_citation(evidence_wrong_version, SYNTHETIC_CASE_ID)
        assert result.is_valid is False
        assert "Version mismatch" in result.reason

    def test_out_of_bounds_page_citation_fails_verification(
        self, retrieval_service: EvidenceRetrievalService
    ):
        evidence_out_of_bounds = Evidence(
            document_id="doc-base-policy-star",
            document_version="v1",
            page=25,  # Document has 18 pages
            quote="Non-existent page quote",
            evidence_type="policy_wording",
        )
        result = retrieval_service.verify_citation(evidence_out_of_bounds, SYNTHETIC_CASE_ID)
        assert result.is_valid is False
        assert "out of bounds" in result.reason

    def test_unreadable_document_citation_fails_verification(
        self, retrieval_service: EvidenceRetrievalService
    ):
        evidence_unreadable = Evidence(
            document_id="doc-unreadable-scan-v1",
            document_version="v1",
            page=1,
            quote="Any quote from unreadable document",
            evidence_type="other",
        )
        result = retrieval_service.verify_citation(evidence_unreadable, SYNTHETIC_CASE_ID)
        assert result.is_valid is False
        assert "unreadable" in result.reason
        # Invariant: Unreadable documents never imply absence of policy exclusions
        assert "Unreadable documents cannot support evidence citations" in result.reason


class TestExpectedOutcomesEvaluation:
    """Verifies that retrieval tools meet all independently specified expected outcomes."""

    def test_expected_cataract_outcome(self, retrieval_service: EvidenceRetrievalService):
        spec = EXPECTED_CATARACT_OUTCOME
        results = retrieval_service.search_pages(SYNTHETIC_CASE_ID, spec.query)
        assert len(results) > 0
        top = results[0]
        assert top.document_id == spec.expected_document_id
        assert top.page_number in (12, spec.expected_page_number)

        # Verify citation against expected page
        evidence = Evidence(
            document_id=spec.expected_document_id,
            document_version=spec.expected_version,
            page=spec.expected_page_number,
            quote=spec.expected_quote,
            evidence_type="policy_wording",
        )
        ver_result = retrieval_service.verify_citation(evidence, SYNTHETIC_CASE_ID)
        assert ver_result.is_valid is True

    def test_expected_hernia_outcome(self, retrieval_service: EvidenceRetrievalService):
        spec = EXPECTED_HERNIA_OUTCOME
        results = retrieval_service.search_pages(SYNTHETIC_CASE_ID, spec.query)
        assert len(results) > 0
        assert results[0].page_number == spec.expected_page_number

        evidence = Evidence(
            document_id=spec.expected_document_id,
            document_version=spec.expected_version,
            page=spec.expected_page_number,
            quote=spec.expected_quote,
            evidence_type="policy_wording",
        )
        ver_result = retrieval_service.verify_citation(evidence, SYNTHETIC_CASE_ID)
        assert ver_result.is_valid is True

    def test_expected_joint_replacement_conflict(self, retrieval_service: EvidenceRetrievalService):
        base_spec = EXPECTED_JOINT_REPLACEMENT_BASE_OUTCOME
        end_spec = EXPECTED_JOINT_REPLACEMENT_ENDORSEMENT_OUTCOME

        # Both documents must be retrievable in the case
        base_page = retrieval_service.read_page(
            base_spec.expected_document_id, base_spec.expected_version, base_spec.expected_page_number, SYNTHETIC_CASE_ID
        )
        assert "forty-eight (48) consecutive months" in base_page.text

        end_page = retrieval_service.read_page(
            end_spec.expected_document_id, end_spec.expected_version, end_spec.expected_page_number, SYNTHETIC_CASE_ID
        )
        assert "twenty-four (24) months" in end_page.text

        # Verify both citations pass independently
        base_evidence = Evidence(
            document_id=base_spec.expected_document_id,
            document_version=base_spec.expected_version,
            page=base_spec.expected_page_number,
            quote=base_spec.expected_quote,
            evidence_type="policy_wording",
        )
        assert retrieval_service.verify_citation(base_evidence, SYNTHETIC_CASE_ID).is_valid is True

        end_evidence = Evidence(
            document_id=end_spec.expected_document_id,
            document_version=end_spec.expected_version,
            page=end_spec.expected_page_number,
            quote=end_spec.expected_quote,
            evidence_type="endorsement",
        )
        assert retrieval_service.verify_citation(end_evidence, SYNTHETIC_CASE_ID).is_valid is True

    def test_expected_maternity_rider_outcome(self, retrieval_service: EvidenceRetrievalService):
        spec = EXPECTED_MATERNITY_RIDER_OUTCOME
        evidence = Evidence(
            document_id=spec.expected_document_id,
            document_version=spec.expected_version,
            page=spec.expected_page_number,
            quote=spec.expected_quote,
            evidence_type="endorsement",
        )
        ver_result = retrieval_service.verify_citation(evidence, SYNTHETIC_CASE_ID)
        assert ver_result.is_valid is True
        assert ver_result.page_number == 2
