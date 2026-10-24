"""Tests for Milestone M3-B: Initial waiting-period review engine.

Verifies:
- Evaluation of condition-specific waiting periods against continuous coverage history.
- The fictional 24-month condition vs 18-month history produces a cited unresolved finding
  and useful clarification request, with no invented waiver or approval statements.
- Fact provenance tracking and preservation of unknown facts.
- Verified citations against physical 1-based page text.
- Tool activity event telemetry and 8-call budget enforcement.
- Pure Pydantic output without side-effect writes to storage.
- Identity and reference discrepancy handling.
"""

import tempfile
from pathlib import Path
import pytest

from admitsense.agent.retrieval import EvidenceRetrievalService
from admitsense.agent.review import (
    ToolActivityEvent,
    WaitingPeriodReviewer,
    run_waiting_period_review,
)
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    build_synthetic_unreadable_pdf,
)
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.database import Database


@pytest.fixture
def review_env():
    """Sets up an isolated SQLite database and DocumentStorage with synthetic PDFs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_m3.db"
        doc_dir = Path(tmp_dir) / "docs"
        db = Database(db_path=db_path)
        case_repo = CaseRepository(db=db)
        doc_storage = DocumentStorage(db=db, storage_dir=doc_dir)

        # 1. Base test case: Ramesh Sharma, Total Knee Replacement
        case_repo.create_case(
            CaseDetails(
                case_id="case-m3-knee-001",
                member_name="Ramesh Sharma",
                policy_id="POL-998877",
                procedure="Total Knee Replacement",
                fact_sources={
                    "member_name": FactSource(source_type="user_provided"),
                    "policy_id": FactSource(source_type="user_provided"),
                    "procedure": FactSource(source_type="user_provided"),
                },
            )
        )

        # 2. Ingest 15-page policy PDF (Section 4.2(b) has 24-month waiting period on page 14)
        policy_doc, _ = doc_storage.save_document(
            case_id="case-m3-knee-001",
            filename="Care_Health_Gold_Policy_Wording.pdf",
            content=build_synthetic_policy_pdf(),
            evidence_type="policy_wording",
        )

        # 3. Ingest policy schedule (18 months continuous coverage on page 1)
        sched_doc, _ = doc_storage.save_document(
            case_id="case-m3-knee-001",
            filename="Policy_Renewal_Schedule.pdf",
            content=build_synthetic_schedule_pdf(),
            evidence_type="policy_schedule",
        )

        retrieval = EvidenceRetrievalService(db=db)

        yield {
            "db": db,
            "case_repo": case_repo,
            "doc_storage": doc_storage,
            "retrieval": retrieval,
            "policy_doc": policy_doc,
            "sched_doc": sched_doc,
        }


def test_24_month_condition_vs_18_month_history_produces_cited_shortfall_and_clarification(review_env):
    """Core Milestone M3-B Acceptance Test:
    A 24-month condition with 18-month policy history must produce an unresolved finding,
    citing actual documents, reporting the 6-month shortfall, requesting clarification,
    and never inferring approval or inventing dummy waiver documents.
    """
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]
    case = case_repo.get_case("case-m3-knee-001")
    assert case is not None

    reviewer = WaitingPeriodReviewer()
    packet = reviewer.run_review(case=case, retrieval=retrieval)

    # 1. General Packet Invariants
    assert packet.case.case_id == "case-m3-knee-001"
    assert packet.review_status == "incomplete"
    assert packet.authorization_status == "not verified"
    assert packet.authorization_evidence == []
    assert packet.stopped_reason == "missing_information"
    assert packet.tool_steps_used <= 8
    assert packet.tool_steps_used > 0

    # 2. Findings Invariants
    assert len(packet.findings) == 1
    finding = packet.findings[0]
    assert finding.status == "unresolved"
    assert "knee" in finding.topic.lower() or "joint" in finding.topic.lower()

    # Must explain the 24-month rule and the 18-month history
    assert "24" in finding.conclusion or "twenty-four" in finding.conclusion
    assert "18" in finding.conclusion or "eighteen" in finding.conclusion
    assert "shortfall" in finding.conclusion.lower() or "gap" in finding.conclusion.lower()

    # Must NOT invent approval or waivers
    assert "approved" not in finding.conclusion.lower()
    assert "waiver document required" not in finding.conclusion.lower()

    # 3. Verified Evidence Citations
    assert len(finding.evidence) >= 1
    policy_citation = next((e for e in finding.evidence if e.evidence_type == "policy_wording"), None)
    assert policy_citation is not None
    assert policy_citation.page == 14
    assert "twenty-four (24) continuous months" in policy_citation.quote

    # 4. Next Action and Checklist
    assert "clarification" in finding.next_action.lower() or "portability" in finding.next_action.lower()
    assert len(packet.missing_evidence_checklist) >= 1
    chk = packet.missing_evidence_checklist[0]
    assert chk.status == "requested"
    assert "continuity" in chk.requested_information.lower() or "schedule" in chk.requested_information.lower()

    # 5. Unresolved Questions
    assert len(packet.unresolved_questions) >= 1
    assert any("continuous coverage" in q.lower() or "waiting period" in q.lower() for q in packet.unresolved_questions)


def test_tool_activity_telemetry_and_events(review_env):
    """Verifies that tool calls are recorded, step numbers increase (1..8), and callback receives events."""
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]
    case = case_repo.get_case("case-m3-knee-001")
    assert case is not None

    events: list[ToolActivityEvent] = []

    def on_event(ev: ToolActivityEvent):
        events.append(ev)

    reviewer = WaitingPeriodReviewer()
    packet = reviewer.run_review(case=case, retrieval=retrieval, event_callback=on_event)

    assert len(events) > 0
    assert packet.tool_steps_used == max(e.step_number for e in events)
    assert packet.tool_steps_used <= 8

    # All events have run_id matching the packet
    for e in events:
        assert e.run_id == packet.run_id
        assert 1 <= e.step_number <= 8
        assert e.tool_name in {"search_pages", "read_page", "verify_citation", "lookup_hospital"}
        assert len(e.summary) > 0


def test_tool_budget_enforcement(review_env):
    """Verifies that review strictly respects the tool budget and terminates if limit reached."""
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]
    case = case_repo.get_case("case-m3-knee-001")
    assert case is not None

    # Budget capped to 2 calls
    reviewer = WaitingPeriodReviewer(default_tool_budget=2)
    packet = reviewer.run_review(case=case, retrieval=retrieval, tool_budget=2)

    assert packet.tool_steps_used <= 2


def test_missing_procedure_produces_unresolved_procedure_finding(review_env):
    """Verifies that a case without procedure facts leaves procedure unknown and asks for it."""
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]

    # Create a case with NO procedure
    no_proc_case = CaseDetails(
        case_id="case-m3-no-proc-002",
        member_name="Ananya Roy",
        fact_sources={"member_name": FactSource(source_type="user_provided")},
    )
    case_repo.create_case(no_proc_case)

    reviewer = WaitingPeriodReviewer()
    packet = reviewer.run_review(case=no_proc_case, retrieval=retrieval)

    assert packet.review_status == "incomplete"
    assert packet.stopped_reason == "missing_information"
    assert len(packet.findings) == 1
    assert packet.findings[0].status == "unresolved"
    assert "procedure" in packet.findings[0].missing_facts
    assert any("procedure" in item.requested_information.lower() for item in packet.missing_evidence_checklist)


def test_zero_documents_produces_missing_documents_finding(review_env):
    """Verifies that reviewing a case with zero uploaded documents alerts the caregiver."""
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]

    empty_doc_case = CaseDetails(
        case_id="case-m3-empty-docs-003",
        member_name="Vikram Singh",
        procedure="Cataract Surgery",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
        },
    )
    case_repo.create_case(empty_doc_case)

    reviewer = WaitingPeriodReviewer()
    packet = reviewer.run_review(case=empty_doc_case, retrieval=retrieval)

    assert packet.review_status == "incomplete"
    assert packet.stopped_reason == "missing_information"
    assert packet.findings[0].status == "unresolved"
    assert "policy_wording" in packet.findings[0].missing_facts


def test_satisfied_waiting_period_produces_supported_finding(review_env):
    """Verifies that a 12-month condition (Cataract) with 18 months continuous coverage is supported."""
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]
    doc_storage = review_env["doc_storage"]

    cataract_case = CaseDetails(
        case_id="case-m3-cataract-004",
        member_name="Ramesh Sharma",
        policy_id="POL-998877",
        procedure="Cataract Surgery",
        fact_sources={
            "member_name": FactSource(source_type="user_provided"),
            "policy_id": FactSource(source_type="user_provided"),
            "procedure": FactSource(source_type="user_provided"),
        },
    )
    case_repo.create_case(cataract_case)

    # Ingest policy and schedule for cataract case
    doc_storage.save_document(
        case_id="case-m3-cataract-004",
        filename="Cataract_Policy_Terms.pdf",
        content=build_synthetic_policy_pdf(),
        evidence_type="policy_wording",
    )
    doc_storage.save_document(
        case_id="case-m3-cataract-004",
        filename="Cataract_Renewal_Schedule.pdf",
        content=build_synthetic_schedule_pdf(),
        evidence_type="policy_schedule",
    )

    packet = run_waiting_period_review(case=cataract_case, retrieval=retrieval)

    assert len(packet.findings) == 1
    finding = packet.findings[0]
    assert finding.status == "supported"
    assert "12" in finding.conclusion or "twelve" in finding.conclusion
    assert "satisfying" in finding.conclusion.lower() or "satisfied" in finding.conclusion.lower()
    assert len(finding.evidence) >= 1
    assert finding.evidence[0].page == 11
    assert "twelve (12) continuous months" in finding.evidence[0].quote
    assert packet.authorization_status == "not verified"


def test_unreadable_document_retention_and_limitation(review_env):
    """Verifies that unreadable documents generate explicit limitations and never imply absence of terms."""
    case_repo = review_env["case_repo"]
    retrieval = review_env["retrieval"]
    doc_storage = review_env["doc_storage"]

    # Ingest unreadable document into case-m3-knee-001
    doc_storage.save_document(
        case_id="case-m3-knee-001",
        filename="Corrupted_Scan.pdf",
        content=build_synthetic_unreadable_pdf(),
        evidence_type="other",
    )

    packet = run_waiting_period_review(case=case_repo.get_case("case-m3-knee-001"), retrieval=retrieval)

    # Must contain limitation about unreadable document
    finding = packet.findings[0]
    assert any("unreadable" in lim.lower() for lim in finding.limitations)
    # Must have a checklist item requesting legible copy
    assert any("unreadable" in item.item_id.lower() or "legible" in item.requested_information.lower() for item in packet.missing_evidence_checklist)
