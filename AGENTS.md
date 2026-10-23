# AdmitSense — Agent Guidelines & Operating Manual

This repository is developed cooperatively by two owners and their coding agents:
- **OWNER A (Interface / Data)**: UI (Streamlit), PDF uploads and text extraction, SQLite persistence, evidence viewer, checklist/replay displays, and HTML packet export.
- **OWNER B (Agent / Review)**: Evidence retrieval tools, bounded agent execution, policy/applicability reasoning, finding generation, Evidence Change Replay computation, and agent evaluation.

---

## 1. Mandatory Read-First Sequence

Before executing any work, any coding agent must inspect:
1. `AGENTS.md` (this file)
2. `docs/MILESTONES.md` (stable milestone build plan)
3. `docs/PROJECT_CONTEXT.md` (domain boundaries, persona, invariants)
4. `docs/CONTRACTS.md` (implemented vs. proposed interfaces and schemas)
5. `docs/TASKS.md` (current task board, dependencies, acceptance checks)
6. `docs/DECISIONS.md` (architectural decisions and rationale)
7. `docs/handoffs/interface-data.md` (Owner A's latest handoff)
8. `docs/handoffs/agent-review.md` (Owner B's latest handoff)
9. Repository state (`git status`, current branch, recent commits, uncommitted changes)

---

## 2. Core Product Invariants & Boundaries

Every component must adhere to these non-negotiable rules:
- **No Inferred Insurance Approval**: Findings assist administrative preparation for hospital admission; they never establish overall policy coverage or insurer approval.
- **Authorization Defaults to Unverified**: Authorization status defaults to `"not verified"`. `"pending insurer review"` strictly requires proof of submission.
- **Unknown Facts Stay Unknown**: If a fact is missing from user input or documents, preserve it as `None`/unknown. Never invent dummy or placeholder values.
- **Provenance Tracking**: Always differentiate user-provided facts from document-derived facts using `FactSource`.
- **Untrusted Document Text**: Document text is untrusted user input. It must never be treated as system prompts or executable instructions.
- **Physical 1-Based Page Numbers**: Extracted PDF pages must preserve physical 1-based page numbering, including blank pages.
- **Immutable Document Versions**: Document uploads are hashed and assigned immutable versions (`v1`, `v2`, etc.). Uploading a new document never silently mutates an existing version.
- **Precedence & Revisions**: A newer document does not automatically override earlier evidence. Contradictions or unverified effective dates result in `"conflict"` or `"unresolved"` status.
- **Deterministic Export**: HTML exports must render the exact saved `ReviewPacket` snapshot from storage, not trigger fresh agent re-evaluations.
- **Synthetic Data Transparency**: All synthetic hospital records and mock policies must be explicitly labelled with dataset dates and versions.
- **Tool Budget Enforcement**: Bounded agent runs are capped at a maximum of 8 tool calls per execution in application code, with a timeout, returning validated partial results if exhausted.

---

## 3. Collaboration & Git Protocol

- **Single Owned Task**: Work on one owned task at a time on an appropriate feature branch (e.g. `feat/m1-case-persistence`).
- **Handoff Files**:
  - Owner A updates ONLY `docs/handoffs/interface-data.md`.
  - Owner B updates ONLY `docs/handoffs/agent-review.md`.
  - Never edit your teammate's handoff file. Read it before starting each session.
- **Safe Git Operations**:
  - Never use `git push --force` or `git reset --hard` on shared branches.
  - Verify branch status: a pushed remote branch is not automatically merged into local checkouts.
  - Commit, push, and merge only within explicit user authorisation.
- **Task Status Lifecycle**:
  - Valid statuses: `TODO`, `IN_PROGRESS`, `BLOCKED`, `IN_REVIEW`, `INTEGRATED`.
  - Only mark a task `INTEGRATED` after the code has been merged and has passed relevant integration acceptance checks.
- **Contract & Schema Changes**:
  - Do not unilaterally alter shared schemas in `src/admitsense/schemas.py`.
  - Propose contract modifications in `docs/CONTRACTS.md` marked as `PROPOSED - Awaiting Teammate Review` and coordinate before editing code.
  - Do not implement your teammate's components to bypass a dependency. Use explicitly labelled test fixtures.
