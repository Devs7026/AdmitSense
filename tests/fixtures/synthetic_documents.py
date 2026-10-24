"""Synthetic extracted document fixtures for AdmitSense development and evaluation.

DISCLAIMER:
All documents, terms, and policy schedules in this file are FICTIONAL SYNTHETIC FIXTURES
authored independently for testing retrieval tools, citation verification, and
evaluating the bounded review agent. They do not represent real policy contracts.
"""

from admitsense.agent.retrieval import DocumentRecord, ExtractedPage

SYNTHETIC_CASE_ID = "case-synthetic-001"
OTHER_CASE_ID = "case-other-999"

# ==============================================================================
# 1. Base Policy Document (18 physical pages, multi-clause policy wording)
# ==============================================================================
SYNTHETIC_BASE_POLICY_DOC = DocumentRecord(
    document_id="doc-base-policy-star",
    case_id=SYNTHETIC_CASE_ID,
    filename="Star_Comprehensive_Health_Policy_Terms.pdf",
    version="v1",
    sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    evidence_type="policy_wording",
    uploaded_at="2026-10-24T09:00:00Z",
    extraction_status="extracted",
    total_pages=18,
    pages=[
        ExtractedPage(
            page_number=1,
            text=(
                "Master Policy Wording for Star Comprehensive Health Plan applicable to all schedules "
                "referencing Form STAR-COMP-2023. Section 1: Preamble and Basis of Insurance."
            ),
        ),
        ExtractedPage(
            page_number=2,
            text=(
                "Section 2: Definitions.\n"
                "2.1 Continuous Coverage means uninterrupted health insurance coverage with an Indian insurer, "
                "including renewals and portability credits recognized under IRDAI regulations.\n"
                "2.2 Hospitalization means admission in a Hospital for a minimum period of 24 consecutive "
                "in-patient care hours except for specified day care procedures."
            ),
        ),
        ExtractedPage(
            page_number=3,
            text="Section 3: Inpatient Hospitalization Benefits, Room Rent Categories, and ICU Charges.",
        ),
        ExtractedPage(
            page_number=4,
            text="Section 3.2: Day Care Procedures list and eligibility criteria.",
        ),
        ExtractedPage(page_number=5, text="Section 3.3: Pre-hospitalization and Post-hospitalization medical expenses."),
        ExtractedPage(page_number=6, text="Section 3.4: Emergency Ambulance Charges and Organ Donor Expenses."),
        ExtractedPage(page_number=7, text="Section 4: Waiting Periods. General waiting period of 30 days applies."),
        ExtractedPage(
            page_number=8,
            text=(
                "Section 4.2: A waiting period of twenty-four (24) consecutive months of continuous coverage shall apply to "
                "the treatment of all types of Hernia, Hydrocele, and Piles."
            ),
        ),
        ExtractedPage(page_number=9, text="Section 4.2.2: Benign prostatic hypertrophy and hysterectomy waiting terms."),
        ExtractedPage(page_number=10, text="Section 4.2.3: Calculus diseases of gall bladder and urogenital system."),
        ExtractedPage(page_number=11, text="Section 4.2.4: ENT disorders and tonsillectomy waiting periods."),
        ExtractedPage(
            page_number=12,
            text=(
                "Section 4.2.5: Eye and Ophthalmic Treatments.\n"
                "Clause 4.3: Cataract surgery is covered subject to a waiting period of twenty-four (24) "
                "months of continuous coverage."
            ),
        ),
        ExtractedPage(page_number=13, text="Clause 4.3.1: Modern surgical treatment methods in cataract surgery."),
        ExtractedPage(
            page_number=14,
            text=(
                "Clause 4.3 (Specific Ailment Waiting Period): Expenses related to the treatment of Cataract "
                "are covered after twenty-four (24) months of continuous coverage.\n"
                "Clause 5.2: Cataract claims are subject to a sub-limit of INR 40,000 per eye."
            ),
        ),
        ExtractedPage(page_number=15, text="Section 4.3: Pre-existing condition waiting period of 36 months."),
        ExtractedPage(
            page_number=16,
            text=(
                "Section 4.4: Joint replacement surgeries shall be subject to a waiting period of "
                "forty-eight (48) consecutive months of continuous coverage unless arising directly out of accidental injury."
            ),
        ),
        ExtractedPage(page_number=17, text="Section 5: General Policy Conditions, Claims Procedure, and Co-payment."),
        ExtractedPage(
            page_number=18,
            text=(
                "Section 6: General Exclusions.\n"
                "6.1 Maternity Expenses: Treatment arising from pregnancy, childbirth, caesarean section, "
                "or miscarriage is specifically excluded unless covered under an optional endorsement rider."
            ),
        ),
    ],
)


# ==============================================================================
# 2. Policy Schedule Document (2 physical pages)
# ==============================================================================
SYNTHETIC_POLICY_SCHEDULE_DOC = DocumentRecord(
    document_id="doc-schedule-9941",
    case_id=SYNTHETIC_CASE_ID,
    filename="Policy_Schedule_POL-9941.pdf",
    version="v1",
    sha256="a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
    evidence_type="policy_schedule",
    uploaded_at="2026-10-24T09:05:00Z",
    extraction_status="extracted",
    total_pages=2,
    pages=[
        ExtractedPage(
            page_number=1,
            text=(
                "Star Comprehensive Health Insurance — Policy Schedule\n"
                "Policy Number: POL-9941-STAR\n"
                "Insured Member: Sunita Patel (Age: 58, Female)\n"
                "Policy Inception Date: 01-Jun-2023. Continuous Coverage Date: 01-Jun-2023.\n"
                "Current Policy Period: 01-Jun-2026 to 31-May-2027.\n"
                "Sum Insured: INR 10,00,000. Cumulative Bonus: INR 2,00,000."
            ),
        ),
        ExtractedPage(
            page_number=2,
            text=(
                "TPA Desk Information:\n"
                "Dedicated Helpline: 1800-425-2255. Cashless claims must be intimated 48 hours prior to planned admission."
            ),
        ),
    ],
)


# ==============================================================================
# 3. Endorsement Document (Joint Replacement waiting reduction, post-dated)
# ==============================================================================
SYNTHETIC_ENDORSEMENT_DOC = DocumentRecord(
    document_id="doc-endorsement-2026-v1",
    case_id=SYNTHETIC_CASE_ID,
    filename="Endorsement_END-2026-04.pdf",
    version="v1",
    sha256="c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef01234",
    evidence_type="endorsement",
    uploaded_at="2026-10-24T09:10:00Z",
    extraction_status="extracted",
    total_pages=1,
    pages=[
        ExtractedPage(
            page_number=1,
            text=(
                "Endorsement No. END-2026-04 Attached to Policy POL-8812-SILVER / POL-9941-STAR.\n"
                "Effective from 01-Nov-2026, Section 4.4 waiting period is amended to twenty-four (24) months.\n"
                "All other terms and conditions of the Master Policy remain unaltered."
            ),
        )
    ],
)


# ==============================================================================
# 4. Maternity Rider Endorsement Document (Amends General Exclusion 6.1)
# ==============================================================================
SYNTHETIC_MATERNITY_RIDER_DOC = DocumentRecord(
    document_id="doc-maternity-rider-v1",
    case_id=SYNTHETIC_CASE_ID,
    filename="Maternity_Rider_Schedule.pdf",
    version="v1",
    sha256="d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef012345",
    evidence_type="endorsement",
    uploaded_at="2026-10-24T09:15:00Z",
    extraction_status="extracted",
    total_pages=2,
    pages=[
        ExtractedPage(
            page_number=1,
            text=(
                "Gold Health Policy Maternity Rider Schedule: Attached to Policy POL-5501-GOLD for Pooja Rao.\n"
                "Commencement Date: 10-Jan-2025."
            ),
        ),
        ExtractedPage(
            page_number=2,
            text=(
                "Section 2.1: Inpatient maternity expenses are covered up to INR 50,000 per delivery after "
                "nine (9) months of continuous coverage under this rider."
            ),
        ),
    ],
)


# ==============================================================================
# 5. Unreadable Corrupted Document (Testing extraction failure & non-implication)
# ==============================================================================
SYNTHETIC_UNREADABLE_DOC = DocumentRecord(
    document_id="doc-unreadable-scan-v1",
    case_id=SYNTHETIC_CASE_ID,
    filename="Scanned_Corrupted_Record.pdf",
    version="v1",
    sha256="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    evidence_type="other",
    uploaded_at="2026-10-24T09:20:00Z",
    extraction_status="unreadable",
    total_pages=3,
    pages=[],
    error_message="Optical scan blurred or corrupted; text layer extraction failed.",
)


# ==============================================================================
# 6. Document Belonging to Another Case (Testing cross-case isolation)
# ==============================================================================
SYNTHETIC_OTHER_CASE_DOC = DocumentRecord(
    document_id="doc-other-case-policy",
    case_id=OTHER_CASE_ID,
    filename="Confidential_Patient_Record.pdf",
    version="v1",
    sha256="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    evidence_type="policy_wording",
    uploaded_at="2026-10-24T09:25:00Z",
    extraction_status="extracted",
    total_pages=2,
    pages=[
        ExtractedPage(
            page_number=1,
            text="Private medical record for unrelated patient belonging to case-other-999.",
        ),
        ExtractedPage(
            page_number=2,
            text="Confidential diagnostic reports and private billing entries.",
        ),
    ],
)


ALL_SYNTHETIC_DOCUMENTS = [
    SYNTHETIC_BASE_POLICY_DOC,
    SYNTHETIC_POLICY_SCHEDULE_DOC,
    SYNTHETIC_ENDORSEMENT_DOC,
    SYNTHETIC_MATERNITY_RIDER_DOC,
    SYNTHETIC_UNREADABLE_DOC,
    SYNTHETIC_OTHER_CASE_DOC,
]
