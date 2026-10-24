from __future__ import annotations

import json
from pathlib import Path


def generate_pdf_bytes(pages_text: list[str]) -> bytes:
    """
    Constructs a valid multi-page PDF document in memory using pure standard library.
    Empty string in pages_text creates an explicit blank page.
    """
    body = bytearray()
    offsets: list[int] = []

    def add_obj(data: bytes) -> int:
        offsets.append(len(body))
        obj_num = len(offsets)
        body.extend(f"{obj_num} 0 obj\n".encode("latin1"))
        body.extend(data)
        body.extend(b"\nendobj\n")
        return obj_num

    num_pages = len(pages_text)
    kids_str = " ".join(f"{4 + 2 * i} 0 R" for i in range(num_pages))
    pages_data = f"<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>".encode("latin1")
    catalog_data = b"<< /Type /Catalog /Pages 2 0 R >>"
    font_data = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    body.extend(b"%PDF-1.4\n")
    add_obj(catalog_data)
    add_obj(pages_data)
    add_obj(font_data)

    for i, text in enumerate(pages_text):
        if text.strip():
            clean = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            # Standard single-line or wrapped stream
            stream_data = f"BT /F1 11 Tf 50 740 Td ({clean}) Tj ET".encode("latin1")
            content_obj_data = (
                f"<< /Length {len(stream_data)} >>\nstream\n".encode("latin1")
                + stream_data
                + b"\nendstream"
            )
            content_id = 4 + 2 * i + 1
            page_data = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("latin1")
        else:
            page_data = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"
            content_obj_data = b"<< /Length 0 >>\nstream\n\nendstream"

        add_obj(page_data)
        add_obj(content_obj_data)

    xref_offset = len(body)
    body.extend(b"xref\n")
    body.extend(f"0 {len(offsets) + 1}\n".encode("latin1"))
    body.extend(b"0000000000 65535 f \n")
    for off in offsets:
        body.extend(f"{off:010d} 00000 n \n".encode("latin1"))
    body.extend(b"trailer\n")
    body.extend(f"<< /Size {len(offsets) + 1} /Root 1 0 R >>\n".encode("latin1"))
    body.extend(b"startxref\n")
    body.extend(f"{xref_offset}\n".encode("latin1"))
    body.extend(b"%%EOF\n")

    return bytes(body)


def build_synthetic_policy_pdf() -> bytes:
    """
    Creates a 15-page synthetic policy master wording document.
    - Page 1: Master preamble and definitions.
    - Page 7: Blank page (tests blank page retention and physical page index alignment).
    - Page 14: Section 4.2(b) containing the 24-month waiting period clause.
    """
    pages: list[str] = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Master Document for Care Health Gold Series. Issued by Fictional Care Insurance Corp.",
        "Section 1: Inpatient Hospitalisation Benefits and Day Care Procedures.",
        "Section 2: Room Rent and Intensive Care Unit Limits. Standard single private room covered up to 1 percent of sum insured per day.",
        "Section 3: Pre-Hospitalisation and Post-Hospitalisation Expenses.",
        "Section 3.2: AYUSH Inpatient Treatment Coverage Terms.",
        "Section 3.3: Domiciliary Hospitalisation Terms and Certification Requirements.",
        "",  # Page 7: Explicit blank page
        "Section 4: General Exclusions and Waiting Periods.",
        "Section 4.1: Initial Thirty (30) Day Waiting Period for illness-related hospitalisation.",
        "Section 4.2: Specific Illness Waiting Periods.",
        "Section 4.2(a): Cataract surgery waiting period: twelve (12) continuous months.",
        "Section 4.2(a) Continued: Hernia and benign prostate enlargement waiting periods.",
        "Section 4.2 Table of Excluded and Specific Conditions.",
        "Section 4.2(b): Treatment for degenerative joint disorders including total knee replacement is covered subject to a specific waiting period of twenty-four (24) continuous months from the initial policy inception date.",
        "Section 5: Claim Procedures, Cashless Network Guidelines, and Grievance Redressal.",
    ]
    return generate_pdf_bytes(pages)


def build_synthetic_schedule_pdf() -> bytes:
    """Creates a 2-page policy renewal schedule showing 18 months continuous coverage."""
    pages = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Care Health Insurance Renewal Schedule. Policy ID: POL-998877. Insured Member: Ramesh Sharma. Policy Inception Date: 2024-04-01. Continuous coverage completed: eighteen (18) months.",
        "Schedule Table: Sum Insured INR 500,000. Cumulative Bonus: INR 50,000. TPA Desk: MediAssist TPA India Ltd.",
    ]
    return generate_pdf_bytes(pages)


def build_synthetic_endorsement_pdf() -> bytes:
    """Creates a 1-page endorsement modifying waiting period from 24 to 12 months."""
    pages = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Policy Endorsement Schedule EW-2025-01. Applicable to Policy ID: POL-998877. Member Name: Ramesh Sharma. Effective From: 2025-04-01. Waiting Period Modification: The specific waiting period for degenerative joint disorders and joint replacement surgeries under Section 4.2(b) is reduced from twenty-four (24) continuous months to twelve (12) continuous months.",
    ]
    return generate_pdf_bytes(pages)


def build_synthetic_hospital_estimate_pdf() -> bytes:
    """Creates a 2-page itemized hospital admission estimate."""
    pages = [
        "SYNTHETIC DEMONSTRATION DOCUMENT. Apex Super Specialty Hospital Pre-Admission Estimate. Patient Name: Ramesh Sharma. Planned Admission: 2026-11-15. Procedure: Total Knee Replacement (Unilateral). Estimated Total: INR 250,000.00.",
        "Estimate Breakdown: Implant Cost INR 90,000; OT Charges INR 45,000; Room Rent (3 days) INR 30,000; Surgeon Fees INR 60,000; Pharmacy INR 25,000.",
    ]
    return generate_pdf_bytes(pages)


def build_synthetic_unreadable_pdf() -> bytes:
    """Creates an empty 2-page PDF with no extractable text to test unreadable extraction state."""
    return generate_pdf_bytes(["", ""])


def build_synthetic_hospital_json() -> dict:
    """Creates synthetic hospital dataset conforming to HospitalRecordReference contract."""
    return {
        "dataset_version": "v2026.1",
        "dataset_date": "2026-10-01",
        "disclaimer": "SYNTHETIC DEMONSTRATION DATASET. Not indicative of real network agreements or claim approval.",
        "hospitals": [
            {
                "record_id": "hosp-synth-001",
                "dataset_version": "v2026.1",
                "dataset_date": "2026-10-01",
                "hospital_name": "Apex Super Specialty Hospital",
                "city": "Bengaluru",
                "network_tier": "tier_1",
                "tpa_desk_contact": "+91-80-5555-0199 (Ext 402)",
                "limitations": [
                    "Synthetic hospital data for demonstration only.",
                    "Does not establish current insurer network agreement or cashless guarantee.",
                ],
            },
            {
                "record_id": "hosp-synth-002",
                "dataset_version": "v2026.1",
                "dataset_date": "2026-10-01",
                "hospital_name": "City General Hospital",
                "city": "Bengaluru",
                "network_tier": "tier_2",
                "tpa_desk_contact": "+91-80-5555-0144",
                "limitations": [
                    "Synthetic hospital data for demonstration only.",
                    "Does not establish current insurer network agreement or cashless guarantee.",
                ],
            },
            {
                "record_id": "hosp-synth-003",
                "dataset_version": "v2026.1",
                "dataset_date": "2026-10-01",
                "hospital_name": "Lotus Healthcare Clinic",
                "city": "Bengaluru",
                "network_tier": "non_network",
                "tpa_desk_contact": None,
                "limitations": [
                    "Synthetic hospital data for demonstration only.",
                    "Does not establish current insurer network agreement or cashless guarantee.",
                ],
            },
        ],
    }


def write_synthetic_fixtures(target_dir: Path | str) -> dict[str, Path]:
    """Generates and writes all synthetic fixture files to target directory."""
    out_dir = Path(target_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "policy_wording": out_dir / "Care_Health_Gold_Policy_Wording.pdf",
        "renewal_schedule": out_dir / "Policy_Renewal_Schedule.pdf",
        "endorsement": out_dir / "Joint_Replacement_Endorsement.pdf",
        "hospital_estimate": out_dir / "Apex_Hospital_Estimate.pdf",
        "unreadable_scanned": out_dir / "Scanned_Receipt_Unreadable.pdf",
        "hospitals_json": out_dir / "hospitals_synthetic_v2026.json",
    }

    files["policy_wording"].write_bytes(build_synthetic_policy_pdf())
    files["renewal_schedule"].write_bytes(build_synthetic_schedule_pdf())
    files["endorsement"].write_bytes(build_synthetic_endorsement_pdf())
    files["hospital_estimate"].write_bytes(build_synthetic_hospital_estimate_pdf())
    files["unreadable_scanned"].write_bytes(build_synthetic_unreadable_pdf())
    files["hospitals_json"].write_text(
        json.dumps(build_synthetic_hospital_json(), indent=2), encoding="utf-8"
    )

    return files
