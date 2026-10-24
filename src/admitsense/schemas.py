from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

FindingStatus = Literal[
    "supported",
    "unresolved",
    "conflict",
    "needs_human_review",
]

ReviewStatus = Literal[
    "complete",
    "incomplete",
    "failed",
]

AuthorizationStatus = Literal[
    "not verified",
    "pending insurer review",
]

StopReason = Literal[
    "review_complete",
    "missing_information",
    "conflicting_evidence",
    "needs_human_review",
    "tool_limit_reached",
    "timeout",
    "processing_error",
]

EvidenceType = Literal[
    "policy_wording",
    "policy_schedule",
    "endorsement",
    "hospital_estimate",
    "admission_document",
    "insurer_correspondence",
    "other",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SchemaModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class Evidence(SchemaModel):
    """A quotation from one immutable document version."""

    document_id: NonEmptyStr
    document_version: NonEmptyStr
    page: int = Field(gt=0, description="Physical PDF page number, starting at 1.")
    quote: NonEmptyStr
    evidence_type: EvidenceType


class FactSource(SchemaModel):
    """Records where a case fact came from, without implying verification."""

    source_type: Literal[
        "user_provided",
        "document",
        "derived",
    ]
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.source_type == "document" and not self.evidence:
            raise ValueError("Document-derived facts require evidence.")

        if self.source_type == "derived" and not self.explanation:
            raise ValueError("Derived facts require a derivation explanation.")

        return self


CaseFactName = Literal[
    "member_name",
    "policy_id",
    "policy_start_date",
    "continuous_coverage_start_date",
    "planned_admission_date",
    "policy_age_months",
    "procedure",
    "hospital_name",
    "estimated_cost",
]


class CaseDetails(SchemaModel):
    case_id: NonEmptyStr

    # Unknown facts remain None; do not invent placeholder values.
    member_name: NonEmptyStr | None = None
    policy_id: NonEmptyStr | None = None
    policy_start_date: date | None = None
    continuous_coverage_start_date: date | None = None
    planned_admission_date: date | None = None

    # Informational only. Use dates and applicable policy rules for checks.
    policy_age_months: int | None = Field(default=None, ge=0)

    procedure: NonEmptyStr | None = None
    hospital_name: NonEmptyStr | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    currency: Literal["INR"] = "INR"

    fact_sources: dict[CaseFactName, FactSource] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_fact_sources(self) -> Self:
        fact_names = (
            "member_name",
            "policy_id",
            "policy_start_date",
            "continuous_coverage_start_date",
            "planned_admission_date",
            "policy_age_months",
            "procedure",
            "hospital_name",
            "estimated_cost",
        )

        for name in fact_names:
            if getattr(self, name) is not None and name not in self.fact_sources:
                raise ValueError(f"Provided fact '{name}' requires a source.")

        for name in self.fact_sources:
            if getattr(self, name) is None:
                raise ValueError(f"Source provided for missing fact '{name}'.")

        return self


class DocumentApplicability(SchemaModel):
    """Extracted applicability metadata; not an automatic override decision."""

    document_id: NonEmptyStr
    document_version: NonEmptyStr

    policy_id: NonEmptyStr | None = None
    member_name: NonEmptyStr | None = None
    issued_on: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    modified_topics: list[NonEmptyStr] = Field(default_factory=list)

    status: Literal[
        "not_checked",
        "applicable",
        "not_applicable",
        "uncertain",
    ] = "not_checked"

    evidence: list[Evidence] = Field(default_factory=list)
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_applicability(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot precede effective_from.")

        if self.status != "not_checked" and not self.reason:
            raise ValueError("An applicability assessment requires a reason.")

        if self.status in {"applicable", "not_applicable"} and not self.evidence:
            raise ValueError("A definitive applicability assessment needs evidence.")

        return self


class Finding(SchemaModel):
    """'Supported' describes the conclusion, not insurance approval."""

    finding_id: NonEmptyStr
    revision: int = Field(default=1, ge=1)
    topic: NonEmptyStr
    status: FindingStatus
    conclusion: NonEmptyStr

    evidence: list[Evidence] = Field(default_factory=list)
    relevant_case_facts: list[CaseFactName] = Field(default_factory=list)
    missing_facts: list[NonEmptyStr] = Field(default_factory=list)
    limitations: list[NonEmptyStr] = Field(default_factory=list)

    next_action: NonEmptyStr
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_finding(self) -> Self:
        if self.status == "supported" and not self.evidence:
            raise ValueError("Supported findings require evidence.")

        if self.status == "unresolved" and not (
            self.missing_facts or self.limitations
        ):
            raise ValueError(
                "Unresolved findings must explain missing facts or limitations."
            )

        return self


class MissingEvidenceItem(SchemaModel):
    item_id: NonEmptyStr
    related_finding_ids: list[NonEmptyStr] = Field(min_length=1)
    requested_information: NonEmptyStr
    why_it_matters: NonEmptyStr
    suggested_source: NonEmptyStr | None = None

    status: Literal[
        "requested",
        "user_does_not_have",
        "provided_pending_review",
        "resolved",
    ] = "requested"

    resolution_note: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.status == "resolved" and not self.resolution_note:
            raise ValueError("Resolved checklist items require a resolution note.")
        return self


class Revision(SchemaModel):
    revision_id: NonEmptyStr
    finding_id: NonEmptyStr

    old_finding_revision: int = Field(ge=1)
    new_finding_revision: int = Field(ge=2)

    old_conclusion: NonEmptyStr
    new_conclusion: NonEmptyStr
    old_status: FindingStatus
    new_status: FindingStatus

    trigger_type: Literal[
        "new_document",
        "user_correction",
        "case_details_changed",
    ]
    triggering_evidence: list[Evidence] = Field(default_factory=list)
    changed_case_facts: list[CaseFactName] = Field(default_factory=list)

    reason: NonEmptyStr
    affected_topics: list[NonEmptyStr] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.new_finding_revision != self.old_finding_revision + 1:
            raise ValueError("Finding revisions must increase by exactly one.")

        if self.trigger_type == "new_document" and not self.triggering_evidence:
            raise ValueError("Document-triggered revisions require evidence.")

        if self.trigger_type in {
            "user_correction",
            "case_details_changed",
        } and not self.changed_case_facts:
            raise ValueError("Fact-triggered revisions must name changed facts.")

        return self


class HospitalRecordReference(SchemaModel):
    """Synthetic hospital reference record conforming to CONTRACTS.md Section 3.4."""

    record_id: NonEmptyStr = Field(description="Unique synthetic record ID, e.g. hosp-synth-001")
    dataset_version: NonEmptyStr = Field(description="Synthetic dataset version, e.g. v2026.1")
    dataset_date: date = Field(description="Publication date of synthetic dataset")
    hospital_name: NonEmptyStr
    city: NonEmptyStr
    network_tier: Literal["tier_1", "tier_2", "non_network", "unspecified"] = "unspecified"
    tpa_desk_contact: NonEmptyStr | None = None
    limitations: list[NonEmptyStr] = Field(
        default_factory=lambda: [
            "Synthetic hospital data for demonstration only.",
            "Does not establish current insurer network agreement or cashless guarantee.",
        ]
    )


class ReviewPacket(SchemaModel):
    packet_id: NonEmptyStr
    packet_version: int = Field(default=1, ge=1)
    run_id: NonEmptyStr
    generated_at: datetime = Field(default_factory=utc_now)

    case: CaseDetails
    review_status: ReviewStatus = "incomplete"

    # Only the current revision of each finding belongs in this list.
    findings: list[Finding] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    document_applicability: list[DocumentApplicability] = Field(
        default_factory=list
    )
    missing_evidence_checklist: list[MissingEvidenceItem] = Field(
        default_factory=list
    )
    unresolved_questions: list[NonEmptyStr] = Field(default_factory=list)

    authorization_status: AuthorizationStatus = "not verified"
    authorization_evidence: list[Evidence] = Field(default_factory=list)

    # Synthetic hospital reference directory entry (M6)
    hospital_record: HospitalRecordReference | None = None

    # This validates recorded usage; the execution loop enforces the cap.
    tool_steps_used: int = Field(default=0, ge=0, le=8)
    stopped_reason: StopReason
    stop_details: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_packet(self) -> Self:
        if (
            self.authorization_status == "pending insurer review"
            and not self.authorization_evidence
        ):
            raise ValueError(
                "Pending insurer review requires evidence of submission."
            )

        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError(
                "Packet must contain only one current revision per finding."
            )

        known_ids = set(finding_ids)
        for item in self.missing_evidence_checklist:
            if not set(item.related_finding_ids).issubset(known_ids):
                raise ValueError("Checklist item references an unknown finding.")

        for revision in self.revisions:
            if revision.finding_id not in known_ids:
                raise ValueError("Revision references an unknown finding.")

        if self.review_status == "complete":
            if not self.findings:
                raise ValueError("A completed review must contain findings.")
            if self.stopped_reason != "review_complete":
                raise ValueError(
                    "A completed review requires the review_complete stop reason."
                )

        if (
            self.stopped_reason == "review_complete"
            and self.review_status != "complete"
        ):
            raise ValueError(
                "review_complete requires a completed review status."
            )

        return self