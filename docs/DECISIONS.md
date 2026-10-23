# AdmitSense — Architectural Decision Log

This record documents key architectural decisions, rationale, and implications.

---

## DEC-001: Pydantic v2 Schemas as Shared Domain Contract
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: Owner A (interface/data) and Owner B (agent/review) need strict, unambiguous data structures to exchange case facts, findings, evidence citations, revisions, and review packets.
- **Decision**: Define shared domain models in `src/admitsense/schemas.py` using Pydantic v2 with strict validation (`extra="forbid"`, whitespace stripping, and custom validators for fact sources, evidence citations, and revision increments).
- **Implications**: Both owners must write code conforming to these models. Schema breaking changes must be coordinated via `docs/CONTRACTS.md` before editing.

---

## DEC-002: SQLite as Local Persistence Engine
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: The MVP requires local persistence for cases, uploaded documents, extracted pages, and review packet histories across Streamlit app rerenders and restarts.
- **Decision**: Use Python's built-in `sqlite3` to store relational records in a local database file. Store binary PDF files under a dedicated storage directory referenced by file path and SHA-256 hash.
- **Implications**: No external database service required; supports ACID transactions for atomic multi-table updates (e.g. saving a new review packet along with its findings and revision logs).

---

## DEC-003: Physical 1-Based Page Numbering & Immutable Document Versions
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: Citations must correspond to what a caregiver or hospital desk sees when opening the PDF in a standard PDF viewer. Document updates or endorsements may be uploaded later.
- **Decision**:
  1. PDF text extraction preserves physical 1-based page indexes, including empty pages.
  2. Documents are identified by SHA-256 hash and version string (`v1`, `v2`).
  3. Re-uploading a document with changes increments its version without mutating or deleting earlier versions or citations.
- **Implications**: Citations in past review packets remain permanently valid and verifiable against the specific document version originally reviewed.

---

## DEC-004: Decoupling Administrative Findings from Insurer Authorization
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: Users might mistake a "supported" finding (e.g. 24-month waiting period satisfied) for insurance approval or a guarantee of cashless hospitalisation.
- **Decision**:
  1. Administrative findings express condition satisfaction based on available evidence, not claim authorization.
  2. `authorization_status` is tracked separately, defaulting to `"not verified"`.
  3. Transitioning `authorization_status` to `"pending insurer review"` requires explicit evidence of submission.
- **Implications**: UI and export layouts must clearly separate policy findings from claim authorization status and include prominent disclaimers.

---

## DEC-005: Bounded Agent Execution Budget
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: LLM agent loops can loop indefinitely, run up excessive API costs, or hang Streamlit UI threads if evidence is missing or ambiguous.
- **Decision**: Enforce a strict budget of at most 8 tool calls per review run in application code, count failed/repeated attempts, and apply a timeout. Return validated partial results when limits are reached with `stopped_reason = "tool_limit_reached"` or `"timeout"`.
- **Implications**: The agent runner must decrement its budget before invoking each tool and handle partial results gracefully without crashing the UI.

---

## DEC-006: Frozen Snapshot HTML Packet Export
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: Exporting a review packet must produce a deterministic, shareable document that matches what the caregiver reviewed on screen.
- **Decision**: HTML export renders the exact saved `ReviewPacket` record retrieved from SQLite. It must never trigger a new LLM model invocation during export. Dynamic fields must be HTML-escaped.
- **Implications**: Export generation is fast, deterministic, offline-capable, and completely reproducible.

---

## DEC-007: Handoff Isolation Protocol
- **Date**: 2026-10-23
- **Status**: Accepted
- **Context**: To prevent merge conflicts, hallucinations of teammate progress, and silent overwrites, agents must respect strict documentation boundaries.
- **Decision**:
  - Owner A maintains and edits only `docs/handoffs/interface-data.md`.
  - Owner B maintains and edits only `docs/handoffs/agent-review.md`.
  - Agents read both files at session start, but only update their own file upon session completion.
- **Implications**: Clear accountability and zero conflicting updates across independent owner workflows.
