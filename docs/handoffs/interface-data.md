Updated: 2026-10-24T16:32:00+05:30
Owner / task: OWNER A / M7-A & M7-I (End-to-End User Journey Verification, Documentation, and Demonstration Runbook)
Branch / implementation commit or PR: main (feat/m7-end-to-end-verification)
Delivery state: merged
Implemented:
1. Complete 10-Step Caregiver User Journey Verification (`tests/test_m7_journey.py` & `tests/verify_m7.py`):
   - Step 1: Case creation with partial/available facts (preserving None for unknowns, provenance=user_provided).
   - Step 2: Ingesting synthetic policy wording (`Care_Health_Gold_Policy_Wording.pdf`, 15 pages, blank page 7 preserved) and renewal schedule (`Policy_Renewal_Schedule.pdf`, 2 pages).
   - Step 3: Starting real bounded agent review run (strictly <= 8 tool calls, honest status='incomplete', authorization='not verified').
   - Step 4: Inspecting findings and verifying exact citations (physical 1-based page 14 of policy wording, exact quote verified against extracted text).
   - Step 5: Recording user follow-up answers with `FactSource(source_type="user_provided")` provenance.
   - Step 6: Uploading applicable endorsement (`Joint_Replacement_Endorsement.pdf`) without mutating or deleting earlier documents or version histories.
   - Step 7: Reassessment with Evidence Change Replay (Revision 1 -> Revision 2: unresolved -> supported), older packet v1 snapshot permanently immutable.
   - Step 8: Updated next actions and dynamic question pruning (obsolete waiting period questions removed; unresolved gaps preserved).
   - Step 9: Standalone HTML review packet export directly from snapshot v2 with full HTML escaping, print CSS, and zero local filesystem paths.
   - Step 10: Application restart simulation with complete SQLite lifecycle persistence across fresh database sessions.

2. Edge Cases, Isolation & Invariant Enforcement:
   - Case Isolation: Cases remain strictly isolated; Case B cannot see or mutate Case A's documents, facts, or review packets.
   - Duplicate Uploads: Exact SHA-256 match returns existing record with `is_duplicate=True`; updated content increments immutable version (`v1` -> `v2`).
   - Unreadable Scanned PDFs: Extracted with status `'unreadable'`, zero invented findings or fake coverage claims; partial review workflow remains accessible.
   - Hospital Reference Lookup: Verified all 4 states (`matched`, `no_match`, `ambiguous_match`, `missing_information`).
   - Synthetic Data Transparency: Explicit synthetic labelling (`v2026.1`, `2026-10-01`) and boundary disclaimers present in UI, packet, and export.
   - Non-Authorisation Invariant: Authorization strictly defaults to `'not verified'`.
   - Tool Budget & Timeouts: Budget capped at <= 8 tool executions; timeouts report honest `'timeout'` stop reason while preserving validated partial findings.
   - Concurrency & Rollback: Stale reviews rejected via `StaleReviewError`; failed saves roll back cleanly.

3. Project Documentation & Demonstration Runbook:
   - Authored `README.md`:
     - System overview and domain boundaries.
     - Prerequisites (Python 3.10+) and dependency installation commands.
     - Required environment variable names without secrets.
     - Exact launch commands for Streamlit and verification suites.
     - Synthetic fixture locations and descriptions.
     - Repeatable clean-demo procedures preserving existing cases.
     - Transparent known limitations.
   - Authored `docs/DEMO_RUNBOOK.md`:
     - Story 1: Applicable Endorsement (cited initial shortfall -> upload endorsement -> validated change -> updated next actions and export).
     - Story 2: Mismatched/Conflicting Evidence (contradictory precedence retains conflict finding and questions without override).
     - Story 3: Unreadable PDF (explicit unreadable extraction status, zero invented findings, partial review preserved).

Interfaces changed:
- No shared schema modifications needed; full backward compatibility with Milestone M1-M6 interfaces preserved.
- Added test suites `tests/test_m7_journey.py` and `tests/verify_m7.py`.

Checks and results:
- `pytest tests/test_m7_journey.py -v`: 6/6 passed in 2.51s.
- `python tests/verify_m7.py`: All 21 combined acceptance checks passed.
- `pytest -q`: 134/134 tests passed in 14.00s.
- `python tests/verify_m1.py` through `tests/verify_m6.py`: All milestone verification suites pass cleanly.

Mocks / limitations / blockers:
- Zero blockers. All features are integrated and verified against actual SQLite database and bounded review agent.

Next action for other owner:
- Owner B: Review M7-A verification results, rehearse demo runbook stories, and integrate into main.
