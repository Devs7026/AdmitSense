"""Development test fixtures representing sample review outputs for AdmitSense.

DISCLAIMER:
These fixtures are explicitly labelled development fixtures for UI prototyping,
contract validation, and testing. They DO NOT represent actual agent execution
or evidence that the review engine has been implemented.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from admitsense.schemas import (
    CaseDetails,
    DocumentApplicability,
    Evidence,
    FactSource,
    Finding,
    MissingEvidenceItem,
    ReviewPacket,
    Revision,
)


def _dt(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ==============================================================================
# Fixture 1: Incomplete review with missing evidence
# ==============================================================================
SAMPLE_INCOMPLETE_REVIEW_PACKET = ReviewPacket(
    packet_id="pkt-fixture-incomplete-001",
    packet_version=1,
    run_id="run-fixture-001",
    generated_at=_dt(2026, 10, 24, 10, 0),
    review_status="incomplete",
    case=CaseDetails(
        case_id="case-fixture-001",
        member_name="Aarav Sharma",
        policy_id="POL-7026-MED",
        procedure="Inguinal Hernia Repair",
        planned_admission_date=date(2026, 11, 15),
        hospital_name="City Care Hospital",
        # Missing facts remain None per product invariants:
        policy_start_date=None,
        continuous_coverage_start_date=None,
        policy_age_months=None,
        estimated_cost=None,
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "planned_admission_date": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
        },
    ),
    document_applicability=[
        DocumentApplicability(
            document_id="doc-base-policy-001",
            document_version="v1",
            policy_id="POL-7026-MED",
            status="applicable",
            reason="Policy schedule matches policy ID POL-7026-MED.",
            evidence=[
                Evidence(
                    document_id="doc-base-policy-001",
                    document_version="v1",
                    page=1,
                    quote="Health Shield Policy Schedule: Policy Number POL-7026-MED issued to Aarav Sharma.",
                    evidence_type="policy_schedule",
                )
            ],
        )
    ],
    findings=[
        Finding(
            finding_id="find-waiting-period-hernia",
            revision=1,
            topic="Specific Condition Waiting Period (Hernia)",
            status="unresolved",
            conclusion=(
                "Hernia surgery has a 24-month specific waiting period under Section 4.2. "
                "Because policy inception date or continuous coverage start date is not documented, "
                "waiting period compliance cannot be determined."
            ),
            evidence=[
                Evidence(
                    document_id="doc-base-policy-001",
                    document_version="v1",
                    page=8,
                    quote="Section 4.2: A waiting period of twenty-four (24) consecutive months of continuous coverage shall apply to the treatment of all types of Hernia, Hydrocele, and Piles.",
                    evidence_type="policy_wording",
                )
            ],
            relevant_case_facts=["procedure", "policy_id"],
            missing_facts=["continuous_coverage_start_date", "policy_start_date"],
            limitations=[
                "User has not provided inception date or prior continuous coverage certificate.",
                "Base policy terms confirm the 24-month waiting rule, but elapsed duration remains unknown."
            ],
            next_action="Obtain prior insurance policy schedules or continuity certificate to prove elapsed coverage.",
            created_at=_dt(2026, 10, 24, 10, 1),
        )
    ],
    revisions=[],
    missing_evidence_checklist=[
        MissingEvidenceItem(
            item_id="chk-hernia-coverage-dates",
            related_finding_ids=["find-waiting-period-hernia"],
            requested_information="Continuous coverage certificate or previous policy renewal schedule",
            why_it_matters=(
                "Section 4.2 imposes a 24-month waiting period for hernia surgery. "
                "Evidence of continuous coverage from prior renewals or porting is needed to verify eligibility."
            ),
            suggested_source="Insurance policy schedule, renewal certificate, or broker portal",
            status="requested",
        )
    ],
    unresolved_questions=[
        "When was policy POL-7026-MED originally issued, or what was the continuous coverage inception date?",
    ],
    authorization_status="not verified",
    authorization_evidence=[],
    tool_steps_used=2,
    stopped_reason="missing_information",
    stop_details="Awaiting continuous coverage inception date to determine 24-month hernia waiting period satisfaction.",
)


# ==============================================================================
# Fixture 2: Supported finding with a citation
# ==============================================================================
SAMPLE_SUPPORTED_FINDING_PACKET = ReviewPacket(
    packet_id="pkt-fixture-supported-002",
    packet_version=1,
    run_id="run-fixture-002",
    generated_at=_dt(2026, 10, 24, 11, 0),
    review_status="complete",
    case=CaseDetails(
        case_id="case-fixture-002",
        member_name="Sunita Patel",
        policy_id="POL-9941-STAR",
        policy_start_date=date(2023, 6, 1),
        continuous_coverage_start_date=date(2023, 6, 1),
        policy_age_months=40,
        planned_admission_date=date(2026, 10, 30),
        procedure="Cataract Surgery with Phacoemulsification",
        hospital_name="Apex Eye Institute",
        estimated_cost=Decimal("45000.00"),
        currency="INR",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "planned_admission_date": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
            "policy_start_date": FactSource(
                source_type="document",
                evidence=[
                    Evidence(
                        document_id="doc-schedule-9941",
                        document_version="v1",
                        page=1,
                        quote="Policy Inception Date: 01-Jun-2023. Continuous Coverage Date: 01-Jun-2023.",
                        evidence_type="policy_schedule",
                    )
                ],
            ),
            "continuous_coverage_start_date": FactSource(
                source_type="document",
                evidence=[
                    Evidence(
                        document_id="doc-schedule-9941",
                        document_version="v1",
                        page=1,
                        quote="Policy Inception Date: 01-Jun-2023. Continuous Coverage Date: 01-Jun-2023.",
                        evidence_type="policy_schedule",
                    )
                ],
            ),
            "policy_age_months": FactSource(
                source_type="derived",
                explanation="Calculated from continuous coverage start date (2023-06-01) to planned admission (2026-10-30), giving 40 full months.",
            ),
            "estimated_cost": FactSource(
                source_type="document",
                evidence=[
                    Evidence(
                        document_id="doc-estimate-apex",
                        document_version="v1",
                        page=1,
                        quote="Total Estimated Procedure Cost for Phacoemulsification with Foldable IOL: INR 45,000.",
                        evidence_type="hospital_estimate",
                    )
                ],
            ),
        },
    ),
    document_applicability=[
        DocumentApplicability(
            document_id="doc-base-policy-star",
            document_version="v1",
            policy_id="POL-9941-STAR",
            member_name="Sunita Patel",
            status="applicable",
            reason="Master policy terms apply to Star Health Plan POL-9941-STAR.",
            evidence=[
                Evidence(
                    document_id="doc-base-policy-star",
                    document_version="v1",
                    page=1,
                    quote="Master Policy Wording for Star Comprehensive Health Plan applicable to all schedules referencing Form STAR-COMP-2023.",
                    evidence_type="policy_wording",
                )
            ],
        )
    ],
    findings=[
        Finding(
            finding_id="find-cataract-waiting-period",
            revision=1,
            topic="Specific Disease Waiting Period (Cataract)",
            status="supported",
            conclusion=(
                "The 24-month specific disease waiting period for cataract surgery is satisfied "
                "based on 40 months of continuous coverage verified from policy schedule doc-schedule-9941 (p. 1)."
            ),
            evidence=[
                Evidence(
                    document_id="doc-base-policy-star",
                    document_version="v1",
                    page=14,
                    quote="Clause 4.3 (Specific Ailment Waiting Period): Expenses related to the treatment of Cataract are covered after twenty-four (24) months of continuous coverage.",
                    evidence_type="policy_wording",
                )
            ],
            relevant_case_facts=["procedure", "continuous_coverage_start_date", "policy_age_months"],
            missing_facts=[],
            limitations=[
                "Sub-limits of INR 40,000 per eye apply under Clause 5.2. Hospital estimate is INR 45,000, leaving a potential INR 5,000 out-of-pocket difference."
            ],
            next_action="Clarify lens model and package inclusions with hospital admission desk to check out-of-pocket costs exceeding the INR 40,000 sub-limit.",
            created_at=_dt(2026, 10, 24, 11, 2),
        )
    ],
    revisions=[],
    missing_evidence_checklist=[],
    unresolved_questions=[],
    authorization_status="not verified",
    authorization_evidence=[],
    tool_steps_used=3,
    stopped_reason="review_complete",
    stop_details=None,
)


# ==============================================================================
# Fixture 3: Conflict requiring clarification
# ==============================================================================
SAMPLE_CONFLICT_PACKET = ReviewPacket(
    packet_id="pkt-fixture-conflict-003",
    packet_version=1,
    run_id="run-fixture-003",
    generated_at=_dt(2026, 10, 24, 12, 0),
    review_status="incomplete",
    case=CaseDetails(
        case_id="case-fixture-003",
        member_name="Devendra Verma",
        policy_id="POL-8812-SILVER",
        planned_admission_date=date(2026, 10, 28),
        procedure="Total Knee Replacement",
        hospital_name="Metro Specialty Hospital",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "planned_admission_date": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
        },
    ),
    document_applicability=[
        DocumentApplicability(
            document_id="doc-endorsement-2026-v1",
            document_version="v1",
            policy_id="POL-8812-SILVER",
            effective_from=date(2026, 11, 1),
            status="uncertain",
            reason=(
                "Endorsement END-2026-04 amends joint replacement waiting periods to 24 months, "
                "but effective date is 01-Nov-2026, which is after planned admission date 28-Oct-2026. "
                "Precedence and applicability for late October admission are uncertain."
            ),
            evidence=[
                Evidence(
                    document_id="doc-endorsement-2026-v1",
                    document_version="v1",
                    page=1,
                    quote="Endorsement No. END-2026-04: Effective from 01-Nov-2026, Section 4.4 waiting period is amended to twenty-four (24) months.",
                    evidence_type="endorsement",
                )
            ],
        )
    ],
    findings=[
        Finding(
            finding_id="find-knee-waiting-period",
            revision=1,
            topic="Joint Replacement Waiting Period",
            status="conflict",
            conclusion=(
                "Conflicting waiting period terms: Base policy Section 4.4 requires 48 months (doc-base-policy-silver, p. 16), "
                "whereas Endorsement END-2026-04 reduces this to 24 months (doc-endorsement-2026-v1, p. 1). "
                "However, the endorsement's stated effective date is 01-Nov-2026, post-dating planned admission on 28-Oct-2026."
            ),
            evidence=[
                Evidence(
                    document_id="doc-base-policy-silver",
                    document_version="v1",
                    page=16,
                    quote="Section 4.4: Joint replacement surgeries shall be subject to a waiting period of forty-eight (48) consecutive months of continuous coverage.",
                    evidence_type="policy_wording",
                ),
                Evidence(
                    document_id="doc-endorsement-2026-v1",
                    document_version="v1",
                    page=1,
                    quote="Endorsement No. END-2026-04: Effective from 01-Nov-2026, Section 4.4 waiting period is amended to twenty-four (24) months.",
                    evidence_type="endorsement",
                ),
            ],
            relevant_case_facts=["procedure", "planned_admission_date", "policy_id"],
            missing_facts=[],
            limitations=[
                "Cannot automatically apply newer endorsement because effective date succeeds planned admission date.",
                "Requires insurer confirmation whether endorsement grace applies."
            ],
            next_action="Contact insurer helpline or desk to clarify if 24-month endorsement rule applies to an admission 4 days before endorsement effective date.",
            created_at=_dt(2026, 10, 24, 12, 2),
        )
    ],
    revisions=[],
    missing_evidence_checklist=[],
    unresolved_questions=[
        "Does Endorsement END-2026-04 apply to an admission on 2026-10-28 when its stated effective date is 2026-11-01?",
    ],
    authorization_status="not verified",
    authorization_evidence=[],
    tool_steps_used=4,
    stopped_reason="conflicting_evidence",
    stop_details="Contradictory waiting period terms between base policy and post-dated endorsement.",
)


# ==============================================================================
# Fixture 4: Revised finding with before/after evidence (Evidence Change Replay)
# ==============================================================================
SAMPLE_REVISED_FINDING_PACKET = ReviewPacket(
    packet_id="pkt-fixture-revised-004",
    packet_version=2,
    run_id="run-fixture-004",
    generated_at=_dt(2026, 10, 24, 14, 0),
    review_status="complete",
    case=CaseDetails(
        case_id="case-fixture-004",
        member_name="Pooja Rao",
        policy_id="POL-5501-GOLD",
        policy_start_date=date(2025, 1, 10),
        continuous_coverage_start_date=date(2025, 1, 10),
        policy_age_months=21,
        planned_admission_date=date(2026, 10, 25),
        procedure="Normal Delivery / Maternity Inpatient Care",
        hospital_name="Motherhood Hospital",
        currency="INR",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "planned_admission_date": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
            "hospital_name": FactSource(source_type="user_provided"),
            "policy_start_date": FactSource(
                source_type="document",
                evidence=[
                    Evidence(
                        document_id="doc-schedule-5501",
                        document_version="v1",
                        page=1,
                        quote="Schedule Issue Date: 10-Jan-2025. Policy Commencement: 10-Jan-2025.",
                        evidence_type="policy_schedule",
                    )
                ],
            ),
            "continuous_coverage_start_date": FactSource(
                source_type="document",
                evidence=[
                    Evidence(
                        document_id="doc-schedule-5501",
                        document_version="v1",
                        page=1,
                        quote="Schedule Issue Date: 10-Jan-2025. Policy Commencement: 10-Jan-2025.",
                        evidence_type="policy_schedule",
                    )
                ],
            ),
            "policy_age_months": FactSource(
                source_type="derived",
                explanation="Elapsed duration is 21 months between 2025-01-10 and 2026-10-25.",
            ),
        },
    ),
    document_applicability=[
        DocumentApplicability(
            document_id="doc-maternity-rider-v1",
            document_version="v1",
            policy_id="POL-5501-GOLD",
            member_name="Pooja Rao",
            effective_from=date(2025, 1, 10),
            status="applicable",
            reason="Maternity Rider active and linked to Gold Policy POL-5501-GOLD.",
            evidence=[
                Evidence(
                    document_id="doc-maternity-rider-v1",
                    document_version="v1",
                    page=1,
                    quote="Gold Health Policy Maternity Rider Schedule: Attached to Policy POL-5501-GOLD for Pooja Rao.",
                    evidence_type="endorsement",
                )
            ],
        )
    ],
    # Current active revision (revision 2)
    findings=[
        Finding(
            finding_id="find-maternity-coverage",
            revision=2,
            topic="Maternity Coverage & Waiting Period",
            status="supported",
            conclusion=(
                "Maternity care covered up to INR 50,000 with 9-month waiting period satisfied "
                "(21 months continuous coverage elapsed) under Maternity Rider Schedule (doc-maternity-rider-v1, p. 2)."
            ),
            evidence=[
                Evidence(
                    document_id="doc-maternity-rider-v1",
                    document_version="v1",
                    page=2,
                    quote="Section 2.1: Inpatient maternity expenses are covered up to INR 50,000 per delivery after nine (9) months of continuous coverage under this rider.",
                    evidence_type="endorsement",
                )
            ],
            relevant_case_facts=["procedure", "continuous_coverage_start_date", "policy_age_months"],
            missing_facts=[],
            limitations=[
                "Benefit is subject to a strict INR 50,000 sub-limit. Hospital expenses exceeding INR 50,000 must be borne out-of-pocket."
            ],
            next_action="Request itemized room rent and delivery estimate from Motherhood Hospital to verify charges against the INR 50,000 rider limit.",
            created_at=_dt(2026, 10, 24, 14, 2),
        )
    ],
    # Traceable audit log showing before-after change
    revisions=[
        Revision(
            revision_id="rev-20261024-001",
            finding_id="find-maternity-coverage",
            old_finding_revision=1,
            new_finding_revision=2,
            old_status="unresolved",
            new_status="supported",
            old_conclusion="Maternity coverage unresolved: General Exclusion 6.1 in base policy excludes all pregnancy and childbirth expenses.",
            new_conclusion="Maternity care covered up to INR 50,000 with 9-month waiting period satisfied (21 months continuous coverage elapsed) under Maternity Rider Schedule (doc-maternity-rider-v1, p. 2).",
            trigger_type="new_document",
            triggering_evidence=[
                Evidence(
                    document_id="doc-maternity-rider-v1",
                    document_version="v1",
                    page=1,
                    quote="Gold Health Policy Maternity Rider Schedule: Attached to Policy POL-5501-GOLD for Pooja Rao.",
                    evidence_type="endorsement",
                )
            ],
            changed_case_facts=[],
            reason="Uploaded Maternity Rider endorsement v1 amends General Exclusion Section 6.1 and confirms active maternity benefit.",
            affected_topics=["Maternity Coverage & Waiting Period"],
            created_at=_dt(2026, 10, 24, 14, 2),
        )
    ],
    missing_evidence_checklist=[],
    unresolved_questions=[],
    authorization_status="not verified",
    authorization_evidence=[],
    tool_steps_used=5,
    stopped_reason="review_complete",
    stop_details=None,
)


import json
from pathlib import Path

ALL_SAMPLE_PACKETS = {
    "incomplete_review": SAMPLE_INCOMPLETE_REVIEW_PACKET,
    "supported_finding": SAMPLE_SUPPORTED_FINDING_PACKET,
    "conflict_review": SAMPLE_CONFLICT_PACKET,
    "revised_finding": SAMPLE_REVISED_FINDING_PACKET,
}


def get_sample_packet(name: str) -> ReviewPacket:
    """Retrieve a deep copy of a sample ReviewPacket fixture by name.

    Available names:
    - 'incomplete_review': Incomplete review with missing facts and checklist item.
    - 'supported_finding': Complete review with supported finding citing physical PDF page.
    - 'conflict_review': Incomplete review with conflict between policy and endorsement.
    - 'revised_finding': Complete review with Evidence Change Replay revision (rev 1 -> rev 2).
    """
    if name not in ALL_SAMPLE_PACKETS:
        raise KeyError(
            f"Unknown sample packet '{name}'. Available: {list(ALL_SAMPLE_PACKETS.keys())}"
        )
    return ALL_SAMPLE_PACKETS[name].model_copy(deep=True)


def load_sample_packet_from_json(path_or_name: str | Path) -> ReviewPacket:
    """Load and validate a sample ReviewPacket from JSON file.

    Accepts either an explicit filesystem path or a known name:
    'incomplete_review', 'supported_finding', 'conflict_review', 'revised_finding'.
    """
    p = Path(path_or_name)
    if not p.exists():
        json_dir = Path(__file__).parent / "json"
        candidate = json_dir / f"{path_or_name}.json"
        if candidate.exists():
            p = candidate
        else:
            raise FileNotFoundError(f"Fixture JSON not found: {path_or_name}")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop("_comment", None)
    return ReviewPacket.model_validate(data)


def list_sample_packet_names() -> list[str]:
    """Return available sample packet fixture keys."""
    return list(ALL_SAMPLE_PACKETS.keys())
