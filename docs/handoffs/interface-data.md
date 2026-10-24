Updated: 2026-10-24T12:25:00+05:30
Owner / task: OWNER A / M3-A (Interface side of M3-I prepared)
Branch / implementation commit or PR: feat/m3-review-workspace
Delivery state: ready-for-review
Implemented:
- SQLite persistence layer for review outputs in `src/admitsense/storage/review_repository.py`:
  - `save_review_packet(packet)`: atomic transaction saving packet metadata, raw serialized JSON snapshot (for future M6 deterministic exports), findings, revisions, and checklist items.
  - `get_latest_review_packet(case_id)`: reloads the most recent validated `ReviewPacket` snapshot.
  - `list_review_packets(case_id)`: historical audit list of all generated packets for a case.
  - `get_finding_history(case_id, finding_id)`: audit trail of revisions for a given topic/finding.
- SQLite schema additions in `src/admitsense/storage/database.py`:
  - `review_packets`: packet_id, case_id, packet_version, run_id, review_status, authorization_status, stopped_reason, stop_details, tool_steps_used, packet_json, created_at.
  - `findings`: finding_id, packet_id, revision, topic, status, conclusion, next_action, limitations, evidence_json.
  - `revisions`: revision_id, packet_id, finding_id, old_finding_revision, new_finding_revision, old_status, new_status, old_conclusion, new_conclusion, trigger_type, reason, affected_topics, triggering_evidence_json.
  - `checklist_items`: item_id, packet_id, requested_information, why_it_matters, suggested_source, status, resolution_note.
- Review service & adapter in `src/admitsense/review/service.py`:
  - `ReviewService`: loads case facts, coordinates review execution with the runner, and commits snapshot via `ReviewRepository`.
  - `FixtureReviewRunner`: clearly labelled development fixture behind agreed `ReviewRunnerProtocol`. Evaluates actual case facts against extracted SQLite document text using `SqliteEvidenceRetrieval` or `EvidenceRetrievalService`. Evaluates 24-month waiting period on p14 against 18-month history, generating an unresolved finding, physical page 14 citation, and checklist item. When endorsement schedule is ingested, updates finding to `supported` with citation and records a `Revision` entry.
- Streamlit Case Workspace in `src/admitsense/ui/workspace_view.py`:
  - "🔍 Review Available Documents" action trigger button in header with processing spinner.
  - Persisted Review Packet summary bar: packet ID, version, review status badge, run ID, tool steps used (capped at 8), and stop reason.
  - Separate Insurer Authorisation banner defaulting to `"not verified"` (strict product invariant).
  - Findings accordion cards displaying status (`SUPPORTED`, `UNRESOLVED`, `CONFLICT`, `NEEDS HUMAN REVIEW`), conclusion, limitations, next action, and clickable physical page citation buttons.
  - Citation navigation to Evidence Viewer: clicking a citation sets session state and opens the exact physical page with the quoted text highlighted in `<mark>` yellow.
  - Missing-evidence checklist showing requested information, why it matters, suggested source, and quick link to document upload tab.
  - Explicit states for incomplete reviews, processing spinners, and error alerts.
Interfaces changed:
- Added module `src/admitsense/storage/review_repository.py` (`ReviewRepository`).
- Added module `src/admitsense/review/` (`service.py` exporting `ReviewService`, `FixtureReviewRunner`).
- Exported `ReviewRepository` in `src/admitsense/storage/__init__.py`.
- Exported `ReviewService` and `FixtureReviewRunner` in `src/admitsense/review/__init__.py`.
- Updated `src/admitsense/app.py` to initialize `ReviewRepository` and `ReviewService` in session state.
- Updated `src/admitsense/ui/workspace_view.py` to wire `review_repo` and `review_service`.
Checks and results:
- `pytest tests/test_review_repository.py` -> 3/3 passed.
- `pytest` (full test suite) -> 71/71 passed.
- `python tests/verify_m3.py` -> 7/7 checks passed (partial case setup, base policy ingestion, review execution, waiting period finding with physical p14 citation, missing-evidence checklist, persistence/reload across restart, endorsement re-review progression with revision tracking, historical packet listing).
- `python tests/verify_m2.py` -> 8/8 checks passed.
- `python tests/verify_m1.py` -> 5/5 checks passed.
Mocks / limitations / blockers:
- `FixtureReviewRunner` is currently used as an interim development adapter while Owner B completes live LLM review logic (`M3-B`). It is clearly labelled in the UI and stop_details.
Next action for other owner:
- Owner B can implement the live review runner (`M3-B`) adhering to `ReviewRunnerProtocol.run_review(case, retrieval, prior_packet, ...)`.
- For `M3-I`, replace `FixtureReviewRunner` in `ReviewService` with Owner B's live runner and test the upload-to-review journey end-to-end.
