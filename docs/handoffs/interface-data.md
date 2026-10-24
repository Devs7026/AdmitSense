Updated: 2026-10-24T12:55:00+05:30
Owner / task: OWNER A / M4-A & Interface side of M4-I (User Follow-up, Activity Display, and Run Status)
Branch / implementation commit or PR: feat/m4-user-followup-and-activity
Delivery state: ready for review (awaiting teammate review and merge authorisation)
Implemented:
1. Concise Tool Activity Event Stream:
   - Added table `tool_activity_events` in SQLite schema (`src/admitsense/storage/database.py`) with indexes `idx_activity_run` and `idx_activity_case`.
   - Enhanced `ReviewRepository` (`src/admitsense/storage/review_repository.py`) with `save_activity_event()` and `list_activity_events()` to persist real tool telemetry.
   - Streamed tool events from `ReviewService.execute_review()` automatically save each event (`search_pages`, `read_page`, `verify_citation`, `lookup_hospital`) to SQLite without inventing events or exposing private model reasoning.
   - Added collapsible "Agent Tool Activity Log" in Streamlit Workspace (`src/admitsense/ui/workspace_view.py`) rendering actual chronological tool calls with step count, tool name, invocation/completed/failed status, arguments, and human-readable action summaries.
2. Honest Run Status, Stop Reason, and Validated Partial Results:
   - Configured honest status reporting in workspace: displays whether review is `complete`, `incomplete`, or `error`.
   - Distinct alert banners for `stopped_reason`:
     - `missing_information`: highlights what information is missing to make progress.
     - `tool_limit_reached`: transparently informs user that tool execution reached the bounded budget limit and shows partial results.
     - `processing_error`: honestly surfaces execution errors with stop details without claiming success.
   - Preserves validated partial findings and checklist items even when review halts prematurely.
3. User Answer Inputs with FactSource Provenance:
   - Interactive follow-up input form in workspace allowing user to answer questions or provide missing case facts:
     - Continuous coverage inception date
     - Policy start date
     - Elapsed policy age (months)
     - Medical procedure name
     - Estimated hospitalization cost
   - Updates `CaseDetails` in SQLite and attaches provenance via `FactSource(source_type="user_provided")` for every field supplied.
   - Automatically marks corresponding checklist items as `"provided_pending_review"`.
4. "I Don't Have This" Handling:
   - Checklist items feature an explicit "⚠️ I Don't Have This" action button.
   - Marks item status as `"user_does_not_have"` with an explanatory resolution note recorded in SQLite and the serialized ReviewPacket.
   - Survives page refresh and application restart.
   - Invariant preserved: marking "I don't have this" retains the relevant question and finding as unresolved; it never infers coverage or synthesizes waivers.
   - Provides an "Undo / Provide Now" button if the user later obtains the document.
5. Explicit Retry / Resume Actions:
   - "🔄 Resume Review (New Run)" action button in header and bottom of workspace.
   - Rerender guard: reviews are only triggered on explicit user button click, preventing duplicate submissions or automatic execution caused by Streamlit widget rerenders.
   - Resuming creates an explicit new run record (`run_id` distinct, `packet_version` incremented) linked to the same case.
   - Prior review runs and packets are retained in SQLite history and accessible via a historical runs drawer in the UI.
6. Tool Budget Enforcement:
   - `ReviewService.execute_review()` bounds tool budget to a maximum of 8 calls (`min(max(1, tool_budget), 8)`).
   - If bounded budget is reached and the review is incomplete, sets `stopped_reason="tool_limit_reached"`.
   - Unexpected runner exceptions produce an honest packet snapshot with `review_status="incomplete"`, `stopped_reason="processing_error"`.
Interfaces changed:
- `src/admitsense/storage/database.py`:
  - Added table `tool_activity_events` (`id`, `run_id`, `case_id`, `step_number`, `tool_name`, `tool_arguments_json`, `status`, `summary`, `error`, `created_at`).
  - Added index `idx_checklist_case` on `checklist_items(case_id)`.
- `src/admitsense/storage/review_repository.py`:
  - Added `save_activity_event(event: ToolActivityEvent, case_id: str) -> None`.
  - Added `list_activity_events(run_id: str | None = None, case_id: str | None = None) -> list[ToolActivityEvent]`.
  - Added `update_checklist_item_status(case_id: str, item_id: str, status: ChecklistStatus, resolution_note: str | None = None) -> None`.
  - Updated `save_review_packet()` to preserve user-provided checklist statuses across incremental runs.
- `src/admitsense/review/service.py`:
  - Enhanced `execute_review(case_id, event_callback, tool_budget, timeout_seconds)` to auto-persist activity events, clamp tool budget to 8, increment `packet_version` relative to `prior_packet`, and catch runner errors honestly.
- `src/admitsense/ui/workspace_view.py`:
  - Added dynamic review button with rerun guard.
  - Added Tool Activity Log accordion displaying SQLite-persisted tool events.
  - Added "I Don't Have This" checklist button and status chip.
  - Added Follow-Up Answer input form recording `FactSource(source_type="user_provided")`.
  - Added Historical Review Runs drawer.
Checks and results:
- `pytest tests/test_m4_followup.py` -> 5/5 passed.
- `pytest` (full test suite) -> 85/85 passed in 5.38s.
- `python tests/verify_m4.py` -> 7/7 checks passed (tool activity persistence, run status and partial results display, user fact answering with provenance, "I don't have this" survival across restart, explicit new run creation retaining history, tool budget capping at <= 8, honest error reporting).
- `python tests/verify_m1.py` -> 5/5 checks passed.
- `python tests/verify_m2.py` -> 8/8 checks passed.
- `python tests/verify_m3.py` -> 8/8 checks passed.
Mocks / limitations / blockers:
- Application-level tool budget is enforced at <= 8 calls in `ReviewService`.
- Backend agent dynamic tool selection and internal tool loop timeout (`M4-B`) are owned by Owner B; `ReviewService` seamlessly supports any runner adhering to `ReviewRunnerProtocol` that streams `ToolActivityEvent`.
Next action for other owner:
- Owner B can implement dynamic tool selection, strict per-call validation, and internal stopping rules (`M4-B`).
- When Owner B executes tool calls, emitting `event_callback(ToolActivityEvent(...))` automatically streams and persists them into the UI and SQLite.
- Complete joint integration `M4-I` by verifying that Owner B's agent obeys tool budget and streaming events under prompt injection and edge cases.
