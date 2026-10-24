Updated: 2026-10-24T15:55:00+05:30
Owner / task: OWNER B / M6-B & M6-I (Review Engine & Data Packaging Integration)
Branch / implementation commit or PR: main (integrated from feat/m6-hospital-and-questions)
Delivery state: integrated and verified on main (all 128 pytest tests, 21 verify_m6 checks, and all milestone verification suites passing)

Implemented:

1. Synthetic Hospital Lookup (`src/admitsense/agent/hospital.py`):
   - `HospitalLookupService` searches dated, versioned local JSON dataset (`data/hospitals/synthetic_hospitals.json` or `tests/fixtures/synthetic/hospitals_synthetic_v2026.json`).
   - Returns stable record ID (`hosp-synth-001`), dataset version (`v2026.1`), and dataset publication date (`2026-10-01`).
   - Explicitly flags all hospital records with `is_synthetic=True` and synthetic demonstration disclaimers.
   - Handles missing inputs (`missing_input`), no matches (`no_match`), and ambiguous candidates (`ambiguous_match`) explicitly; NEVER silently selects an uncertain candidate.
   - Directory references are strictly separated from PDF page citations (`HospitalRecordReference` vs `Evidence`).
   - Enforces key invariant: directory records NEVER imply active insurer empanelment, cashless guarantee, or claim pre-authorization.

2. Bounded Agent Review Integration (`src/admitsense/agent/review.py`):
   - Integrated `lookup_hospital` as an explicit agent tool within `BoundedReviewAgent.run_review`.
   - Tool execution strictly consumes from the bounded 8-call budget (`step_number=1`), emitting a structured `ToolActivityEvent`.
   - Attaches the resulting `HospitalRecordReference` (with match status, metadata, and limitations) directly to `ReviewPacket.hospital_reference`.
   - Lookup failure or ambiguity does NOT create a false positive finding; limitations are preserved on the review packet.
   - Preserves earlier findings and revision history across replays.

3. Actionable Desk & Insurer Questions (`src/admitsense/agent/questions.py`):
   - Implemented `derive_desk_and_insurer_questions(findings, checklist, case, hospital_ref)`:
     - Derives specific, actionable questions linked to unresolved findings (e.g., waiting period shortfalls, ambiguous endorsements, missing procedures/diagnoses, unverified hospitals).
     - Dynamically prunes obsolete questions when supporting evidence resolves the underlying issue (e.g., when an applicable endorsement satisfies a waiting period shortfall, the waiting period question is automatically removed).
     - Keeps remaining unresolved evidence gaps visible.
     - Never invents mandatory document requirements or implies coverage pre-authorization.

4. Deterministic Export-Ready Data (`src/admitsense/review/export_data.py`):
   - Implemented `build_review_export_payload(packet, case)`:
     - Pure deterministic dictionary builder consuming a saved `ReviewPacket` snapshot.
     - Zero live model execution or network calls during export generation.
     - Preserves review status, stopped reasons, incomplete states, and pending-reassessment limitations.
     - Structures sections: case metadata, review summary, authorization banner, hospital reference, findings, checklist items, desk questions, and revision history audit trail.
   - Implemented `escape_html(text)` utility to protect against XSS injection in Owner A's self-contained HTML export view.

Exact Interfaces for Owner A (Section 3.4 in CONTRACTS.md):

```python
from admitsense.agent import HospitalLookupService, derive_desk_and_insurer_questions
from admitsense.review import build_review_export_payload, escape_html
from admitsense.schemas import (
    HospitalLookupResult,
    HospitalRecordReference,
    ReviewPacket,
)

# 1. Direct hospital lookup:
service = HospitalLookupService()
result: HospitalLookupResult = service.lookup(
    hospital_name="Apex Multi-Speciality Hospital",
    city="Mumbai",
)
# result.status: "exact_match" | "ambiguous_match" | "no_match" | "missing_input"
# result.hospital: HospitalRecordReference | None

# 2. Derive actionable desk & insurer questions:
questions: list[str] = derive_desk_and_insurer_questions(
    findings=packet.findings,
    checklist=packet.missing_evidence_checklist,
    case=case,
    hospital_ref=packet.hospital_reference,
)

# 3. Deterministic export payload from saved ReviewPacket snapshot:
export_payload: dict[str, Any] = build_review_export_payload(
    packet=packet,
    case=case,
)
```

Sample Hospital Reference Record (`ReviewPacket.hospital_reference`):
```json
{
  "record_id": "hosp-synth-001",
  "dataset_version": "v2026.1",
  "dataset_date": "2026-10-01",
  "hospital_name": "Apex Multi-Speciality Hospital",
  "city": "Mumbai",
  "network_tier": "tier_1",
  "tpa_desk_contact": "tpa-desk@apex-synthetic.local",
  "is_synthetic": true,
  "limitations": [
    "SYNTHETIC DEMONSTRATION RECORD: Valid for testing and evaluation purposes only.",
    "Does not establish current insurer network agreement, cashless eligibility, or pre-authorisation."
  ]
}
```

Sample Export Payload (`export_payload` dictionary):
```json
{
  "export_meta": {
    "generated_at": "2026-10-24T15:20:00Z",
    "generator": "AdmitSense Deterministic Review Exporter",
    "schema_version": "1.0"
  },
  "case": {
    "case_id": "case-synth-101",
    "member_name": "Ramesh Sharma",
    "policy_id": "POL-998877",
    "hospital_name": "Apex Multi-Speciality Hospital",
    "city": "Mumbai",
    "planned_admission_date": "2026-11-01"
  },
  "review": {
    "packet_id": "pkt-rev-001",
    "review_version": 1,
    "review_status": "complete",
    "authorization_status": "not verified",
    "authorization_banner": "Insurer pre-authorisation is NOT VERIFIED. Directory and policy findings do not guarantee cashless admission or claim approval.",
    "stopped_reason": null,
    "hospital": {
      "record_id": "hosp-synth-001",
      "dataset_version": "v2026.1",
      "dataset_date": "2026-10-01",
      "hospital_name": "Apex Multi-Speciality Hospital",
      "city": "Mumbai",
      "network_tier": "tier_1",
      "is_synthetic": true,
      "limitations": [
        "SYNTHETIC DEMONSTRATION RECORD: Valid for testing and evaluation purposes only.",
        "Does not establish current insurer network agreement, cashless eligibility, or pre-authorisation."
      ]
    },
    "findings": [
      {
        "finding_id": "find-waiting-period-total-knee-replacement",
        "topic": "Specific Condition Waiting Period: Total Knee Replacement",
        "status": "supported",
        "conclusion": "Policy terms specify a waiting period of 12 continuous months for treatment of Total Knee Replacement under Endorsement Schedule EW-2025-01. Available records document 18 months of continuous coverage, satisfying this specific waiting period.",
        "revision": 2,
        "evidence": [
          {
            "document_id": "doc-policy_endorsement_schedule_ew-2025-01",
            "document_version": "v1",
            "page": 1,
            "quote": "The specific waiting period for degenerative joint disorders and joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months to twelve (12) continuous months."
          }
        ]
      }
    ],
    "unresolved_questions": [
      "Desk Question [General Pre-Authorization]: Request written cashless pre-authorisation from insurer for planned admission on 2026-11-01 at Apex Multi-Speciality Hospital."
    ],
    "revisions": [
      {
        "revision_id": "rev-9b1c2d3e",
        "finding_id": "find-waiting-period-total-knee-replacement",
        "old_finding_revision": 1,
        "new_finding_revision": 2,
        "reason": "Applicable endorsement schedule matches policy ID and member, effective prior to planned admission."
      }
    ]
  }
}
```

Integration Instructions for Owner A (M6-A UI & HTML Export):
1. Workspace Display (`src/admitsense/ui/workspace_view.py`):
   - Inspect `packet.hospital_reference`.
   - Render the dated synthetic hospital card with:
     - Stable ID badge (`hosp-synth-001`), dataset version (`v2026.1`), and publication date (`2026-10-01`).
     - Explicit warning banner: "Synthetic demonstration record — does not verify live network empanelment or cashless guarantee".
   - If `packet.hospital_reference` has limitations or non-exact match status, render the explicit match explanation (e.g., "Ambiguous match: multiple synthetic facilities match...").
   - Display actionable questions in a dedicated "Desk & Insurer Questions" section.
2. Self-Contained HTML Export (`src/admitsense/ui/export_view.py`):
   - Fetch saved `ReviewPacket` snapshot from `ReviewRepository.get_latest_review_packet(case_id)`.
   - Call `build_review_export_payload(packet, case)` to obtain the export data dictionary.
   - Render self-contained HTML report with embedded CSS styling:
     - Wrap dynamic text fields with `escape_html(val)` to prevent HTML/XSS injection.
     - Include packet ID, review version, generated timestamp, hospital metadata, findings with PDF citations, checklist, actionable desk questions, and revision history.
     - Keep the prominent "Pre-Authorisation: NOT VERIFIED" disclaimer banner at the top of the report.
   - Provide "Download HTML Report" button delivering the generated HTML file.

Verification Results:
- `pytest tests/test_m6_hospital_and_export.py -v`: 14/14 tests passed in 1.47s:
  - `test_exact_hospital_match_returns_stable_metadata_and_synthetic_flag`
  - `test_no_match_returns_no_match_status_and_no_positive_claim`
  - `test_ambiguous_hospital_name_does_not_silently_select`
  - `test_missing_hospital_input_returns_missing_input_status`
  - `test_invalid_dataset_metadata_raises_value_error`
  - `test_hospital_record_never_infers_cashless_or_approval`
  - `test_hospital_references_separated_from_pdf_citations`
  - `test_agent_invoked_hospital_lookup_bounded_execution`
  - `test_agent_hospital_lookup_failure_does_not_create_false_positive_finding`
  - `test_actionable_desk_questions_derived_from_unresolved_findings`
  - `test_resolved_evidence_gap_prunes_obsolete_question`
  - `test_unresolved_gaps_remain_visible_in_questions`
  - `test_export_payload_pure_snapshot_without_model_invocation`
  - `test_export_payload_preserves_incomplete_and_pending_reassessment`
- `python tests/verify_m6.py`: 12/12 verification checks passed:
  - 1. Synthetic dataset presence & version validation
  - 2. Exact hospital lookup with stable ID and synthetic disclaimer
  - 3. Ambiguous hospital match handling (refuses silent selection)
  - 4. No-match hospital handling
  - 5. Missing hospital input handling
  - 6. Invariant check: no network/cashless claims from directory
  - 7. PDF citations decoupled from hospital references
  - 8. Bounded execution with lookup_hospital tool within budget (<= 8 calls)
  - 9. Question derivation from unresolved findings & missing facts
  - 10. Obsolete question removal on issue resolution
  - 11. Deterministic export payload generation from saved snapshot
  - 12. Incomplete and timeout review states preserved in export
- Full repository regression:
  - `pytest`: 128/128 tests passed in 13.62s across all test suites.
  - Acceptance suites: `verify_m1.py` (5/5), `verify_m2.py` (8/8), `verify_m3.py` (8/8), `verify_m4.py` (15/15), `verify_m5.py` (16/16), `verify_m6.py` (21/21).

Limitations & Delivery State:
- Milestone M6-B and M6-I completely implemented, integrated with Owner A's M6-A HTML exporter, and verified on main.
- Review export consumes static snapshots without model invocation; HTML rendering and download button verified in UI and tests.
- Milestone M7 has NOT been started.
