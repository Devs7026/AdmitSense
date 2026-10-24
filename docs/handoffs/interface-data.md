Updated: 2026-10-24T14:10:00+05:30
Owner / task: OWNER A / M5-A & Interface/Storage side of M5-I (Evidence Change Replay & Immutable Snapshots)
Branch / implementation commit or PR: feat/m5-evidence-replay-and-diff
Delivery state: ready for review (awaiting teammate review and merge authorisation)
Implemented:
1. Replay Delta Computation (`src/admitsense/review/replay.py`):
   - Implemented `compute_evidence_replay(prior_packet, new_findings, trigger_type, triggering_evidence, changed_case_facts, reason)` matching agreed CONTRACTS.md Section 3.5.
   - Categorizes findings into three clear sets:
     - Changed findings: increments `Finding.revision` by exactly 1 (`old_revision + 1`) and creates a traceable `Revision` audit record.
     - Unchanged findings: retains `Finding.revision` at `old_revision` and emits 0 new revisions.
     - Newly introduced findings: starts at `Finding.revision = 1` with 0 prior revisions.
   - Enforces trigger integrity: `trigger_type="new_document"` requires non-empty `triggering_evidence`; `trigger_type in {"user_correction", "case_details_changed"}` requires `changed_case_facts`.
2. Atomic Storage & Historical Finding Snapshots (`src/admitsense/storage/review_repository.py`):
   - `save_review_packet(packet, expected_prior_packet_version=None)`:
     - Atomically commits `review_packets`, `findings`, `revisions`, and `checklist_items` in a single SQLite transaction.
     - Stale review protection: checks `expected_prior_packet_version` against current database state. If newer reviews were committed concurrently, raises `StaleReviewError` and rolls back without mutating.
     - Failed saves rollback completely, leaving previous review intact.
   - `get_finding_snapshot(case_id, finding_id, revision)`: retrieves the exact historical finding record and citations as it existed at a past revision.
   - `get_finding_history(case_id, finding_id)` and `list_all_revisions(case_id)`: retrieves chronological audit trails grouped by `revision_id` to prevent duplicate carried-forward logs.
3. Review Service Integration (`src/admitsense/review/service.py`):
   - Tracks `expected_prior_version` before analysis and validates it upon save.
   - Enhanced `FixtureReviewRunner` to demonstrate M5 replay progression: amends waiting period finding from 24 to 12 months when `Joint_Replacement_Endorsement.pdf` is uploaded, recording triggering endorsement evidence on p.1, while duplicate runs without new evidence emit 0 duplicate revisions.
4. Evidence Change Replay Interface (`src/admitsense/ui/workspace_view.py`):
   - Built full `tab_replay` ("🔄 Evidence Change Replay"):
     - Packet version selector to inspect past review revisions.
     - Changed Findings: two-column before-and-after cards displaying Previous Assessment (Rev X) vs Updated Assessment (Rev X+1), reason for change, triggering evidence citations, and updated next action.
     - Previous Evidence Viewer: collapsible drawer showing older citations with clickable buttons jumping to earlier document versions/pages in the Evidence Viewer.
     - Unchanged Findings section: clearly groups findings that remained unaltered by the latest evidence.
     - Newly Introduced Findings section: highlights findings introduced for the first time.
     - Current checklist and updated next action banner preserved.
     - Separate insurer authorisation banner strictly maintained defaulting to `"not verified"`.
     - Supports live review packets as well as development fixture preview (`revised_finding` scenario).
Interfaces changed:
- Added module `src/admitsense/review/replay.py` exporting `compute_evidence_replay`.
- Exported `compute_evidence_replay` in `src/admitsense/review/__init__.py`.
- Added `StaleReviewError` in `src/admitsense/storage/review_repository.py` and exported in `src/admitsense/storage/__init__.py`.
- Added `ReviewRepository.get_finding_snapshot(case_id, finding_id, revision) -> Finding | None`.
- Added `ReviewRepository.list_all_revisions(case_id) -> list[Revision]`.
- Updated `ReviewRepository.save_review_packet(packet, expected_prior_packet_version=None)`.
- Updated `ReviewService.execute_review` to guard against stale concurrent packet overwrites.
- Recorded agreed M5 interfaces in `docs/CONTRACTS.md` (Sections 2.5 and 3.5).
Checks and results:
- `pytest tests/test_m5_replay.py` -> 5/5 passed in 1.23s.
- `python tests/verify_m5.py` -> 9/9 checks passed:
  - Base policy ingestion & initial unresolved finding at rev 1.
  - Endorsement ingestion without replacing older base policy v1.
  - Reassessment revises finding (rev 1 -> rev 2) with endorsement citation on p.1.
  - Duplicate uploads and re-reviews emit 0 duplicate revisions.
  - Historical snapshots at rev 1 and rev 2 both accessible with their respective evidence.
  - Application restart preserves full replay audit history.
  - StaleReviewError rejects attempts to overwrite newer review states.
  - Transactional rollback on failed save leaves previous review intact.
  - Authorisation invariant strictly remains 'not verified'.
- `pytest` (full test suite) -> 99/99 passed in 10.88s.
- Regression verification scripts: `verify_m1.py`, `verify_m2.py`, `verify_m3.py`, `verify_m4.py` -> all passed.
Mocks / limitations / blockers:
- Owner A interface & storage side is complete without mocks.
- `FixtureReviewRunner` provides clearly labelled interim fixture behaviour while Owner B implements live applicability and reassessment logic (`M5-B`).
Next action for other owner (Owner B):
- Implement M5-B in `src/admitsense/agent/review.py`:
  - Applicability checks (effective dates, policy IDs, member match) on uploaded endorsements.
  - Use `compute_evidence_replay` or emit `Revision` entries linking old/new finding revisions.
  - Reassess waiting periods when endorsements apply.
  - When integrated, `ReviewService` and the Replay UI will automatically persist and render Owner B's live revisions.
