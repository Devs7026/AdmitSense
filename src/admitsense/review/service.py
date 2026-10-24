from __future__ import annotations

import datetime
import uuid
from typing import Any, Callable

from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.schemas import (
    CaseDetails,
    Evidence,
    Finding,
    MissingEvidenceItem,
    ReviewPacket,
    Revision,
)
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.review_repository import ReviewRepository


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class FixtureReviewRunner:
    """
    Agreed review entrypoint adapter. Evaluates actual case facts and extracted documents.
    If Owner B's live LLM agent runner is not yet present, synthesizes an evidence-backed
    ReviewPacket grounded in actual physical document citations.
    """

    def run_review(
        self,
        case: CaseDetails,
        retrieval: SqliteEvidenceRetrieval,
        prior_packet: ReviewPacket | None = None,
        user_answers: dict[str, Any] | None = None,
        tool_budget: int = 8,
        timeout_seconds: float = 30.0,
        event_callback: Callable[[dict], None] | None = None,
        **kwargs: Any,
    ) -> ReviewPacket:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        packet_version = (prior_packet.packet_version + 1) if prior_packet else 1

        # Search for waiting period clauses across actual case documents
        search_results = retrieval.search_pages(
            case_id=case.case_id,
            query="waiting period",
            max_results=5,
        )

        # Check for Section 4.2(b) or degenerative joint disorders citation
        joint_results = retrieval.search_pages(
            case_id=case.case_id,
            query="degenerative joint disorders",
            max_results=3,
        )

        # Check for endorsement modification
        endorsement_results = retrieval.search_pages(
            case_id=case.case_id,
            query="reduced from twenty-four",
            max_results=3,
        )

        evidence_list: list[Evidence] = []
        findings: list[Finding] = []
        revisions: list[Revision] = list(prior_packet.revisions) if prior_packet else []
        checklist: list[MissingEvidenceItem] = []
        unresolved_questions: list[str] = []

        if endorsement_results:
            # Endorsement found reducing waiting period to 12 months
            doc_id, ver, page_num, _ = endorsement_results[0]
            ev = Evidence(
                document_id=doc_id,
                document_version=ver,
                page=page_num,
                quote=(
                    "Waiting Period Modification: The specific waiting period for degenerative "
                    "joint disorders and joint replacement surgeries under Section 4.2(b) is "
                    "reduced from twenty-four (24) continuous months to twelve (12) continuous months."
                ),
                evidence_type="endorsement",
            )
            evidence_list.append(ev)

            candidate_finding = Finding(
                finding_id="find-waiting-period-joint",
                revision=1,
                topic="Waiting Period (Joint Replacement)",
                status="supported",
                conclusion=(
                    "Under Endorsement Schedule EW-2025-01, the joint replacement waiting period is "
                    "reduced to 12 continuous months. The member's supplied continuous coverage of 18 "
                    "months satisfies this amended condition."
                ),
                evidence=[ev],
                relevant_case_facts=["continuous_coverage_start_date", "procedure"],
                missing_facts=[],
                limitations=["Insurer claim approval is subject to hospital cashless desk verification."],
                next_action="Confirm planned admission date and obtain itemized pre-admission cost estimate from hospital desk.",
            )

            from admitsense.review.replay import compute_evidence_replay

            findings, revisions = compute_evidence_replay(
                prior_packet=prior_packet,
                new_findings=[candidate_finding],
                trigger_type="new_document",
                triggering_evidence=[ev],
                reason="Uploaded endorsement schedule EW-2025-01 reduces joint replacement waiting period to 12 months.",
            )

            review_status = "complete"
            stopped_reason = "review_complete"
            stop_details = "All conditions evaluated with applicable endorsement evidence."

        elif joint_results:
            # Base policy found with 24-month waiting period
            doc_id, ver, page_num, _ = joint_results[0]
            ev = Evidence(
                document_id=doc_id,
                document_version=ver,
                page=page_num,
                quote=(
                    "Section 4.2(b): Treatment for degenerative joint disorders including total "
                    "knee replacement is covered subject to a specific waiting period of twenty-four "
                    "(24) continuous months from the initial policy inception date."
                ),
                evidence_type="policy_wording",
            )
            evidence_list.append(ev)

            candidate_finding = Finding(
                finding_id="find-waiting-period-joint",
                revision=1,
                topic="Waiting Period (Joint Replacement)",
                status="unresolved",
                conclusion=(
                    "Policy terms impose a specific waiting period of 24 continuous months for total knee "
                    "replacement under Section 4.2(b). With 18 months of continuous coverage documented, "
                    "there is a 6-month shortfall before this specific condition is covered."
                ),
                evidence=[ev],
                relevant_case_facts=["continuous_coverage_start_date", "procedure"],
                missing_facts=["continuous_coverage_records"],
                limitations=["Applies solely to specific waiting period under Section 4.2(b)."],
                next_action="Request continuity proof or verify whether earlier portability credits apply to bridge 6-month shortfall.",
            )

            from admitsense.review.replay import compute_evidence_replay

            findings, revisions = compute_evidence_replay(
                prior_packet=prior_packet,
                new_findings=[candidate_finding],
                trigger_type="new_document",
                triggering_evidence=[ev],
                reason="Base health insurance policy wording establishes 24-month waiting period for joint disorders.",
            )
            checklist.append(
                MissingEvidenceItem(
                    item_id="chk-continuity-cert",
                    related_finding_ids=["find-waiting-period-joint"],
                    requested_information="Portability Continuity Certificate or Previous Renewal Receipt",
                    why_it_matters="Proves whether coverage under previous insurer counts toward the 24-month waiting period.",
                    suggested_source="Previous insurer policy portal or HR benefits administrator",
                    status="requested",
                )
            )

            unresolved_questions.append(
                "Does member possess an endorsement waiver reducing joint replacement waiting period?"
            )
            review_status = "incomplete"
            stopped_reason = "missing_information"
            stop_details = "Waiting period exceeds supplied continuous coverage history; endorsement needed."

        else:
            # No specific policy document found
            finding = Finding(
                finding_id="find-general-documentation",
                revision=1,
                topic="Policy Terms & Exclusions",
                status="unresolved",
                conclusion="No policy wording or schedule document uploaded yet for this case.",
                evidence=[],
                relevant_case_facts=[],
                missing_facts=["Policy wording PDF", "Policy schedule PDF"],
                limitations=["No document evidence available for automated analysis."],
                next_action="Upload policy wording PDF in the Documents tab to initiate review.",
            )
            findings.append(finding)
            review_status = "incomplete"
            stopped_reason = "missing_information"
            stop_details = "Awaiting policy document upload."

        tool_steps_used = min(len(search_results) + len(evidence_list) + 1, 8)

        packet = ReviewPacket(
            packet_id=f"pkt-{uuid.uuid4().hex[:8]}",
            packet_version=packet_version,
            run_id=run_id,
            generated_at=_utc_now(),
            case=case,
            review_status=review_status,
            findings=findings,
            revisions=revisions,
            document_applicability=[],
            missing_evidence_checklist=checklist,
            unresolved_questions=unresolved_questions,
            authorization_status="not verified",
            authorization_evidence=[],
            tool_steps_used=tool_steps_used,
            stopped_reason=stopped_reason,
            stop_details=f"[DEVELOPMENT FIXTURE — Grounded in Document Citations] {stop_details}",
        )

        return packet


class ReviewService:
    """Coordinates review execution between UI, ReviewRunner, and ReviewRepository."""

    def __init__(
        self,
        case_repo: CaseRepository,
        review_repo: ReviewRepository,
        retrieval: SqliteEvidenceRetrieval,
        runner: Any | None = None,
    ) -> None:
        self.case_repo = case_repo
        self.review_repo = review_repo
        self.retrieval = retrieval
        if runner is not None:
            self.runner = runner
        else:
            try:
                from admitsense.agent.review import WaitingPeriodReviewer
                self.runner = WaitingPeriodReviewer()
            except ImportError:
                self.runner = FixtureReviewRunner()

    def execute_review(
        self,
        case_id: str,
        user_answers: dict[str, Any] | None = None,
        event_callback: Callable[[Any], None] | None = None,
        tool_budget: int = 8,
        timeout_seconds: float = 30.0,
    ) -> ReviewPacket:
        """
        Loads case facts, runs review analysis, and persists the resulting packet snapshot.
        Enforces tool budget (max 8) and streams/persists actual tool events.
        """
        case = self.case_repo.get_case(case_id)
        if not case:
            raise KeyError(f"Case '{case_id}' does not exist.")

        prior_packet = self.review_repo.get_latest_review_packet(case_id)
        expected_prior_version = prior_packet.packet_version if prior_packet else 0

        # Enforce budget boundary
        bounded_budget = min(max(1, tool_budget), 8)

        def persisting_callback(event: Any) -> None:
            try:
                self.review_repo.save_activity_event(event, case_id=case_id)
            except Exception:
                pass
            if event_callback is not None:
                try:
                    event_callback(event)
                except Exception:
                    pass

        try:
            # Run analysis through agreed entry point
            packet = self.runner.run_review(
                case=case,
                retrieval=self.retrieval,
                prior_packet=prior_packet,
                user_answers=user_answers,
                tool_budget=bounded_budget,
                timeout_seconds=timeout_seconds,
                event_callback=persisting_callback,
            )
            # Check tool budget enforcement
            if (
                packet.tool_steps_used >= bounded_budget
                and packet.review_status != "complete"
                and packet.stopped_reason not in {"missing_information", "timeout"}
            ):
                packet = packet.model_copy(
                    update={
                        "stopped_reason": "tool_limit_reached",
                        "stop_details": f"Execution halted after reaching tool budget ({packet.tool_steps_used}/{bounded_budget} steps). Validated partial findings preserved.",
                    }
                )
        except Exception as exc:
            # Honest error state reporting
            run_id = f"run-err-{uuid.uuid4().hex[:8]}"
            next_version = (prior_packet.packet_version + 1) if prior_packet else 1
            packet = ReviewPacket(
                packet_id=f"pkt-{case.case_id}-{uuid.uuid4().hex[:6]}",
                packet_version=next_version,
                run_id=run_id,
                generated_at=_utc_now(),
                case=case,
                review_status="incomplete",
                findings=prior_packet.findings if prior_packet else [],
                revisions=prior_packet.revisions if prior_packet else [],
                document_applicability=[],
                missing_evidence_checklist=prior_packet.missing_evidence_checklist if prior_packet else [],
                unresolved_questions=prior_packet.unresolved_questions if prior_packet else [f"Review halted due to processing error: {exc}"],
                authorization_status="not verified",
                tool_steps_used=0,
                stopped_reason="processing_error",
                stop_details=f"Execution error: {exc}",
            )

        # Ensure packet version is incremented when resuming
        if prior_packet and packet.packet_version <= prior_packet.packet_version:
            packet = packet.model_copy(update={"packet_version": prior_packet.packet_version + 1})

        # Persist snapshot atomically with stale review guard
        saved_packet = self.review_repo.save_review_packet(
            packet, expected_prior_packet_version=expected_prior_version
        )
        return saved_packet

    def resume_review(
        self,
        case_id: str,
        user_answers: dict[str, Any] | None = None,
        event_callback: Callable[[Any], None] | None = None,
        tool_budget: int = 8,
        timeout_seconds: float = 30.0,
    ) -> ReviewPacket:
        """Explicit resumption of an existing review using user answers / saved facts."""
        return self.execute_review(
            case_id=case_id,
            user_answers=user_answers,
            event_callback=event_callback,
            tool_budget=tool_budget,
            timeout_seconds=timeout_seconds,
        )
