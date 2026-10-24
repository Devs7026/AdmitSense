Updated: 2026-10-24T15:35:00+05:30
Owner / task: OWNER A / M6-A & Interface/Export side of M6-I (Hospital Reference Display & Deterministic HTML Packet Export)
Branch / implementation commit or PR: feat/m6-hospital-and-packet-export
Delivery state: ready for review (awaiting teammate review and merge authorisation)
Implemented:
1. Hospital Information Display (`src/admitsense/documents/hospital_directory.py` & UI):
   - Created `LocalSyntheticHospitalDirectory` implementing `HospitalLookupService` protocol conforming to CONTRACTS.md Section 2.6 and Section 3.4.
   - Evaluates hospital facilities against dated synthetic demonstration records (`v2026.1`, `2026-10-01`).
   - Supports all 4 required matching states:
     - `matched`: Displays facility name, city, network tier (`tier_1`, `tier_2`, `non_network`), TPA contact, record ID, dataset version, and date.
     - `no_match`: Displays clear notice when a facility is not in the synthetic dataset.
     - `ambiguous_match`: Identifies multiple candidate facilities matching the query and prompts for exact name.
     - `missing_information`: Explains that hospital facility has not been entered in case details.
   - Non-Authorisation Invariant strictly enforced: Prominently displays notice that directory match does NOT verify live insurer network status, cashless eligibility, or claim approval.
   - Integrated into both `tab_facts` and `tab_export` in the Streamlit workspace view.

2. Review Packet Preview (`src/admitsense/ui/workspace_view.py`):
   - Implemented full `tab_export` ("📥 Review Packet Preview & Deterministic Export"):
     - Snapshot Version Selector: Allows caregivers to select which historical packet version (`v1`, `v2`, etc.) to inspect and export from SQLite storage.
     - Metadata Header: Packet ID, Version, Run ID, Generation Time, and Review Status badge.
     - Mandatory Authorisation Banner: Strictly defaults to `"not verified"` with domain boundary explanation.
     - Incomplete Review Warning: Prominently highlights partial execution stop reasons, stop details, and limitations.
     - Case & Admission Summary: Patient, policy ID, procedure, planned admission date, coverage start, estimated cost.
     - Synthetic Hospital Display: Live directory card showing status, tier, contact, and disclaimers.
     - Documents Reviewed: Table of reviewed files, versions, and extraction statuses.
     - Administrative Findings: Topic cards with revision badges, status, conclusion, next action, and exact blockquote physical page citations.
     - Missing Evidence Checklist: Table of requested items, rationale, suggested sources, and resolution statuses.
     - Questions for Hospital Admission Desk & Insurer: Concrete actionable questions list for desk staff and TPA.
     - Revision Audit Trail: Full chronological history of finding revisions, trigger types, and triggering evidence quotes.

3. Deterministic HTML Packet Download (`src/admitsense/export/html_exporter.py`):
   - Implemented pure function `generate_review_packet_html`:
     - Renders a standalone, self-contained HTML5 document directly from a saved `ReviewPacket` snapshot.
     - Deterministic export: ZERO live model calls, reassessments, or database writes during generation.
     - Security: Complete HTML escaping (`html.escape`) of all dynamic user, document, model, and hospital strings (safe against script injection / XSS).
     - Export Safety: No secrets, machine paths (`C:\Users\`, `/tmp/`), or local `file:///` URLs.
     - Modern Styling: Clean typography, status color badges, responsive layout, and dedicated `@media print` stylesheet for clean printing / PDF saving.
     - Download Button: `st.download_button` generating `review_packet_{case_id}_v{packet_version}.html`. Preview and download strictly represent the exact same packet version.

Interfaces changed:
- Added `HospitalRecordReference` schema in `src/admitsense/schemas.py`.
- Added optional `hospital_record: HospitalRecordReference | None = None` to `ReviewPacket` in `src/admitsense/schemas.py`.
- Added module `src/admitsense/documents/hospital_directory.py` exporting `HospitalMatchStatus`, `HospitalLookupResult`, `HospitalLookupService`, and `LocalSyntheticHospitalDirectory`.
- Added module `src/admitsense/export/html_exporter.py` and exported `generate_review_packet_html` in `src/admitsense/export/__init__.py`.
- Updated `docs/CONTRACTS.md` adding Section 2.6 and marking Section 3.4 as AGREED.

Checks and results:
- `pytest tests/test_m6_export.py -v` -> 7/7 passed in 0.55s:
  - Export is deterministic and contains complete snapshot data.
  - Special characters and script tags escaped safely.
  - Zero secrets, internal paths, or broken links in export.
  - Incomplete packets retain visible limitations and stop reasons.
  - Historical packets retain original findings across subsequent revisions.
  - Hospital directory states (matched, no_match, ambiguous, missing) and synthetic disclaimers verified.
  - Authorization status strictly remains 'not verified'.
- `python tests/verify_m6.py` -> 9/9 verification checks passed:
  - Hospital directory lookup states verified.
  - Synthetic dataset transparency and non-authorisation disclaimer present.
  - Snapshot construction with findings, citations, checklist, questions, and revisions verified.
  - Deterministic HTML generation verified.
  - Complete HTML escaping verified.
  - Export safety (no internal paths or file:// links) verified.
  - Incomplete review export with visible limitations verified.
  - Historical packet snapshot immutability verified.
  - Standalone HTML document structure valid.
- `pytest` (full test suite) -> 114/114 passed across entire repository in 15.17s.
- Milestone regression scripts:
  - `python tests/verify_m1.py` -> 5/5 passed.
  - `python tests/verify_m2.py` -> 8/8 passed.
  - `python tests/verify_m3.py` -> 8/8 passed.
  - `python tests/verify_m4.py` -> 15/15 passed.
  - `python tests/verify_m5.py` -> 16/16 passed.
  - `python tests/verify_m6.py` -> 9/9 passed.

Mocks / limitations / blockers:
- Owner A interface & export side is complete without mocks.
- `LocalSyntheticHospitalDirectory` provides the agreed directory lookup adapter for UI preview and export.
- Did not implement Owner B's review runner lookup tool or question-generation logic (`M6-B`).

Next action for other owner (Owner B):
- Implement M6-B in `src/admitsense/agent/review.py`:
  - Hospital lookup tool (`lookup_hospital`) providing `HospitalRecordReference` with synthetic record ID, dataset version (`v2026.1`), and publication date (`2026-10-01`).
  - Structured desk questions generation for admission desk and insurer.
  - Validate output wording for limitations and unresolved conditions.
  - When integrated, `generate_review_packet_html` and the workspace preview will seamlessly render Owner B's live hospital lookups and desk questions from the persisted packet.
