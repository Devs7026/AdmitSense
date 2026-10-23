# AdmitSense — Project Context & Boundaries

## 1. Product Summary

- **Product Name**: AdmitSense
- **Primary Persona**: A family caregiver preparing for a loved one's planned hospital admission.
- **Core Problem**: Complex health insurance policy clauses, exclusions, waiting periods, missing evidence, and late document revisions create high stress, surprise out-of-pocket costs, and uncertainty about what actions to take or what questions to ask hospital desk or insurer staff.
- **Target Outcome**: A transparent, cited **Review Packet** providing administrative preparation:
  - Supported and unresolved findings citing specific document passages and physical pages.
  - Actionable missing-evidence checklist items.
  - Concrete clarification questions for the hospital admission desk and insurer.
  - A traceable **Evidence Change Replay** showing how new documents or endorsements alter prior conclusions.
  - Self-contained HTML export for offline reference.

---

## 2. Caregiver User Journey

```text
[Create / Resume Case]
         │
         ▼
[Enter Known Facts (Optional/Partial)]
         │
         ▼
[Upload Evidence Documents (PDFs)]
         │
         ▼
[Run Review Analysis (Bounded Agent)]
         │
         ▼
[Inspect Findings & Cited Evidence]
         │
         ▼
[Address Missing-Evidence Checklist / Questions]
         │
         ▼
[Upload Revisions / Endorsements / Changes]
         │
         ▼
[Inspect Evidence Change Replay (Before / After)]
         │
         ▼
[Preview & Export Self-Contained Review Packet]
```

---

## 3. UI Architecture

AdmitSense is built using Streamlit with three primary navigation surfaces:

1. **Home**:
   - Welcome banner and caregiver guidance.
   - List of existing saved cases with status summaries (complete, incomplete, last updated).
   - "New Case" setup initiation.
2. **Case Setup**:
   - Input form for patient details, policy identification, procedure, planned admission date, and hospital name.
   - Fact provenance tracking (recording user-provided vs. document-derived entries).
   - Non-blocking inputs: allows unknown values and incomplete initial state.
3. **Case Workspace**:
   - **Next Action Banner**: High-priority recommendation (e.g., clarify pre-existing waiting period, request cost breakdown).
   - **Findings Panel**: Topic-by-topic breakdown (`supported`, `unresolved`, `conflict`, `needs_human_review`).
   - **Evidence Viewer**: Side-by-side or modal display rendering the exact PDF document, version, and physical page cited.
   - **Documents Panel**: Upload manager with immutable version history, SHA-256 hash, and extraction status.
   - **Missing-Evidence Checklist**: Items flagged as missing, with reasons and suggested actions.
   - **Evidence Change Replay**: Visual diff of finding revisions across document iterations.
   - **Review Packet Export**: Print-ready, CSS-styled HTML export.

---

## 4. MVP Scope & Technology Choices

| Area | Technology / Choice | In-Scope | Out-of-Scope (MVP) |
|---|---|---|---|
| **Frontend** | Streamlit + Vanilla CSS | Clean, responsive multi-section dashboard | Complex custom React frontends |
| **Document Ingestion** | `pypdf` | Text-based PDF extraction, physical page numbers | OCR for scanned handwritten records |
| **Domain Modeling** | Pydantic v2 (`schemas.py`) | Strict validation, immutable evidence references | Dynamic unvalidated dictionaries |
| **Storage** | SQLite (`sqlite3`) | Relational persistence of cases, documents, pages, reviews | External cloud databases / migrations |
| **Agent / Review** | Bounded Agent (Groq / LLM) | Retrieval tools, max 8 calls, timeout, partial results | Unbounded multi-agent frameworks, LangChain/CrewAI |
| **Hospital Reference** | Synthetic Local JSON | Dated, versioned synthetic hospital/network lookup | Live hospital network scrapers / real APIs |
| **Exports** | Static HTML / Print CSS | Deterministic snapshot export from saved packets | PDF rendering engines (WeasyPrint, etc.) |

---

## 5. Non-Negotiable Invariants

1. **No Insurance Approval Inference**: AdmitSense is an administrative preparation aid. It must NEVER state, imply, or infer insurance approval or cashless claim guarantee.
2. **Authorisation Status**: Defaults strictly to `"not verified"`. Transition to `"pending insurer review"` requires explicit evidence of submission.
3. **Unknown Facts Remain Unknown**: Missing information stays `None`/unspecified. The application must never hallucinate dummy dates or IDs.
4. **Untrusted Evidence**: Document text is treated strictly as data, never as prompt instructions.
5. **Physical Page Integrity**: All citations cite the physical 1-based PDF page number (matching the page index in standard PDF viewers), retaining blank pages.
6. **Immutable Versions**: Re-uploading a document creates a new version (`v2`); older versions and their citations remain immutable.
7. **Deterministic Export**: HTML exports are generated directly from the persisted `ReviewPacket` database record, never from a live model invocation.
8. **Emergency Care Notice**: The application must visibly advise that emergency medical care should never be delayed for insurance administrative review.
