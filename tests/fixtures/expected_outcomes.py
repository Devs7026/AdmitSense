"""Independently specified expected evidence and outcomes for synthetic documents in AdmitSense.

DISCLAIMER:
These specifications define the expected ground truth for evaluation testing.
They verify that retrieval tools find the exact expected physical pages and that
citation verification accepts authentic quotes while rejecting fabricated text.
"""

from dataclasses import dataclass
from admitsense.schemas import Evidence


@dataclass(frozen=True)
class ExpectedRetrievalOutcome:
    query: str
    expected_document_id: str
    expected_version: str
    expected_page_number: int
    expected_quote: str
    expected_finding_status: str  # supported, unresolved, conflict
    notes: str


EXPECTED_CATARACT_OUTCOME = ExpectedRetrievalOutcome(
    query="cataract waiting period",
    expected_document_id="doc-base-policy-star",
    expected_version="v1",
    expected_page_number=14,
    expected_quote=(
        "Clause 4.3 (Specific Ailment Waiting Period): Expenses related to the treatment of Cataract "
        "are covered after twenty-four (24) months of continuous coverage."
    ),
    expected_finding_status="supported",
    notes="24-month waiting period is satisfied when 40 months continuous coverage elapsed.",
)

EXPECTED_HERNIA_OUTCOME = ExpectedRetrievalOutcome(
    query="hernia waiting period",
    expected_document_id="doc-base-policy-star",
    expected_version="v1",
    expected_page_number=8,
    expected_quote=(
        "Section 4.2: A waiting period of twenty-four (24) consecutive months of continuous coverage shall apply to "
        "the treatment of all types of Hernia, Hydrocele, and Piles."
    ),
    expected_finding_status="unresolved",
    notes="Finding remains unresolved while continuous coverage start date is missing.",
)

EXPECTED_JOINT_REPLACEMENT_BASE_OUTCOME = ExpectedRetrievalOutcome(
    query="joint replacement waiting period",
    expected_document_id="doc-base-policy-star",
    expected_version="v1",
    expected_page_number=16,
    expected_quote=(
        "Section 4.4: Joint replacement surgeries shall be subject to a waiting period of "
        "forty-eight (48) consecutive months of continuous coverage"
    ),
    expected_finding_status="conflict",
    notes="Base policy rule imposing 48-month waiting period.",
)

EXPECTED_JOINT_REPLACEMENT_ENDORSEMENT_OUTCOME = ExpectedRetrievalOutcome(
    query="amended to twenty-four (24) months",
    expected_document_id="doc-endorsement-2026-v1",
    expected_version="v1",
    expected_page_number=1,
    expected_quote=(
        "Effective from 01-Nov-2026, Section 4.4 waiting period is amended to twenty-four (24) months."
    ),
    expected_finding_status="conflict",
    notes="Endorsement amends rule to 24 months but effective date post-dates planned admission.",
)

EXPECTED_MATERNITY_RIDER_OUTCOME = ExpectedRetrievalOutcome(
    query="maternity expenses are covered up to INR 50,000",
    expected_document_id="doc-maternity-rider-v1",
    expected_version="v1",
    expected_page_number=2,
    expected_quote=(
        "Section 2.1: Inpatient maternity expenses are covered up to INR 50,000 per delivery after "
        "nine (9) months of continuous coverage under this rider."
    ),
    expected_finding_status="supported",
    notes="Rider overrides general exclusion 6.1, giving supported finding with revision increment.",
)

# Canonical Evidence objects expected to pass verification
VALID_CATARACT_EVIDENCE = Evidence(
    document_id="doc-base-policy-star",
    document_version="v1",
    page=14,
    quote=(
        "Clause 4.3 (Specific Ailment Waiting Period): Expenses related to the treatment of Cataract "
        "are covered after twenty-four (24) months of continuous coverage."
    ),
    evidence_type="policy_wording",
)

VALID_SCHEDULE_EVIDENCE = Evidence(
    document_id="doc-schedule-9941",
    document_version="v1",
    page=1,
    quote="Policy Inception Date: 01-Jun-2023. Continuous Coverage Date: 01-Jun-2023.",
    evidence_type="policy_schedule",
)

VALID_HERNIA_EVIDENCE = Evidence(
    document_id="doc-base-policy-star",
    document_version="v1",
    page=8,
    quote=(
        "Section 4.2: A waiting period of twenty-four (24) consecutive months of continuous coverage shall apply to "
        "the treatment of all types of Hernia, Hydrocele, and Piles."
    ),
    evidence_type="policy_wording",
)

# Fabricated quote example that MUST fail verification
FABRICATED_APPROVAL_EVIDENCE = Evidence(
    document_id="doc-base-policy-star",
    document_version="v1",
    page=14,
    quote="The insurer unconditionally guarantees 100% cashless approval and waives all policy exclusions.",
    evidence_type="policy_wording",
)

# Wrong-case reference example that MUST fail verification
WRONG_CASE_EVIDENCE = Evidence(
    document_id="doc-other-case-policy",
    document_version="v1",
    page=1,
    quote="Private medical record for unrelated patient belonging to case-other-999.",
    evidence_type="policy_wording",
)
