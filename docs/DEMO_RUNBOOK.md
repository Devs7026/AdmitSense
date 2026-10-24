# AdmitSense — Demonstration Runbook

This runbook provides step-by-step instructions, inputs, and expected observable results for rehearsing and presenting the three required demonstration stories.

---

## Preparation & Clean Setup

1. Start the Streamlit application:
   ```powershell
   .\.venv\Scripts\streamlit.exe run src/admitsense/app.py
   ```
2. Open **`http://localhost:8501`** in a clean browser window.
3. In the sidebar, click **➕ New Case Setup**.

---

## Story 1: Applicable Endorsement Flow

> **Caregiver Persona**: Savitri is preparing for Ramesh's planned Total Knee Replacement. His policy wording requires a 24-month waiting period, but he was issued a special endorsement reducing it to 12 months.

### Step 1: Create Case Details
1. In the **Case Setup** view, enter:
   - **Case ID**: `case-demo-story1`
   - **Member Name**: `Ramesh Sharma`
   - **Policy ID**: `POL-998877`
   - **Procedure**: `Total Knee Replacement`
   - **Planned Admission Date**: `2026-11-20`
   - **Coverage Start Date**: `2025-05-20` (18 months of coverage prior to admission)
   - **Hospital Name**: `Apex Super Specialty Hospital`
   - **Estimated Cost**: `250000` (optional)
2. Click **Create Case**.
3. **Observable Result**: The app navigates to the Case Workspace with active case ID `case-demo-story1`. In the Overview tab, patient details are displayed with `"user_provided"` fact provenance badges.

### Step 2: Ingest Base Policy & Renewal Schedule
1. Click the **📄 Documents** tab.
2. In the upload area, upload two files from `tests/fixtures/synthetic/`:
   - `Care_Health_Gold_Policy_Wording.pdf` (evidence type: `policy_wording`)
   - `Policy_Renewal_Schedule.pdf` (evidence type: `policy_schedule`)
3. Click **Process & Ingest Uploaded Documents**.
4. **Observable Result**:
   - Both documents are extracted with status `[extracted]`.
   - `Care_Health_Gold_Policy_Wording.pdf` displays `15 pages`.
   - Clicking on a document opens the physical 1-based page viewer.

### Step 3: Run Baseline Review
1. Click the **🔍 Review & Findings** tab.
2. Click **🚀 Run Comprehensive Review**.
3. **Observable Result**:
   - Live Tool Activity stream displays bounded tool executions (<= 8 calls).
   - Review completes with status **`INCOMPLETE (missing_information)`**.
   - Mandatory Authorisation Banner strictly displays: **`NOT VERIFIED`**.
   - Finding card: **Waiting Period (Joint Replacement)** has status **`⚠️ UNRESOLVED`** (Revision 1).
   - Finding citations link to physical **Page 14** of `Care_Health_Gold_Policy_Wording.pdf`:
     > *"Section 4.2(b): Treatment for degenerative joint disorders including total knee replacement is covered subject to a specific waiting period of twenty-four (24) continuous months..."*
   - Limitations clearly explain: *Supplied continuous coverage (18 months) is less than the 24-month waiting period.*
   - Missing evidence checklist requests: *Endorsement schedule or prior policy proof.*

### Step 4: Upload Applicable Endorsement & Reassess
1. Navigate back to the **📄 Documents** tab.
2. Upload: `Joint_Replacement_Endorsement.pdf` (evidence type: `endorsement`).
3. Click **Process & Ingest Uploaded Documents**.
4. **Observable Result**: Document table now displays 3 files; earlier versions remain untouched.
5. Return to **🔍 Review & Findings** and click **🔄 Reassess Review with New Evidence**.

### Step 5: Verify Evidence Change Replay & Updated Export
1. **Observable Result**:
   - Packet version increments to **`v2`**.
   - The finding **Waiting Period (Joint Replacement)** updates to **`✅ SUPPORTED`** (Revision 2).
   - **Evidence Change Replay** card highlights before-and-after change:
     - Old: `⚠️ UNRESOLVED` (Rev 1)
     - New: `✅ SUPPORTED` (Rev 2)
     - Trigger: `New Document (Joint_Replacement_Endorsement.pdf)`
     - Triggering Quote: *"Waiting Period Modification: The specific waiting period for degenerative joint disorders... is reduced from twenty-four (24) continuous months to twelve (12) continuous months."*
   - Obsolete waiting period questions are dynamically removed from desk questions.
2. Click the **📥 Review Packet Preview & Export** tab:
   - Historical packet selector allows toggling between **Version 1** and **Version 2**.
   - Version 1 snapshot preserves original `UNRESOLVED` finding permanently.
   - Version 2 displays `SUPPORTED` finding, synthetic hospital card for `Apex Super Specialty Hospital` (Tier 1), and dynamic desk questions.
3. Click **⬇️ Download Review Packet (.html)**:
   - Opens independently in any web browser without server connection.
   - Print-ready CSS formatting (`Ctrl+P`).
   - Zero local filesystem paths or machine secrets.

---

## Story 2: Mismatched / Conflicting Evidence Flow

> **Caregiver Persona**: An endorsement is provided, but it contains contradictory language or was issued for a different policy ID, requiring honest preservation of uncertainty.

### Step 1: Create Case Details
1. Click **➕ New Case Setup**.
2. Enter:
   - **Case ID**: `case-demo-story2`
   - **Member Name**: `Ramesh Sharma`
   - **Policy ID**: `POL-998877`
   - **Procedure**: `Total Knee Replacement`
   - **Planned Admission Date**: `2026-11-20`
3. Click **Create Case**.

### Step 2: Upload Documents with Conflicting Endorsement
1. In the **📄 Documents** tab, upload:
   - `Care_Health_Gold_Policy_Wording.pdf`
   - `Policy_Renewal_Schedule.pdf`
2. Next, upload an endorsement containing unresolved precedence or mismatched terms:
   - In synthetic tests, this schedule specifies: *"Waiting period modified to 12 months, however precedence unresolved: terms conflict with master policy schedule pending underwriter review."*
3. Click **Process & Ingest Uploaded Documents**.

### Step 3: Run Review & Observe Conflict Handling
1. In **🔍 Review & Findings**, click **🚀 Run Comprehensive Review**.
2. **Observable Result**:
   - Review completes with status **`INCOMPLETE (conflicting_evidence)`**.
   - Finding card displays status **`⚡ CONFLICT`**.
   - Conclusion states: *Endorsement terms conflict with master policy wording; precedence is unresolved.*
   - The system does **NOT** silently override the base terms or invent an approval waiver.
   - Unresolved questions section contains actionable queries for the insurer:
     - *"Does endorsement schedule EW-2025-01 take precedence over master policy schedule?"*
   - Authorisation remains strictly **`NOT VERIFIED`**.

---

## Story 3: Unreadable PDF & Partial Workflow Flow

> **Caregiver Persona**: A caregiver uploads a photographed hospital bill or corrupted scanned receipt that has no readable text.

### Step 1: Create Case Details
1. Click **➕ New Case Setup**.
2. Enter:
   - **Case ID**: `case-demo-story3`
   - **Member Name**: `Sunil Dutt`
   - **Procedure**: `Total Knee Replacement`
3. Click **Create Case**.

### Step 2: Upload Unreadable Scanned File
1. In **📄 Documents**, upload `Scanned_Receipt_Unreadable.pdf` from `tests/fixtures/synthetic/`.
2. Click **Process & Ingest Uploaded Documents**.
3. **Observable Result**:
   - The extraction status is explicitly flagged as **`[unreadable]`** or **`[error]`** (0 pages extracted).
   - The UI displays an alert: *No readable text could be extracted from this scanned or image-only file.*

### Step 3: Run Review & Verify Partial Results
1. In **🔍 Review & Findings**, click **🚀 Run Comprehensive Review**.
2. **Observable Result**:
   - The system executes safely without crashing.
   - Zero fabricated findings: the agent does NOT invent coverage, room rent limits, or exclusions for unreadable documents.
   - Review status displays **`INCOMPLETE (missing_information)`**.
   - Missing-evidence checklist flags: *Please upload a clear, text-searchable digital PDF of policy wording.*
   - Caregivers can still use the rest of the workspace (Hospital lookup, Case details).

---

## Summary Checklist for Demonstration Rehearsal

- [ ] All 3 cases tested independently without cross-case data leakage.
- [ ] Physical 1-based page 14 citation opened and verified.
- [ ] Evidence Change Replay verified before and after endorsement upload.
- [ ] Downloaded HTML packet opens in Chrome/Edge/Firefox and displays cleanly.
- [ ] Authorization status confirmed as "not verified" across all views.
- [ ] Synthetic hospital directory transparency disclaimers visible.
