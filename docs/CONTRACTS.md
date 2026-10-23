# AdmitSense — System Contracts & Interfaces

This document defines the data models, interfaces, error handling, and storage boundaries for AdmitSense.

- **IMPLEMENTED**: Code exists and is verified in the repository.
- **PROPOSED**: Proposed interfaces awaiting review and coordination between Owner A and Owner B.

---

## 1. Domain Data Models (IMPLEMENTED)

Defined in [`src/admitsense/schemas.py`](file:///c:/Users/Admin/Documents/AgentOps%20CGI%20Hackathon/AdmitSense/src/admitsense/schemas.py) using Pydantic v2.

### 1.1 Core Enums and Types
- `FindingStatus`: `"supported" | "unresolved" | "conflict" | "needs_human_review"`
- `ReviewStatus`: `"complete" | "incomplete" | "failed"`
- `AuthorizationStatus`: `"not verified" | "pending insurer review"`
- `StopReason`: `"review_complete" | "missing_information" | "conflicting_evidence" | "needs_human_review" | "tool_limit_reached" | "timeout" | "processing_error"`
- `EvidenceType`: `"policy_wording" | "policy_schedule" | "endorsement" | "hospital_estimate" | "admission_document" | "insurer_correspondence" | "other"`
- `CaseFactName`: `"member_name" | "policy_id" | "policy_start_date" | "continuous_coverage_start_date" | "planned_admission_date" | "policy_age_months" | "procedure" | "hospital_name" | "estimated_cost"`

### 1.2 Core Models
- `Evidence`: Cites exact physical page (`gt=0`), immutable document version, quote, and evidence type.
- `FactSource`: Distinguishes `user_provided`, `document` (requires evidence), and `derived` (requires explanation).
- `CaseDetails`: Stores case attributes. Missing facts remain `None`. Requires `fact_sources` mapping for every non-null fact.
- `DocumentApplicability`: Records applicability metadata (`not_checked`, `applicable`, `not_applicable`, `uncertain`), effective date bounds, reasons, and supporting evidence.
- `Finding`: Stores administrative findings, status, conclusion, next action, citations, missing facts, and limitations.
- `MissingEvidenceItem`: Actionable checklist item with status (`requested`, `user_does_not_have`, `provided_pending_review`, `resolved`).
- `Revision`: Traceable before-after change log entry for a finding revision.
- `ReviewPacket`: Master container linking case facts, findings, revisions, applicability, missing evidence checklist, authorization status, tool step counts (0 to 8), and stop reason.

---

## 2. Proposed Storage & Ingestion Interfaces (PROPOSED)

Owner A proposes the following repository and extraction contracts for implementation in M1 and M2.

### 2.1 Extraction & Document Status Schema (PROPOSED)
```python
from typing import Literal
from pydantic import BaseModel, Field

ExtractionStatus = Literal[
    "pending",
    "extracted",
    "partial",
    "unreadable",
    "error",
]

class ExtractedPage(BaseModel):
    page_number: int = Field(gt=0, description="1-based physical PDF page number")
    text: str = Field(description="Extracted raw text with normalized whitespace")
    is_blank: bool = False
    character_count: int = Field(ge=0)

class DocumentRecord(BaseModel):
    document_id: str
    case_id: str
    filename: str
    version: str = "v1"
    sha256: str
    evidence_type: str = "other"
    uploaded_at: str
    extraction_status: ExtractionStatus
    total_pages: int = Field(ge=0)
    pages: list[ExtractedPage] = Field(default_factory=list)
    error_message: str | None = None
```

### 2.2 Case Repository Interface (PROPOSED)
```python
class CaseRepository(Protocol):
    def create_case(self, case: CaseDetails) -> CaseDetails:
        """Persist a new case. Raises ValueError if case_id already exists."""
        ...

    def get_case(self, case_id: str) -> CaseDetails | None:
        """Retrieve a case by ID. Returns None if not found."""
        ...

    def update_case(self, case: CaseDetails) -> CaseDetails:
        """Update existing case facts. Raises KeyError if case does not exist."""
        ...

    def list_cases(self) -> list[CaseDetails]:
        """Return all persisted cases ordered by last update."""
        ...
```

### 2.3 Document Storage Interface (PROPOSED)
```python
class DocumentStorage(Protocol):
    def save_document(
        self,
        case_id: str,
        filename: str,
        content: bytes,
        evidence_type: str = "other",
    ) -> DocumentRecord:
        """
        Calculates SHA-256 hash. If document with same filename exists for case,
        increments version (e.g. v1 -> v2). Stores raw file and initial DocumentRecord.
        """
        ...

    def get_document(self, document_id: str, version: str) -> DocumentRecord | None:
        """Fetch immutable document record including extracted pages."""
        ...

    def list_documents(self, case_id: str) -> list[DocumentRecord]:
        """List all documents and versions for a given case."""
        ...

    def save_extracted_pages(
        self,
        document_id: str,
        version: str,
        pages: list[ExtractedPage],
        status: ExtractionStatus,
        error_message: str | None = None,
    ) -> None:
        """Persist extracted page texts and extraction status atomically."""
        ...
```

### 2.4 Evidence & Page Retrieval Interface (PROPOSED)
```python
class EvidenceRetrieval(Protocol):
    def get_page_text(
        self,
        document_id: str,
        version: str,
        page_number: int,
    ) -> str | None:
        """
        Returns physical page text (1-based page_number) for agent search
        or UI evidence inspection. Returns None if document/page does not exist.
        """
        ...

    def verify_citation(
        self,
        evidence: Evidence,
    ) -> tuple[bool, str]:
        """
        Validates that evidence.quote appears within the specified document_id,
        version, and 1-based page number (after standard whitespace normalisation).
        Returns (is_valid, reason).
        """
        ...
```

### 2.5 Review Persistence & Atomic Revisions (PROPOSED)
```python
class ReviewRepository(Protocol):
    def save_review_packet(self, packet: ReviewPacket) -> ReviewPacket:
        """
        Persists a review packet snapshot. Must be executed in a single transaction:
        1. Insert/update ReviewPacket metadata.
        2. Insert current findings with their revision number.
        3. Insert new Revision entries linking old and new finding revisions.
        4. Insert missing evidence checklist items.
        """
        ...

    def get_latest_review_packet(self, case_id: str) -> ReviewPacket | None:
        """Fetch the most recent review packet for a case."""
        ...

    def get_finding_history(
        self,
        case_id: str,
        finding_id: str,
    ) -> list[Revision]:
        """Retrieve chronological audit trail of all revisions for a specific finding."""
        ...
```

---

## 3. ID Assignment & Ownership Matrix

| Entity | ID Format Example | Assigned By | Stored By | Invariant Rule |
|---|---|---|---|---|
| **Case** | `case-20261023-001` | Owner A (UI/Repository) | SQLite `cases` | Case IDs must be unique. |
| **Document** | `doc-base-policy` | Owner A (Storage) | SQLite `documents` | Hashed via SHA-256; unique per file. |
| **Document Version** | `v1`, `v2` | Owner A (Storage) | SQLite `documents` | Immutable; incremented on re-upload. |
| **Page Number** | `1`, `2`, `...` | Owner A (`pypdf` extractor) | SQLite `document_pages` | Physical 1-based PDF page index. |
| **Finding** | `find-waiting-period` | Owner B (Agent / Review) | SQLite `findings` | Unique per topic per case. |
| **Finding Revision**| `1`, `2`, `...` | Owner B (Review Engine) | SQLite `findings` | Increments by exactly 1 on change. |
| **Revision Log** | `rev-20261023-001` | Owner B (Review Engine) | SQLite `revisions` | Links old revision to new revision. |
| **Checklist Item** | `chk-waiting-period` | Owner B (Review Engine) | SQLite `checklist_items` | Links to `finding_id`. |
| **Packet** | `pkt-20261023-001` | Owner B (Review Engine) | SQLite `review_packets` | Preserved as immutable snapshot. |
| **Run** | `run-20261023-001` | Owner B (Agent Runner) | SQLite `review_packets` | Identifies single bounded execution. |

---

## 4. Error States & Handling

1. **Extraction Failures**:
   - Status set to `"unreadable"` or `"error"`.
   - Blank or unreadable pages do NOT throw uncaught exceptions; they produce explicit `ExtractedPage(is_blank=True)` records.
   - Unreadable documents must NEVER be assumed to imply missing policy exclusions.
2. **Citation Verification Failures**:
   - If quote matching fails due to whitespace, normalise spaces (`" ".join(text.split())`).
   - If quote is fabricated or belongs to another document/page, flag as `"needs_human_review"` or reject finding.
3. **Budget / Timeout Exhaustion**:
   - When tool step budget reaches 8 or timeout fires:
     - Set `stopped_reason = "tool_limit_reached"` or `"timeout"`.
     - Set `review_status = "incomplete"`.
     - Persist validated partial findings. Do not raise unhandled exception to UI.
