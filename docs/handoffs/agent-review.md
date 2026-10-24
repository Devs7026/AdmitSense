Updated: 2026-10-24T12:05:00+05:30
Owner / task: OWNER B / M2-B & M2-I
Branch / implementation commit or PR: dev-agent / main
Delivery state: integrated
Implemented:
- Built case-scoped evidence retrieval and citation verification service in `src/admitsense/agent/retrieval.py` (`EvidenceRetrievalService`):
  - `search_pages(case_id, query, document_id, max_results)`: case-scoped term/phrase search with term coverage and stopword weighting, returning `PageSearchResult` supporting both tuple unpacking and attribute access. Supports loading pages from in-memory objects or directly querying the SQLite database (`documents` and `document_pages` tables).
  - `read_page(document_id, version, page_number, case_id)` and `get_page_text(...)`: physical 1-based page reading enforcing document existence, exact version, bounds (`1 <= page <= total_pages`), and non-unreadable extraction status.
  - `verify_citation(evidence, case_id)`: citation verification enforcing physical page numbers > 0, case ownership, version match, page bounds, and quotation matching with documented whitespace normalization.
  - Explicit failures with descriptive reasons for fabricated quotes, wrong-case references (`CaseOwnershipError`), version mismatches (`VersionMismatchError`), page out-of-bounds (`PageOutOfBoundsError`), and unreadable/error extraction states (`DocumentUnreadableError`).
  - Whitespace normalization (`normalize_whitespace`): collapses multi-space/newline/tab sequences, standardizes smart quotes, dashes, and non-breaking spaces.
- Unified data models: `src/admitsense/agent/retrieval.py` imports `DocumentRecord`, `ExtractedPage`, and `ExtractionStatus` directly from `admitsense.documents.models`.
- Authored labelled synthetic document fixtures in `tests/fixtures/synthetic_documents.py`:
  - Base policy wording (`doc-base-policy-star`, v1, 18 physical pages with waiting period and exclusion clauses).
  - Policy schedule (`doc-schedule-9941`, v1, 2 physical pages with member name and continuous coverage dates).
  - Endorsement (`doc-endorsement-2026-v1`, v1, 1 page with post-dated effective date).
  - Maternity Rider (`doc-maternity-rider-v1`, v1, 2 pages with 9-month waiting period).
  - Unreadable document (`doc-unreadable-scan-v1`, v1, 3 pages, extraction_status="unreadable").
  - Other-case document (`doc-other-case-policy`, `case_id="case-other-999"`) to test cross-case isolation.
- Independently specified ground-truth expected outcomes in `tests/fixtures/expected_outcomes.py`.
- Authored unit test suite in `tests/test_evidence_retrieval.py` containing 28 tests covering search, bounds, case isolation, quotation matching, fabricated quotes, unreadable status, and evaluation against expected outcomes.
- Authored integration test suite in `tests/test_m2_integration.py` containing 4 integration tests verifying real `pypdf`-extracted documents from Owner A's synthetic generator saved in SQLite, testing search, physical page reading, case isolation, citation verification, and fabricated quote rejection.
Interfaces changed:
- Implemented `EvidenceRetrievalService` in `src/admitsense/agent/retrieval.py` conforming to `EvidenceRetrieval` protocol in `docs/CONTRACTS.md`.
- Added models: `PageSearchResult`, `CitationVerificationResult`. Reused shared `DocumentRecord`, `ExtractedPage`, `ExtractionStatus` from `admitsense.documents.models`.
Checks and results:
- `pytest -v tests/` -> 61 passed in 1.15s (28 retrieval, 4 integration, 15 case validation, 10 sample fixtures, 4 case repo).
- `python tests/verify_m2.py` -> 8/8 verification checks passed.
- `python tests/verify_m1.py` -> 5/5 verification checks passed.
Mocks / limitations / blockers:
- None. Retrieval service is fully integrated with Owner A's SQLite document and page storage.
Next action for other owner:
- Owner A and Owner B ready for Milestone M3 (Initial Waiting-Period Review, findings generation, and UI review actions).
