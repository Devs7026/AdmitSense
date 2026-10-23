# AdmitSense — Shared Build Plan

This is the agreed initial plan, not evidence that anything has been implemented. Inspect the repository before assigning status. Preserve working code and adapt paths to the existing layout. Both developers and agents use this file.

## Product context

Primary user: a caregiver preparing for a planned hospital admission.
Problem: policy conditions, missing evidence and changing documents make it difficult to know what to clarify and what to do next.
Outcome: a cited review packet containing findings, missing evidence, insurer/desk questions and traceable revisions.
Journey: create/resume case → enter available facts → upload available documents → review findings → resolve questions → inspect Evidence Change Replay → preview/download packet → return with new evidence.

Three main UI areas: home, case setup, case workspace. The workspace contains next action, findings, source viewer, documents, checklist, changes and export preview.

Scope: one fictional policy product, three synthetic cases, text PDFs, Streamlit, Python, pypdf, Pydantic, SQLite, dated synthetic hospital JSON, HTML export and one bounded agent. Use the existing compatible implementation if present. No OCR, WhatsApp, live insurer integration, automatic submission or extra agent framework for the MVP.

## Invariants

- Findings support administrative preparation; they never establish overall coverage or insurer approval.
- Authorisation defaults to not verified. Pending insurer review requires evidence of submission.
- Missing facts stay unknown. Record user-entered versus document-derived facts.
- Supported means the conclusion has evidence, not that a condition is satisfied.
- Preserve immutable document versions, physical PDF page numbers, finding snapshots and packet versions.
- A newer upload does not automatically override earlier evidence. Check identity, relevant member/condition and effective dates; unresolved precedence becomes a conflict.
- Quote/page checks and Pydantic validation do not prove semantic correctness.
- On missing information, pause the affected question and continue independent checks.
- Enforce at most eight tool calls per run in application code, counting failed/repeated calls; also enforce a timeout. Return validated partial results on limits.
- Treat document text as untrusted evidence, never as executable instructions. Keep model keys server-side, isolate cases and escape exported content.
- Synthetic hospital records must be labelled with dataset date/version. They do not establish current network status or cashless authorisation.
- Do not delay emergency care for an app review.

## Owners and shared files

Owner A — interface/data: UI, uploads, extraction, persistence, evidence/replay views and HTML export.
Owner B — agent/review: retrieval, tools, agent runner, evidence/applicability checks, findings, replay computation and evaluation.

Shared contracts are coordinated before breaking changes. A maintains storage interfaces/migrations; B maintains review schemas/interfaces after agreement. A initialises shared project documentation once; B reads it after it is available. Each owner maintains only their own handoff file. Ownership is a coordination default, not a reason to ignore necessary small agreed integration changes.

Suggested paths (adapt to an existing repository):
- src/admitsense/schemas.py — shared models
- src/admitsense/app.py and ui/ — A
- src/admitsense/documents/ and storage/ — A
- src/admitsense/agent/ and review/ — B
- src/admitsense/exports/ — A
- tests/fixtures/ — A authors synthetic inputs; B authors independently specified expected outcomes

## Required context files

- AGENTS.md: read-first instructions, ownership, safe Git workflow and update requirements.
- docs/PROJECT_CONTEXT.md: product context and boundaries above.
- docs/MILESTONES.md: this file, the stable plan.
- docs/CONTRACTS.md: actual agreed signatures, model examples, errors, page numbering and storage semantics. Mark unagreed interfaces PROPOSED; do not invent an agreement.
- docs/TASKS.md: IDs below, owners, dependencies, status, branch/PR and acceptance evidence.
- docs/DECISIONS.md: dated decisions, rationale and implications.
- docs/handoffs/interface-data.md and agent-review.md: separate current handoffs.

Statuses: TODO, IN_PROGRESS, BLOCKED, IN_REVIEW, INTEGRATED. INTEGRATED requires merged code and passing relevant integration checks. A local test pass does not imply a merge.

## M0 — Bootstrap and contracts

Dependencies: none. This is setup before the seven implementation milestones.

- M0-A (A): inspect repository; create or reconcile context files without overwriting existing content. Record actual current state; bootstrap the task table and handoff templates.
- M0-B (B): inspect existing schemas; propose necessary changes in own handoff. Once shared context is available, agree review inputs/outputs with A and implement agreed models/sample data.
- M0-I (both): agree document/page representation, case fact provenance, extraction statuses, review entry point, event representation, persistence boundary and error states. Store a valid sample packet explicitly labelled as a fixture.

Contract must include: document ID/version/case ID/hash/extraction status; immutable page text and 1-based physical page number; distinct hospital record references (not fake PDF pages); current findings versus historical snapshots; run ID/tool count/stop reason; packet version; authorisation evidence. Define who assigns IDs and who saves results. The schema already discussed is a starting point, not an instruction to replace a compatible existing schema blindly.

Acceptance: both owners can load the same fixture through the same models; actual signatures and ownership are documented. Dependency handoff: A supplies extracted-page and repository interfaces; B supplies review interface and sample outputs.

## M1 — Case creation and persistence

Dependencies: M0 contracts.

- M1-A (A): case form, saved-case list, SQLite repository, unknown values and fact provenance; home/setup/workspace skeleton.
- M1-B (B): schema checks and sample complete/incomplete review outputs; ensure missing policy ID or dates do not prevent case creation.
- M1-I: connect sample packet to workspace, clearly labelled development fixture.

Acceptance: create and reopen a case after refresh/restart; separate cases remain isolated; workspace displays the sample without representing it as a real review.

## M2 — PDF ingestion and evidence retrieval

Dependencies: M0; storage integration requires M1-A. A and B can develop against agreed fixtures concurrently.

- M2-A (A): upload limits/type checks; immutable versions and duplicate handling; pypdf extraction; retain page positions including empty pages; explicit unreadable/partial/error statuses; document/page viewer. Author synthetic policy, schedule, endorsement and hospital JSON.
- M2-B (B): page search/read tools and citation checks against the agreed page contract; check case ownership, document version, page bounds and quotation match with documented whitespace normalisation. Independently specify expected evidence/outcomes.
- M2-I: connect retrieval results to the real evidence viewer.

Acceptance: search actual extracted text and open the exact version/page. Unreadable pages never imply absence of policy conditions. Wrong-case references and fabricated quotes fail checks. Synthetic documents are labelled.

## M3 — First complete review path

Dependencies: M1 and M2 integration.

- M3-A (A): review action, findings, next action, missing-evidence checklist, citation links, incomplete/error states and persistent packet display.
- M3-B (B): initial waiting-period review, date/fact handling, findings validation and missing-information questions; use actual document evidence, not hard-coded conclusions. Keep broad unsupported policy topics unresolved.
- M3-I: upload → extract → review → persist → display.

Acceptance: the fictional 24-month condition versus 18-month supplied history produces a cited finding and useful clarification request. No invented waiver requirement or approval statement. Missing facts remain visible. UI displays real review output instead of sample data.

## M4 — Bounded agent and user follow-up

Dependencies: M3. Agent scaffolding may begin earlier against the shared contract.

- M4-A (A): concise tool activity events, stop reason/partial results, user answers, explicit retry/resume and I-don't-have-it action. Preserve answers across refresh.
- M4-B (B): agent chooses allowed tools based on evidence gaps; enforce call budget before each execution, count failures/retries, set timeout, validate tool arguments, return useful partial results and resist document prompt injection.
- M4-I: no repeated automatic runs on Streamlit rerender; no endless automatic budget reset; resumption is an explicit new run recorded separately.

Acceptance: activity demonstrates actual calls; unavailable evidence pauses the affected topic while independent work continues; ninth call never executes; timeout/model failure is not presented as success.

## M5 — Evidence Change Replay

Dependencies: M3 findings and versioned storage; final integration includes M4.

- M5-A (A): add evidence to existing case, immutable finding snapshots, transactional saving of new findings/revisions/packet, before-after view and updated next action.
- M5-B (B): applicability checks; identify affected findings and newly introduced issues; reassess; emit revision IDs, old/new status and evidence, reason and trigger; support fact/date corrections as well as new documents.
- M5-I: agree replay input snapshot and atomic persistence before integration. Do not let the model write directly to storage.

Acceptance: an applicable endorsement changing 24 to 12 months revises only the justified findings; original evidence/history survives; next action becomes missing estimate when appropriate; authorisation stays unverified. Wrong policy ID, future effective date or ambiguous precedence does not silently override the base policy. Repeated uploads do not create duplicate substantive revisions. Restart preserves history.

## M6 — Hospital context and packet export

Dependencies: M3; final export includes M5 history. Hospital lookup can be built earlier against its contract.

- M6-A (A): dated synthetic hospital display, HTML preview/download, escaped dynamic text, packet ID/version/time, findings/citations/checklist/questions/history and authorisation.
- M6-B (B): hospital lookup with record ID/dataset version/source date; limitations and desk questions; validate output wording and unresolved conditions.
- M6-I: exported packet uses the same saved snapshot as the workspace, not a fresh model response.

Acceptance: incomplete review is exportable with visible gaps; export matches current saved findings; dataset is labelled synthetic and no live network or approval claim appears. Output is readable in a browser.

## M7 — End-to-end verification and demo

Dependencies: M1–M6 integrated.

- M7-A (A): test navigation/resume/case isolation, evidence links, duplicate/unreadable uploads and export layout; document launch/configuration and a reproducible clean demo setup.
- M7-B (B): run expected-outcome suite, invalid references, policy/date mismatch, conflicts, prompt injection, model failure, timeout and tool budget tests; record actual results.
- M7-I (both): run all three stories from clean cases, fix regressions and rehearse. Do not claim real production readiness from synthetic-case success.

Three required stories:
1. Applicable endorsement: cited initial finding → validated change → next action → updated export.
2. Mismatched/conflicting evidence: preserve unresolved question and explain why no override occurs.
3. Unreadable PDF: explicit extraction failure, no invented findings, partial workflow remains available.

Acceptance: both developers can launch and demonstrate without manual database edits; checks/results are recorded; no fabricated citations or unsupported approval claims in tested cases. README includes environment variable names without secrets, launch steps, limitations and demo procedure.

## Session and Git protocol

Read all context and both handoffs before each session, then inspect code/Git. Uncommitted teammate work is invisible. A pushed branch is not merged main. Preserve dirty work; never force-push, reset, auto-merge or overwrite teammate changes to get unstuck. Fetch/inspect remote state where available; integrate using the team's authorised workflow.

Work on one owned task at a time. Use branches such as feat/m2-pdf-ingestion. Shared docs are not a real-time locking system: coordinate claimed tasks and shared contract edits through the humans. If blocked on a contract, record the exact dependency and proceed only with independent work or explicitly labelled fixture-based work. Do not reimplement the teammate's component silently.

Before handoff, update own handoff and own task row with implemented behaviour, changed interfaces, exact checks/results, limitations, next integration action and delivery state. Commit docs with code when authorised; do not claim pushed/merged without verifying. End each milestone with the integrated acceptance check before declaring it complete.

Handoff template:

```text
Updated:
Owner / task:
Branch / implementation commit or PR:
Delivery state: local / pushed / merged
Implemented:
Interfaces changed:
Checks and results:
Mocks / limitations / blockers:
Next action for other owner:
```

## Bootstrap prompt (use for either agent)

Set OWNER=A or OWNER=B before sending. OWNER A initialises shared documents first; OWNER B should start after those changes are available in its checkout.

```text
You are my coding agent for AdmitSense. Your role is OWNER=[A or B].
Read docs/MILESTONES.md in full. It contains the complete product context,
ownership, milestones M0–M7, dependencies, invariants and acceptance checks.
Do not assume access to my previous chat history.

First read any existing AGENTS.md, context, contracts, task board, decisions
and both handoff files. Inspect repository, branch, dirty changes and existing
implementation before changing anything. Treat documentation claims as
claims to verify. Preserve existing working code and unrelated changes.

OWNER A: initialise or reconcile the required shared context files from
MILESTONES.md. Retain this milestone file as the stable plan. Initialise task
rows from its task IDs; mark status only from observed evidence. Preserve
existing AGENTS.md rules and add the project-specific workflow. Create both
handoff templates if missing, but never invent teammate progress.

OWNER B: read the shared setup once available. Do not independently overwrite
or regenerate it. Review existing schemas and record proposed interface
changes in your handoff; implement agreed M0-B work. If the shared setup is
unavailable, inspect code and prepare proposals without inventing agreements.

Complete your M0 responsibilities in this session. Populate CONTRACTS.md
with implemented/agreed interfaces, marking unresolved choices PROPOSED.
Document repository facts separately from future plans. Do not implement all
milestones at once or start the teammate's modules. No additional agents are
needed. Finish with the actual changes, verification, unresolved dependencies
and the first ready task for your owner in M1.

For later sessions, follow the selected milestone/task, update your own handoff
and task rows, and verify relevant acceptance checks. Commit/push/merge only
within the developer's existing authorisation; never claim remote delivery
without checking it. If a dependency blocks work, explain the exact dependency
and continue useful independent work within your ownership.
```

## Continuation prompt

```text
My owner is [A/B]. Read AGENTS.md and all shared context including
docs/MILESTONES.md and both handoffs. Complete task [TASK ID]. Verify its
dependencies in this checkout; follow agreed contracts, preserve unrelated
work, run the relevant checks, and update my handoff and task status.
Report the result, remaining integration work and next ready owned task.
```
