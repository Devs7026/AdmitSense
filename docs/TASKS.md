# AdmitSense — Task Board

Track all milestone tasks from `docs/MILESTONES.md`.

Valid statuses:
- `TODO`: Not yet started or waiting on prerequisites.
- `IN_PROGRESS`: Actively being worked on by assigned owner.
- `BLOCKED`: Work paused waiting on an external dependency or teammate contract.
- `IN_REVIEW`: Implementation done and verified locally; awaiting teammate/peer review.
- `INTEGRATED`: Merged into checkout and verified passing integration acceptance checks.

---

## Task Board Table

| Task ID | Owner | Status | Dependencies | Branch / Commit | Acceptance Check & Deliverable |
| **M0-A** | Owner A | `INTEGRATED` | None | `main` | Reconcile shared context files (`AGENTS.md`, `PROJECT_CONTEXT.md`, `CONTRACTS.md`, `TASKS.md`, `DECISIONS.md`, handoff templates); propose storage & ingestion interfaces without clobbering existing code. |
| **M0-B** | Owner B | `INTEGRATED` | M0-A | `main` | Reviewed `schemas.py` & Owner A's storage proposals; documented ReviewRunner, ToolActivityEvent, HospitalRecordReference, and replay in `CONTRACTS.md`; authored 4 sample fixtures in `tests/fixtures/sample_review_packets.py` & JSON; 7/7 tests passing in `tests/test_sample_fixtures.py`. |
| **M0-I** | Both | `INTEGRATED` | M0-A, M0-B | `main` | Agreed document/page representation, extraction statuses, review entry point, persistence boundary; loaded shared sample packet fixtures via `ReviewPacket`. |
| **M1-A** | Owner A | `INTEGRATED` | M0-I | `main` (`2a27074`) | Case form, saved-case list, SQLite repository, unknown values & fact provenance; Home/Setup/Workspace navigation skeleton. Verified persistence and case isolation with 7 tests. Merged into main. |
| **M1-B** | Owner B | `INTEGRATED` | M0-I | `main` | Verified partial case creation (missing policy ID, dates, procedure, hospital); verified FactSource provenance enforcement; refined complete/incomplete sample fixtures with documented loader helpers; 22/22 pytest checks passing. |
| **M1-I** | Both | `INTEGRATED` | M1-A, M1-B | `main` | Connected sample packet to workspace as a clearly labelled development fixture; verified case isolation and refresh persistence (tests/verify_m1.py passed 5/5 checks; 29/29 pytest passed). |
| **M2-A** | Owner A | `INTEGRATED` | M0-I (storage M1-A) | `main` (`1499041`) | Upload limits/type checks; immutable versions & SHA-256 duplicate handling; `pypdf` extraction retaining 1-based page positions and blank pages; explicit unreadable/partial/error statuses; document/page viewer. Authored synthetic policy, schedule, endorsement, and hospital JSON. Verified with 36 tests and verify_m2.py. Merged into main. |
| **M2-B** | Owner B | `INTEGRATED` | M0-I | `dev-agent` / `main` | Implemented EvidenceRetrievalService, search_pages, read_page, and verify_citation in src/admitsense/agent/retrieval.py; authored synthetic document fixtures & expected outcomes; connected to SQLite db storage; 28/28 tests passing in tests/test_evidence_retrieval.py (61/61 total). |
| **M2-I** | Both | `INTEGRATED` | M2-A, M2-B | `main` | Connected retrieval results to real evidence viewer and Owner A's SQLite extracted documents; verified search, reading physical pages, case isolation, and citation verification in tests/test_m2_integration.py and tests/verify_m2.py (8/8 checks passed). |
| **M3-A** | Owner A | `INTEGRATED` | M1-I, M2-I | `main` | Review action trigger, ReviewRepository SQLite persistence, ReviewService adapter, interactive findings cards, citation links to evidence viewer with quote highlighting, missing-evidence checklist, explicit incomplete/error states, separate authorization banner. Verified with 3 unit tests in tests/test_review_repository.py (71/71 pytest passing) and 7 acceptance checks in tests/verify_m3.py. Merged into main. |
| **M3-B** | Owner B | `INTEGRATED` | M1-I, M2-I | `feat/m3-waiting-period-review` | Implemented WaitingPeriodReviewer & run_waiting_period_review in src/admitsense/agent/review.py; evaluates 24-mo condition vs 18-mo history, producing cited shortfall & clarification request without invented waivers; verified citations on physical page 14; 7/7 tests passing in tests/test_waiting_period_review.py (78/78 total); verify_m3.py passed all combined checks. |
| **M3-I** | Both | `INTEGRATED` | M3-A, M3-B | `main` | End-to-end integration: Upload → Extract → Review → Persist → Display. Connected WaitingPeriodReviewer to ReviewService and ReviewRepository; real 24-month condition vs 18-month history review persists and renders in UI. |
| **M4-A** | Owner A | `TODO` | M3-I | — | Concise tool activity event stream, stop reason/partial results view, user answer inputs, retry/resume action, and "I don't have it" checklist action; preserve answers across refresh. |
| **M4-B** | Owner B | `IN_REVIEW` | M3-I | `feat/m4-bounded-agent` | Implemented BoundedReviewAgent in src/admitsense/agent/review.py; pre-dispatch cap of 8 calls strictly enforced (call 9 blocked); failures/retries consume budget; cross-case access rejected; run timeout & bounded loop iterations; paused topic allows independent checks; partial results with explicit stop reason; structured ToolActivityEvent telemetry; explicit resumption creates new run ID; 'user does not have this evidence' handled without repeated requests; prompt injection resistance. 9/9 tests passing in tests/test_bounded_agent.py (87/87 full suite); 8/8 checks passing in tests/verify_m4.py. |
| **M4-I** | Both | `TODO` | M4-A, M4-B | — | Streamlit rerender does not re-trigger automatic runs; budget does not automatically reset; resumption creates explicit new run ID. 9th call never executes. Execution side prepared and verified. |
| **M5-A** | Owner A | `TODO` | M3-I | — | Add evidence to existing case, immutable finding snapshots, transactional saving of new findings/revisions/packet, before-after diff view, updated next action banner. |
| **M5-B** | Owner B | `TODO` | M3-I | — | Applicability checks (effective dates, policy IDs, member match); identify affected findings; compute `Revision` entries (old/new status, evidence, reason, trigger); support fact/date corrections. |
| **M5-I** | Both | `TODO` | M5-A, M5-B | — | Applicable endorsement changing 24 to 12 months revises only justified findings; original history intact; next action updates; restart preserves full audit trail. |
| **M6-A** | Owner A | `TODO` | M3-I | — | Dated synthetic hospital display, self-contained HTML preview and download with embedded CSS, escaped dynamic text, packet ID/version/time, findings/citations/checklist/questions/history. |
| **M6-B** | Owner B | `TODO` | M3-I | — | Hospital lookup with record ID/dataset version/source date; limitations and desk questions; validate output wording and unresolved conditions. |
| **M6-I** | Both | `TODO` | M6-A, M6-B | — | Exported HTML packet matches the saved snapshot from SQLite; no live model calls during export; synthetic dataset clearly labelled. |
| **M7-A** | Owner A | `TODO` | M1–M6 integrated | — | Test navigation/resume/case isolation, evidence links, duplicate/unreadable uploads, export layout; document launch/config in README. |
| **M7-B** | Owner B | `TODO` | M1–M6 integrated | — | Run expected-outcome test suite, invalid references, policy/date mismatch, conflicts, prompt injection, model failure, timeout, tool budget limits. |
| **M7-I** | Both | `TODO` | M7-A, M7-B | — | Execute 3 end-to-end stories: (1) Applicable endorsement, (2) Mismatched/conflicting evidence, (3) Unreadable PDF extraction failure. Rehearse clean demo. |
