Updated: 2026-10-24T14:45:00+05:30
Owner / task: OWNER B / M5-B & M5-I (Review Engine Side)
Branch / implementation commit or PR: main (merged from feat/m5-replay-engine at commit abaa7bc)
Delivery state: integrated and verified on main (all 13 pytest tests and 16 combined acceptance checks passing)

Implemented:
1. Applicability Checks:
   - Evaluates policy identity (`e_policy_id == case.policy_id`), member scope (`e_member_name == case.member_name`), and effective dates relative to the case (`e_effective_from <= case.planned_admission_date`).
   - If policy ID or member name does not match, sets `status="not_applicable"` citing the document, preserving base policy terms.
   - If effective date is after planned admission date, sets `status="not_applicable"` with explicit explanation; terms do not apply to this admission.
   - If precedence language is ambiguous (e.g., contradictory terms or pending underwriter review) or admission date is unknown for a future effective date, sets `status="uncertain"` and creates a finding with `status="conflict"`.
   - Never assumes a newer upload automatically overrides earlier evidence.
   - Never infers authenticity merely from matching metadata.
   - Retains uncertainty whenever applicability cannot be established.
   - Evaluates each endorsement record and produces validated `DocumentApplicability` records.

2. Impact Detection:
   - Identifies findings that depend on changed evidence or case facts.
   - Inspects for newly introduced conditions or conflicts.
   - Preserves unrelated findings from prior packets without incrementing their revision numbers.
   - Supports planned admission date and other case-fact corrections (`trigger_type="case_details_changed"` or `"user_correction"`).

3. Reassessment Engine (`compute_evidence_replay`):
   - Accepts snapshot of `prior_packet`, candidate `new_findings`, `trigger_type`, `triggering_evidence`, `changed_case_facts`, and `reason`.
   - Preserves stable finding IDs across runs (`finding_id` remains constant).
   - Increments a finding's revision number by exactly 1 only for substantive changes (conclusion, status, evidence citations, or next action).
   - Avoids revisions caused solely by duplicate input or model paraphrasing (retains prior revision number; does not create redundant `Revision` records).
   - Emits structured `Revision` records containing `revision_id`, `finding_id`, `old_finding_revision`, `new_finding_revision`, `old_conclusion`, `new_conclusion`, `old_status`, `new_status`, `trigger_type`, `triggering_evidence`, `changed_case_facts`, `reason`, and `affected_topics`.
   - Pure review engine: does NOT write directly to SQLite storage; returns results through agreed interfaces for Owner A's transactional persistence.

4. Updated Next Actions:
   - Rebuilds checklist items from current findings.
   - Resolves a missing-evidence item only when supplied evidence actually answers it (e.g. applicable endorsement resolves waiting period shortfall checklist item).
   - Keeps unrelated unresolved items visible in the checklist.
   - Does NOT interpret one resolved condition as overall coverage approval: authorization strictly remains `"not verified"`, with no overall approval claims.

5. M4 Guarantees Preserved:
   - Reassessment executes through existing bounded execution (`BoundedReviewAgent`).
   - Tool budget (maximum 8 calls per run) strictly enforced before dispatch.
   - Timeout handling and honest incomplete reporting preserved (`stopped_reason="timeout"`).
   - Clearly identifies findings awaiting reassessment if a run stops early (`"Reassessment pending: review run stopped before this topic could be re-evaluated"` in limitations).

Exact Interface for Owner A (Section 3.5 in CONTRACTS.md):
```python
from admitsense.agent import BoundedReviewAgent, compute_evidence_replay
from admitsense.schemas import CaseDetails, ReviewPacket, Finding, Revision

# 1. Bounded review replay execution:
agent = BoundedReviewAgent(default_tool_budget=8, default_timeout_seconds=30.0)
packet: ReviewPacket = agent.run_review(
    case=case,                     # CaseDetails from CaseRepository
    retrieval=retrieval,           # EvidenceRetrievalService
    prior_packet=latest_packet,    # None for initial run; prior ReviewPacket snapshot for replay
    user_answers=user_answers,     # Optional dict of caregiver answers / decline flags
    event_callback=on_tool_event,  # Optional live ToolActivityEvent callback
)

# 2. Direct replay computation function (pure review engine):
final_findings, accumulated_revisions = compute_evidence_replay(
    prior_packet=latest_packet,
    new_findings=reassessed_findings,
    trigger_type="new_document",   # Literal["new_document", "user_correction", "case_details_changed"]
    triggering_evidence=new_evidence_list,
    changed_case_facts=[],
    reason="Applicable endorsement reduces waiting period to 12 months.",
)
```

Sample Replay Outputs:

Sample `Revision` Record (JSON):
```json
{
  "revision_id": "rev-9b1c2d3e",
  "finding_id": "find-waiting-period-total-knee-replacement",
  "old_finding_revision": 1,
  "new_finding_revision": 2,
  "old_conclusion": "Policy terms impose a specific waiting period of 24 continuous months for treatment of Total Knee Replacement. Available records document 18 months of continuous coverage, leaving a 6-month shortfall before the waiting period is satisfied.",
  "new_conclusion": "Policy terms specify a waiting period of 12 continuous months for treatment of Total Knee Replacement under Endorsement Schedule EW-2025-01 (modifying Section 4.2(b)). Available records document 18 months of continuous coverage, satisfying this specific waiting period.",
  "old_status": "unresolved",
  "new_status": "supported",
  "trigger_type": "new_document",
  "triggering_evidence": [
    {
      "document_id": "doc-policy_endorsement_schedule_ew-2025-01",
      "document_version": "v1",
      "page": 1,
      "quote": "Waiting Period Modification: The specific waiting period for degenerative joint disorders and joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months to twelve (12) continuous months.",
      "evidence_type": "endorsement"
    }
  ],
  "changed_case_facts": [],
  "reason": "Applicable endorsement schedule matches policy ID and member, effective prior to planned admission.",
  "affected_topics": [
    "Specific Condition Waiting Period: Total Knee Replacement"
  ],
  "created_at": "2026-10-24T14:20:00Z"
}
```

Sample `DocumentApplicability` Record (JSON):
```json
{
  "document_id": "doc-policy_endorsement_schedule_ew-2025-01",
  "document_version": "v1",
  "policy_id": "POL-998877",
  "member_name": "Ramesh Sharma",
  "effective_from": "2025-04-01",
  "status": "applicable",
  "evidence": [
    {
      "document_id": "doc-policy_endorsement_schedule_ew-2025-01",
      "document_version": "v1",
      "page": 1,
      "quote": "Waiting Period Modification: The specific waiting period for degenerative joint disorders and joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months to twelve (12) continuous months.",
      "evidence_type": "endorsement"
    }
  ],
  "reason": "Endorsement schedule matches policy ID 'POL-998877', member 'Ramesh Sharma', and is effective (2025-04-01) prior to planned admission.",
  "modified_topics": [
    "Specific Condition Waiting Period: Joint Replacement"
  ]
}
```

Integration Instructions for Owner A (M5-A / M5-I Persistence & UI):
1. In `ReviewService.execute_review` / `ReviewService.resume_review`:
   - Fetch the latest persisted `ReviewPacket` for the case from `ReviewRepository.get_latest_review_packet(case_id)`.
   - Pass `prior_packet=latest_packet` into `BoundedReviewAgent.run_review(...)`.
   - Persist the newly generated `ReviewPacket` snapshot (including its updated `findings`, `revisions`, `document_applicability`, and `missing_evidence_checklist`) transactionally to SQLite storage via `ReviewRepository.save_review_packet(packet)`.
2. Workspace UI (Streamlit):
   - Render finding cards with their stable finding IDs and current revision badges (e.g. `v2`).
   - If a finding has revision history in `packet.revisions`, render a collapsible "Revision Audit Trail" showing old vs. new conclusion, status change, triggering document quote, and trigger reason.
   - Render a "Document Applicability" section displaying evaluated endorsements with badges (`applicable` green, `not_applicable` gray, `uncertain` amber) and rationale.
   - Retain unchanged findings and unrelated unresolved checklist items visibly.
   - Authorization status remains strictly `"not verified"` banner.

Checks and results:
- `pytest -v tests/test_m5_replay.py` -> 8/8 passed in 2.44s:
  - Applicable endorsement changes 24 months to 12 months and keeps narrow scope.
  - Supplied 18-month history supports only the relevant narrow finding.
  - Wrong policy ID does not override base policy.
  - Endorsement effective after planned admission date does not silently apply.
  - Ambiguous precedence produces an unresolved/conflict finding.
  - Unrelated findings remain unchanged across replay.
  - Duplicate input does not create duplicate substantive revisions.
  - Corrected case date triggers reassessment of dependent findings.
  - Failed/partial reassessment does not falsely report completion.
- `python tests/verify_m5.py` -> 9/9 verification checks passed.
- `pytest` -> 102/102 passed across entire repository (100% test pass in 12.05s).
- `python tests/verify_m1.py` -> 5/5 passed.
- `python tests/verify_m2.py` -> 8/8 passed.
- `python tests/verify_m3.py` -> 8/8 passed.
- `python tests/verify_m4.py` -> 15/15 passed.

Limitations & Delivery State:
- Pure review engine returned to caller; persistence responsibility resides with Owner A's `ReviewRepository` / `ReviewService`.
- Milestone M5-B and M5-I review-engine side complete and verified on `feat/m5-replay-engine`.
- Ready for Owner A's M5-A UI/persistence integration.
