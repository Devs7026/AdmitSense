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
|---|---|---|---|---|---|
| **M0-A** | Owner A | `IN_REVIEW` | None | `main` (local) | Reconcile shared context files (`AGENTS.md`, `PROJECT_CONTEXT.md`, `CONTRACTS.md`, `TASKS.md`, `DECISIONS.md`, handoff templates); propose storage & ingestion interfaces without clobbering existing code. Completed locally. |
| **M0-B** | Owner B | `IN_REVIEW` | M0-A | `dev-agent` (local) | Reviewed `schemas.py` & Owner A's storage proposals; documented ReviewRunner, ToolActivityEvent, HospitalRecordReference, and replay in `CONTRACTS.md`; authored 4 sample fixtures in `tests/fixtures/sample_review_packets.py` & JSON; 7/7 tests passing in `tests/test_sample_fixtures.py`. |
| **M1-A** | Owner A | `INTEGRATED` | M0-I | `main` (`2a27074`) | Case form, saved-case list, SQLite repository, unknown values & fact provenance; Home/Setup/Workspace navigation skeleton. Verified persistence and case isolation with 7 tests. Merged into main. |
| **M1-B** | Owner B | `IN_REVIEW` | M0-I | `dev-agent` (local) | Verified partial case creation (missing policy ID, dates, procedure, hospital); verified FactSource provenance enforcement; refined complete/incomplete sample fixtures with documented loader helpers; 22/22 pytest checks passing. |
| **M1-I** | Both | `TODO` | M1-A, M1-B | — | Connect sample packet to workspace as a clearly labelled development fixture; verify case isolation and refresh persistence. |
| **M2-A** | Owner A | `TODO` | M0-I (storage M1-A) | — | Upload limits/type checks; immutable versions and SHA-256 duplicate handling; `pypdf` extraction retaining 1-based page positions and blank pages; explicit unreadable/partial/error statuses; document/page viewer. Author synthetic policy, schedule, endorsement, and hospital JSON. |
| **M2-B** | Owner B | `TODO` | M0-I | — | Page search/read tools and citation checks against agreed page contract; check case ownership, document version, page bounds, and quote matching with normalized whitespace. Independently specify expected evidence. |
| **M2-I** | Both | `TODO` | M2-A, M2-B | — | Connect retrieval results to real evidence viewer. Search extracted text and navigate to exact document version and physical page. |
| **M3-A** | Owner A | `TODO` | M1-I, M2-I | — | Review action trigger, findings card, next action banner, missing-evidence checklist, citation links, incomplete/error states, and persistent packet display. |
| **M3-B** | Owner B | `TODO` | M1-I, M2-I | — | Initial waiting-period review, date/fact handling, findings validation, and missing-information questions; use actual document evidence, keeping unsupported topics unresolved. |
| **M3-I** | Both | `TODO` | M3-A, M3-B | — | End-to-end integration: Upload → Extract → Review → Persist → Display. 24-month condition vs 18-month history produces cited finding and clarification request; no invented waiver. |
| **M4-A** | Owner A | `TODO` | M3-I | — | Concise tool activity event stream, stop reason/partial results view, user answer inputs, retry/resume action, and "I don't have it" checklist action; preserve answers across refresh. |
| **M4-B** | Owner B | `TODO` | M3-I | — | Dynamic tool selection; enforce maximum 8 tool calls per execution in application code, count retries/failures, enforce timeout, validate tool inputs, return partial results, resist prompt injection. |
| **M4-I** | Both | `TODO` | M4-A, M4-B | — | Streamlit rerender does not re-trigger automatic runs; budget does not automatically reset; resumption creates explicit new run ID. 9th call never executes. |
| **M5-A** | Owner A | `TODO` | M3-I | — | Add evidence to existing case, immutable finding snapshots, transactional saving of new findings/revisions/packet, before-after diff view, updated next action banner. |
| **M5-B** | Owner B | `TODO` | M3-I | — | Applicability checks (effective dates, policy IDs, member match); identify affected findings; compute `Revision` entries (old/new status, evidence, reason, trigger); support fact/date corrections. |
| **M5-I** | Both | `TODO` | M5-A, M5-B | — | Applicable endorsement changing 24 to 12 months revises only justified findings; original history intact; next action updates; restart preserves full audit trail. |
| **M6-A** | Owner A | `TODO` | M3-I | — | Dated synthetic hospital display, self-contained HTML preview and download with embedded CSS, escaped dynamic text, packet ID/version/time, findings/citations/checklist/questions/history. |
| **M6-B** | Owner B | `TODO` | M3-I | — | Hospital lookup with record ID/dataset version/source date; limitations and desk questions; validate output wording and unresolved conditions. |
| **M6-I** | Both | `TODO` | M6-A, M6-B | — | Exported HTML packet matches the saved snapshot from SQLite; no live model calls during export; synthetic dataset clearly labelled. |
| **M7-A** | Owner A | `TODO` | M1–M6 integrated | — | Test navigation/resume/case isolation, evidence links, duplicate/unreadable uploads, export layout; document launch/config in README. |
| **M7-B** | Owner B | `TODO` | M1–M6 integrated | — | Run expected-outcome test suite, invalid references, policy/date mismatch, conflicts, prompt injection, model failure, timeout, tool budget limits. |
| **M7-I** | Both | `TODO` | M7-A, M7-B | — | Execute 3 end-to-end stories: (1) Applicable endorsement, (2) Mismatched/conflicting evidence, (3) Unreadable PDF extraction failure. Rehearse clean demo. |
