Updated: 2026-10-24T11:55:00+05:30
Owner / task: OWNER A / M2-A
Branch / implementation commit or PR: main (commit 1499041)
Delivery state: merged
Implemented:
- PDF upload validation & configuration in src/admitsense/documents/models.py:
  - UploadValidationConfig: 10 MB maximum file size, 50 maximum physical pages, .pdf extension check.
  - ExtractedPage and DocumentRecord models conforming to docs/CONTRACTS.md.
- pypdf extraction engine in src/admitsense/documents/extractor.py:
  - Preserves physical 1-based page positions starting at page 1.
  - Retains blank pages (is_blank=True, text="") so downstream citations do not drift.
  - Normalizes whitespace across extracted text.
  - Classifies explicit extraction statuses: extracted, partial, unreadable, error.
  - Enforces invariant: unreadable documents/pages never imply absence of policy exclusions.
- Document persistence & versioning in src/admitsense/documents/storage.py:
  - File binary storage under data/documents/<case_id>/<doc_id>/<version>_<filename>.
  - Duplicate-upload handling via SHA-256: identical files return existing record (is_duplicate=True) without creating redundant versions.
  - Immutable version increment: re-uploading modified files under same filename increments version (v1 -> v2) while leaving older versions untouched.
  - Full relational persistence in SQLite tables documents and document_pages.
- Evidence retrieval & citation verification in src/admitsense/documents/retrieval.py:
  - SqliteEvidenceRetrieval implementing get_page_text, verify_citation, and search_pages with multi-word matching.
- Synthetic demonstration fixtures in src/admitsense/documents/synthetic.py:
  - Care_Health_Gold_Policy_Wording.pdf: 15 pages; page 7 blank; page 14 contains Section 4.2(b) 24-month waiting period clause.
  - Policy_Renewal_Schedule.pdf: 2 pages; specifies 18 months continuous coverage.
  - Joint_Replacement_Endorsement.pdf: 1 page; modifies waiting period to 12 months.
  - Apex_Hospital_Estimate.pdf: 2 pages; knee replacement hospital estimate.
  - Scanned_Receipt_Unreadable.pdf: 2 blank pages testing explicit unreadable status.
  - hospitals_synthetic_v2026.json: dated (2026-10-01), versioned (v2026.1) synthetic hospital reference data.
- Streamlit Document & Evidence Viewer in src/admitsense/ui/workspace_view.py:
  - Document upload section with evidence type selector.
  - One-click synthetic fixture quick loaders.
  - Document records list showing status badges (EXTRACTED, PARTIAL, UNREADABLE, ERROR) and SHA-256 hashes.
  - Interactive physical page viewer with blank page warning and live citation verifier.
Interfaces changed:
- Added module src/admitsense/documents/ with models.py, extractor.py, storage.py, retrieval.py, synthetic.py.
- SQLite schema in src/admitsense/storage/database.py expanded with documents and document_pages tables.
- SqliteEvidenceRetrieval ready for Owner B retrieval tools integration.
Checks and results:
- pytest tests/test_pdf_ingestion.py -> 7/7 passed.
- pytest (full test suite) -> 36/36 passed.
- python tests/verify_m2.py -> 8/8 acceptance checks passed (readable extraction, unreadable status, upload limits, duplicate handling, immutable versioning, cross-case isolation, citation verification, synthetic documents).
Mocks / limitations / blockers:
- Agent retrieval tools (M2-B) will be authored by Owner B. Owner A supplies SqliteEvidenceRetrieval as the underlying engine.
Next action for other owner:
- Owner B can start Milestone M2-B: build page search/read tools and citation checks against SqliteEvidenceRetrieval.
- Verify retrieval tools against tests/fixtures/synthetic/Care_Health_Gold_Policy_Wording.pdf (page 14 waiting period).
