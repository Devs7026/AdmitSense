Updated: 2026-10-24T11:47:00+05:30
Owner / task: OWNER B / M2-B
Branch / implementation commit or PR: dev-agent (local working tree)
Delivery state: local
Implemented:
- Built case-scoped evidence retrieval and citation verification service in src/admitsense/agent/retrieval.py (EvidenceRetrievalService):
  - search_pages(case_id, query, document_id, max_results): case-scoped term/phrase search with term coverage and stopword weighting, returning PageSearchResult supporting both tuple unpacking and attribute access.
  - read_page(document_id, version, page_number, case_id) and get_page_text(...): physical 1-based page reading enforcing document existence, exact version, bounds (1 <= page <= total_pages), and non-unreadable extraction status.
  - verify_citation(evidence, case_id): citation verification enforcing physical page numbers > 0, case ownership, version match, page bounds, and quotation matching with documented whitespace normalization.
  - Explicit failures with descriptive reasons for fabricated quotes, wrong-case references (CaseOwnershipError), version mismatches (VersionMismatchError), page out-of-bounds (PageOutOfBoundsError), and unreadable/error extraction states (DocumentUnreadableError).
  - Whitespace normalization (normalize_whitespace): collapses multi-space/newline/tab sequences, standardizes smart quotes, dashes, and non-breaking spaces.
- Authored labelled synthetic document fixtures in tests/fixtures/synthetic_documents.py:
  - Base policy wording (doc-base-policy-star, v1, 18 physical pages with waiting period and exclusion clauses).
  - Policy schedule (doc-schedule-9941, v1, 2 physical pages with member name and continuous coverage dates).
  - Endorsement (doc-endorsement-2026-v1, v1, 1 page with post-dated effective date).
  - Maternity Rider (doc-maternity-rider-v1, v1, 2 pages with 9-month waiting period).
  - Unreadable document (doc-unreadable-scan-v1, v1, 3 pages, extraction_status="unreadable").
  - Other-case document (doc-other-case-policy, case_id="case-other-999") to test cross-case isolation.
- Independently specified ground-truth expected outcomes in tests/fixtures/expected_outcomes.py.
- Authored test suite in tests/test_evidence_retrieval.py containing 28 tests covering search, bounds, case isolation, quotation matching, fabricated quotes, unreadable status, and evaluation against expected outcomes.
Interfaces changed:
- Implemented EvidenceRetrievalService in src/admitsense/agent/retrieval.py conforming to EvidenceRetrieval protocol in docs/CONTRACTS.md.
- Added models: ExtractedPage, DocumentRecord, PageSearchResult, CitationVerificationResult.
Checks and results:
- pytest -v tests/test_evidence_retrieval.py -> 28 passed in 0.46s.
- pytest -v tests/ -> 57 passed in 0.71s (28 retrieval, 15 case validation, 10 sample fixtures, 4 case repo).
- python tests/verify_m1.py -> 5/5 verification checks passed.
Mocks / limitations / blockers:
- Retrieval service is currently tested against labelled synthetic document fixtures (tests/fixtures/synthetic_documents.py) while Owner A's PDF uploader and pypdf extraction (M2-A) are pending.
- Integration check M2-I will verify EvidenceRetrievalService against Owner A's actual SQLite-persisted extracted documents.
Next action for other owner:
- Owner A to implement M2-A (PDF upload limits/type checks, immutable versions, SHA-256 duplicate handling, pypdf extraction retaining 1-based page positions and blank pages, and document/page viewer).
- In M2-I, connect extracted DocumentRecord objects from SQLite into EvidenceRetrievalService(documents) to link retrieval results to the UI evidence viewer.
