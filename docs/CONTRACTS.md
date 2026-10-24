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

    def search_pages(
        self,
        case_id: str,
        query: str,
        document_id: str | None = None,
        max_results: int = 5,
    ) -> list[tuple[str, str, int, str]]:
        """
        Search extracted page text across documents for a case.
        Returns list of (document_id, version, page_number, matching_snippet).
        Required because bounded agent (8-call limit) cannot linearly scan all pages.
        """
        ...
```

### 2.5 Review Persistence, Replay Snapshots & Atomic Revisions (AGREED)
```python
class StaleReviewError(RuntimeError):
    """Raised when an execution attempts to save against an outdated case/packet state."""
    pass

class ReviewRepository(Protocol):
    def save_review_packet(
        self,
        packet: ReviewPacket,
        expected_prior_packet_version: int | None = None,
    ) -> ReviewPacket:
        """
        Persists a review packet snapshot atomically in a single SQLite transaction:
        1. If expected_prior_packet_version is specified, verify current latest version in DB matches.
           If database has a newer version, raises StaleReviewError and aborts without mutating.
        2. Insert ReviewPacket metadata and JSON snapshot.
        3. Insert current findings with their revision number (retaining prior packet finding snapshots).
        4. Insert new Revision entries linking old and new finding revisions.
        5. Insert/update missing evidence checklist items.
        Rolls back completely if any insert fails.
        """
        ...

    def get_latest_review_packet(self, case_id: str) -> ReviewPacket | None:
        """Fetch the most recent review packet for a case."""
        ...

    def list_review_packets(self, case_id: str) -> list[ReviewPacket]:
        """List all historical review packet snapshots for a case."""
        ...

    def get_finding_snapshot(
        self,
        case_id: str,
        finding_id: str,
        revision: int,
    ) -> Finding | None:
        """Fetch the exact historical finding record and its evidence at a specific revision."""
        ...

    def get_finding_history(
        self,
        case_id: str,
        finding_id: str,
    ) -> list[Revision]:
        """Retrieve chronological audit trail of all revisions for a specific finding."""
        ...
```

### 2.6 Hospital Lookup Service & HTML Export Interfaces (AGREED - M6)
```python
from datetime import date
from typing import Literal, Protocol, Sequence
from pydantic import BaseModel, Field
from admitsense.schemas import HospitalRecordReference, ReviewPacket
from admitsense.documents.models import DocumentRecord

HospitalMatchStatus = Literal[
    "matched",
    "no_match",
    "ambiguous_match",
    "missing_information",
]

class HospitalLookupResult(BaseModel):
    status: HospitalMatchStatus
    record: HospitalRecordReference | None = None
    candidates: list[HospitalRecordReference] = Field(default_factory=list)
    query: str | None = None
    dataset_version: str = "v2026.1"
    dataset_date: date = Field(default_factory=lambda: date(2026, 10, 1))
    message: str = ""
    disclaimer: str = (
        "SYNTHETIC DEMONSTRATION DATASET. Not indicative of real network agreements "
        "or claim approval. Does not establish current insurer network agreement or cashless guarantee."
    )
    is_synthetic: bool = True

class HospitalLookupService(Protocol):
    def lookup_hospital(
        self,
        hospital_name: str | None,
        city: str | None = None,
    ) -> HospitalLookupResult:
        """Lookup a synthetic hospital record by name and optional city."""
        ...

def generate_review_packet_html(
    packet: ReviewPacket,
    hospital_result: HospitalLookupResult | None = None,
    hospital_record: HospitalRecordReference | None = None,
    available_documents: Sequence[DocumentRecord] | None = None,
) -> str:
    """
    Renders a standalone, self-contained HTML5 packet directly from a saved ReviewPacket snapshot.
    Deterministic export with zero live model queries or database writes during generation.
    All dynamic text is HTML-escaped. Standalone file opens independently in any browser.
    """
    ...
```

---

## 3. Proposed Agent & Review Interfaces (PROPOSED)

Owner B proposes the following agent, review runner, event telemetry, hospital reference, and replay interfaces for implementation in M2-B, M3-B, M4-B, and M5-B.

### 3.1 Inputs Supplied by Storage / Extraction
The review engine operates on domain models and retrieval protocols supplied by Owner A:
1. `CaseDetails`: Validated case attributes with provenance (`fact_sources`).
2. `EvidenceRetrieval`: Service providing `get_page_text`, `search_pages`, and `verify_citation`.
3. `DocumentRecord` list: Available active documents, their versions, and extraction statuses.
4. `HospitalDataset`: Dated, versioned local synthetic hospital data (for M6).

### 3.2 Review Engine Runner Interface
```python
from typing import Callable
from admitsense.schemas import CaseDetails, ReviewPacket

class ReviewRunner(Protocol):
    def run_review(
        self,
        case: CaseDetails,
        retrieval: EvidenceRetrieval,
        prior_packet: ReviewPacket | None = None,
        user_answers: dict[str, Any] | None = None,
        tool_budget: int = 8,
        timeout_seconds: float = 30.0,
        event_callback: Callable[[ToolActivityEvent], None] | None = None,
    ) -> ReviewPacket:
        """
        Executes bounded agent analysis:
        1. Evaluates case facts and retrieves relevant policy/endorsement pages.
        2. Validates evidence citations against actual physical page text.
        3. Generates supported, unresolved, or conflict findings.
        4. Enforces strict <= 8 tool calls; terminates gracefully on budget or timeout.
        5. If prior_packet is provided, triggers Evidence Change Replay computation.
        6. Returns pure Pydantic ReviewPacket; does NOT write directly to SQLite.
        """
        ...
```

### 3.3 Tool Activity Events & Streamlit Telemetry (AGREED)
Owner A's Streamlit workspace displays real-time agent activity via the following event schema:
```python
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class ToolActivityEvent(BaseModel):
    run_id: str
    step_number: int = Field(ge=1, le=8, description="1-based tool call step (max 8)")
    tool_name: Literal[
        "search_pages",
        "read_page",
        "verify_citation",
        "lookup_hospital",
    ]
    tool_arguments: dict[str, Any]
    status: Literal["invoked", "completed", "failed"]
    summary: str = Field(description="Caregiver-friendly action summary")
    error: str | None = None
    timestamp: datetime
```

### 3.4 Synthetic Hospital Record & Export Data Schema (AGREED - M6)
Hospital reference data is strictly separate from PDF citations and contains explicit dataset versions and dates. Export payloads consume saved snapshots deterministically without triggering live model invocations:
```python
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field

class HospitalRecordReference(BaseModel):
    record_id: str = Field(description="Unique synthetic record ID, e.g. hosp-synth-001")
    dataset_version: str = Field(description="Synthetic dataset version, e.g. v2026.1")
    dataset_date: date = Field(description="Publication date of synthetic dataset")
    hospital_name: str
    city: str
    network_tier: Literal["tier_1", "tier_2", "non_network", "unspecified"] = "unspecified"
    tpa_desk_contact: str | None = None
    is_synthetic: bool = True
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Synthetic hospital data for demonstration only.",
            "Does not establish current insurer network agreement or cashless guarantee."
        ]
    )

HospitalMatchStatus = Literal[
    "exact_match",
    "ambiguous_match",
    "no_match",
    "missing_input",
]

class HospitalLookupResult(BaseModel):
    status: HospitalMatchStatus
    query: str | None = None
    hospital: HospitalRecordReference | None = None
    candidate_matches: list[HospitalRecordReference] = []
    explanation: str
    is_synthetic: bool = True

def derive_desk_and_insurer_questions(
    case: CaseDetails,
    findings: list[Finding],
    checklist: list[MissingEvidenceItem] = [],
    hospital_reference: HospitalRecordReference | None = None,
    hospital_lookup_status: HospitalMatchStatus | None = None,
    document_applicability: list[DocumentApplicability] = [],
) -> list[str]:
    """Derives actionable questions for hospital desk and insurer staff.
    Removes obsolete questions once finding is supported. Retains unresolved gaps."""
    ...

def build_review_export_payload(packet: ReviewPacket) -> dict[str, Any]:
    """Pure deterministic transformation of saved ReviewPacket snapshot into
    structured, HTML-escapable export payload for Owner A's M6-A export preview."""
    ...
```

### 3.5 Evidence Change Replay Contract & Interfaces (AGREED - M5)

The Evidence Change Replay engine computes traceable revisions across document iterations and case-fact corrections:

#### 1. Input Case / Evidence Snapshot & Current Findings
- **Case & Provenance**: `CaseDetails` snapshot including all user-provided and document-derived facts with their `FactSource`.
- **Active Documents**: Case-scoped extracted documents and pages from `EvidenceRetrievalService`.
- **Prior State**: `prior_packet: ReviewPacket | None`. Contains the previous baseline `findings`, `revisions` history, and `missing_evidence_checklist`.
- **Follow-up Inputs**: `user_answers: dict[str, Any] | None` containing caregiver responses or corrected case facts.

#### 2. Stable Finding IDs & Revision Numbers
- Every finding maintains a permanent, unique `finding_id` per topic per case (e.g. `find-waiting-period-specific-condition-total-knee-replacement`, `find-waiting-period-initial-30-day`, `find-room-rent-inpatient-limits`).
- Findings start at `revision = 1`.
- When a finding experiences a substantive change in status, conclusion, evidence, or next action:
  - Its `revision` number increments by exactly 1 (`new_finding_revision = old_finding_revision + 1`).
  - An atomic `Revision` log entry is recorded linking the prior state to the revised state.
- Unchanged findings preserve their exact existing `revision` number, status, conclusion, citations, and finding ID.
- Avoid duplicate revisions: cosmetic re-runs, model paraphrasing, or identical duplicate uploads must NOT increment the revision number.

#### 3. Changed, Unchanged, and New Findings
- `ReviewPacket.findings` strictly contains the current (latest) revision of each active finding. Superseded older revisions are moved to `ReviewPacket.revisions`.
- Newly introduced conditions, endorsements, or policy conflicts create a new `Finding` with `revision = 1`.
- Unrelated findings (e.g. initial 30-day waiting period, room rent limits) remain intact and untouched when an endorsement only modifies specific joint replacements.

#### 4. Document and Case-Fact Triggers
- `trigger_type: Literal["new_document", "user_correction", "case_details_changed"]`
  - `"new_document"`: Triggered by upload or version update of an endorsement, schedule, or hospital bill. Requires `triggering_evidence: list[Evidence]` citing the physical page and quote.
  - `"user_correction"`: Triggered by user follow-up answer or caregiver input correction. Requires `changed_case_facts: list[CaseFactName]`.
  - `"case_details_changed"`: Triggered by case date or procedure modification. Requires `changed_case_facts: list[CaseFactName]`.

#### 5. Persistence Responsibility & Stale-Result Handling
- **Persistence Boundary**: Review engine (`BoundedReviewAgent` / `compute_evidence_replay`) is side-effect free. It returns a validated `ReviewPacket` without writing directly to SQLite or filesystem. Owner A's `ReviewService` and `ReviewRepository` handle transactional persistence in SQLite (`review_packets`, `findings`, `revisions`, `checklist_items`).
- **Stale-Result & Early Stopping Handling**: If a reassessment run stops early (e.g., `tool_limit_reached` or `timeout`), findings that could not be reassessed retain explicit limitations and an honest `review_status="incomplete"` with `stopped_reason`. The agent never falsely reports completion or implies that all findings are up to date when the tool budget or timeout halted execution.

```python
def compute_evidence_replay(
    prior_packet: ReviewPacket | None,
    new_findings: list[Finding],
    trigger_type: Literal["new_document", "user_correction", "case_details_changed"],
    triggering_evidence: list[Evidence] = [],
    changed_case_facts: list[CaseFactName] = [],
    reason: str = "",
) -> tuple[list[Finding], list[Revision]]:
    """
    Computes delta between prior_packet findings and new findings:
    1. Distinguishes three finding categories:
       - Changed findings: status, conclusion, evidence, or next action differs from prior finding.
         Finding.revision increments by exactly 1 (old_finding.revision + 1).
         A Revision record is emitted linking old to new revision.
       - Unchanged findings: status, conclusion, evidence, and next action match prior finding.
         Finding.revision remains at old_finding.revision.
         Zero new Revision records are emitted for unchanged findings.
       - New findings: finding_id did not exist in prior_packet.
         Finding.revision is set to 1. No prior Revision record.
    2. Enforces trigger integrity:
       - trigger_type='new_document' requires triggering_evidence.
       - trigger_type in {'user_correction', 'case_details_changed'} requires changed_case_facts.
    3. Preserves accumulated prior revisions, appending newly generated revisions.
    4. Returns (updated_findings_list, all_revisions_list).
    """
    ...
```

### 3.6 Persistence Boundaries & Separation of Concerns
- **Owner B (Agent / Review)**: Pure deterministic & LLM logic. Generates and validates `ReviewPacket`, `Finding`, `Revision`, and `ToolActivityEvent`. Does not write to SQLite or disk directly.
- **Owner A (Storage / UI)**: Invokes `ReviewRunner.run_review`, streams `ToolActivityEvent` to the Streamlit UI, rejects stale reviews, and commits the resulting `ReviewPacket` to SQLite via `ReviewRepository.save_review_packet`.

### 3.7 LLM Provider & Grounding Contract (Milestone M7)
Owner B implements live model inference using the Groq API:

```python
class LLMReviewClient(Protocol):
    @property
    def is_available(self) -> bool:
        """Returns True only when groq SDK is present and non-empty GROQ_API_KEY is configured."""
        ...

    @property
    def status_summary(self) -> dict[str, Any]:
        """Provides diagnostic metadata regarding provider, model, and credential presence."""
        ...

    def evaluate_clause_applicability(
        self,
        case_procedure: str,
        clause_text: str,
        document_name: str,
        page_number: int,
    ) -> dict[str, Any]:
        """Evaluates clause applicability.
        Raises MissingCredentialsError if GROQ_API_KEY is not configured.
        Raises LLMProviderError on network, quota, or rate-limit failure.
        """
        ...
```

**Non-Negotiable LLM Invariants**:
1. **Configured Model**: Defaults to `llama-3.3-70b-versatile`, customizable via environment variable `GROQ_MODEL`.
2. **Credential Requirement**: Environment variable `GROQ_API_KEY`.
3. **Transparent Credential Diagnostics**: Missing `GROQ_API_KEY` is transparently reported via `status_summary["credentials_configured"] = False`. The system NEVER silently fakes live LLM invocation or invents model responses.
4. **Resilient Failure Handling**: Network timeouts and provider errors (`LLMProviderError`) do not crash the review runner; the agent falls back safely to deterministic rule-based evaluation.
5. **Strict Grounding Rule**: Every quote or clause suggested by an LLM is verified against physical document page text using `verify_citation`. Fabricated or hallucinated quotes are rejected.
6. **Authorization Invariant**: Model inference is strictly advisory and administrative; `authorization_status` is ALWAYS `"not verified"`. Pre-authorization guarantees and cashless approval inferences are forbidden.

---

## 4. ID Assignment & Ownership Matrix

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
| **Hospital Record** | `hosp-synth-001` | Owner B (Dataset Author) | JSON / SQLite | Dated, versioned synthetic hospital ID. |

---

## 5. Error States & Handling

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
4. **Validation Failures in Review Engine**:
   - If a candidate finding fails Pydantic schema validation, quarantine it as `"needs_human_review"` rather than crashing the overall review run.

