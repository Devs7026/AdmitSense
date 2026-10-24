# AdmitSense 🏥

> **Caregiver Admission Preparation & Insurance Review Assistant**  
> Streamlit interface, bounded autonomous agent review, traceable evidence citations, and deterministic review packet export for planned hospital admissions.

---

## 1. Product Overview & Boundaries

AdmitSense assists family caregivers in preparing for a loved one's planned hospital admission by analyzing health insurance policies, renewal schedules, and endorsements against case facts.

### Non-Negotiable Invariants & Boundaries
- **No Inferred Insurance Approval**: Findings assist administrative preparation only. They never establish overall policy coverage, cashless hospitalisation guarantees, or insurer pre-authorization.
- **Authorization Defaults to `"not verified"`**: Claim authorization status strictly defaults to `"not verified"`. Transition to `"pending insurer review"` requires explicit evidence of submission.
- **Physical 1-Based Page Numbers**: Citations strictly reference physical, 1-based PDF pages (including blank pages) so caregivers can locate the exact text in standard PDF readers.
- **Immutable Document Versions**: Document uploads are SHA-256 hashed and versioned (`v1`, `v2`). Updating a document never overwrites earlier versions or historical citations.
- **Evidence Change Replay**: Reassessment calculates substantive changes, incrementing finding revisions and preserving past packet snapshots immutably.
- **Deterministic Export**: Standalone HTML review packet export is rendered directly from saved database snapshots with zero live model calls and complete HTML escaping.
- **Synthetic Data Transparency**: Hospital directory entries and test policy documents are clearly dated and labelled as synthetic demonstration fixtures.
- **Bounded Tool Budget**: Review executions are strictly capped at at most 8 tool calls per run.

---

## 2. Prerequisites & Installation

### Prerequisites
- **Python**: 3.10, 3.11, 3.12, or 3.13+ (tested with Python 3.14).
- **Git**: For version control and branch workflows.
- **Operating System**: Windows, macOS, or Linux.

### Dependency Installation

1. **Clone Repository**:
   ```bash
   git clone https://github.com/Devs7026/AdmitSense.git
   cd AdmitSense
   ```

2. **Create & Activate Virtual Environment**:
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

---

## 3. Configuration & Environment Variables

AdmitSense operates out-of-the-box with local SQLite and built-in synthetic fixtures. For custom deployments or external model integration, configure the following environment variable names. **Never commit secrets or API tokens to the repository.**

| Variable Name | Description | Default Value |
|---|---|---|
| `ADMITSENSE_DB_PATH` | Path to the SQLite database file | `data/admitsense.db` |
| `ADMITSENSE_DOCS_DIR` | Directory storing uploaded PDF files | `data/documents` |
| `ADMITSENSE_HOSPITALS_PATH` | Path to dated synthetic hospital directory JSON | `data/hospitals/synthetic_hospitals.json` |
| `ADMITSENSE_PORT` | Port for the Streamlit web application | `8501` |
| `AGENT_MODEL` | Identifier for the LLM model (e.g. `gemini-2.0-flash`) | Local Bounded Agent |
| `AGENT_TOOL_BUDGET` | Maximum tool invocations per review run | `8` |
| `AGENT_TIMEOUT_SECONDS` | Maximum seconds allowed per review run | `30.0` |

---

## 4. Launch Commands

### Launch Web Application (Streamlit)
```powershell
.\.venv\Scripts\streamlit.exe run src/admitsense/app.py
```
Open your browser to: **`http://localhost:8501`**

### Run Verification & Acceptance Suites
```powershell
# Run complete test suite (134 tests)
.\.venv\Scripts\pytest -q

# Run end-to-end user journey verification (Milestone M7)
.\.venv\Scripts\python tests/verify_m7.py

# Run individual milestone verification scripts
.\.venv\Scripts\python tests/verify_m1.py
.\.venv\Scripts\python tests/verify_m2.py
.\.venv\Scripts\python tests/verify_m3.py
.\.venv\Scripts\python tests/verify_m4.py
.\.venv\Scripts\python tests/verify_m5.py
.\.venv\Scripts\python tests/verify_m6.py
```

---

## 5. Synthetic Fixture Locations

All demonstration files and test documents are fictional synthetic fixtures located in the repository:

- **Policy Master Wordings**: `tests/fixtures/synthetic/Care_Health_Gold_Policy_Wording.pdf` (15 physical pages, blank page 7, Section 4.2(b) waiting period on page 14).
- **Renewal Schedules**: `tests/fixtures/synthetic/Policy_Renewal_Schedule.pdf` (2 pages, documenting 18 months continuous coverage).
- **Applicable Endorsement Schedules**: `tests/fixtures/synthetic/Joint_Replacement_Endorsement.pdf` (1 page, reducing waiting period to 12 months for policy `POL-998877`).
- **Hospital Pre-Admission Estimates**: `tests/fixtures/synthetic/Apex_Hospital_Estimate.pdf` (2 pages, itemized hospital bill estimate).
- **Unreadable Scanned Documents**: `tests/fixtures/synthetic/Scanned_Receipt_Unreadable.pdf` (scanned document with 0 extractable text).
- **Dated Synthetic Hospital Directory**: `data/hospitals/synthetic_hospitals.json` (version `v2026.1`, publication date `2026-10-01`).

---

## 6. Safe Clean-Demo Procedure

To rehearse or present a demonstration without modifying existing saved cases or risk database corruption:

1. **Option A: Dedicated Demo Environment (Recommended)**:
   Launch the app with temporary storage paths:
   ```powershell
   $env:ADMITSENSE_DB_PATH = "data/demo_sandbox.db"
   $env:ADMITSENSE_DOCS_DIR = "data/demo_documents"
   .\.venv\Scripts\streamlit.exe run src/admitsense/app.py
   ```
   When finished, delete `data/demo_sandbox.db` and `data/demo_documents/` to reset.

2. **Option B: UI Case Creation**:
   - In the sidebar, click **➕ New Case Setup**.
   - Use a clear demo ID such as `case-demo-live-001`.
   - All cases in AdmitSense are completely isolated; creating new demo cases never mutates or affects other existing cases in the saved case list.

---

## 7. Known Limitations

- **Administrative Preparation Only**: The system does NOT represent an insurance company, TPA, or hospital desk. It does not submit claims, approve coverage, or confirm cashless admission.
- **Synthetic Hospital Directory**: Hospital matching uses a local synthetic dataset (`v2026.1`). Directory matches do not reflect real network agreements or live empanelment status.
- **Bounded Tool Budget**: Review runs are capped at 8 tool invocations. If evidence is deeply nested or requires exhaustive search, the agent stops with `stopped_reason = "tool_limit_reached"`, preserving validated partial results.
- **Unreadable PDFs**: Scanned receipts or image-only PDFs without an OCR layer produce extraction status `"unreadable"`. The system highlights this as an evidence gap rather than inventing findings.
