from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from admitsense.documents.models import DocumentRecord, ExtractedPage
from admitsense.documents.retrieval import SqliteEvidenceRetrieval
from admitsense.documents.storage import DocumentStorage
from admitsense.documents.synthetic import (
    build_synthetic_endorsement_pdf,
    build_synthetic_hospital_estimate_pdf,
    build_synthetic_policy_pdf,
    build_synthetic_schedule_pdf,
    build_synthetic_unreadable_pdf,
)
from admitsense.review.service import ReviewService
from admitsense.schemas import CaseDetails, Evidence, ReviewPacket
from admitsense.storage.case_repository import CaseRepository
from admitsense.storage.review_repository import ReviewRepository
from admitsense.ui.components import render_authorization_badge


def _load_sample_packet_fixture(scenario: str = "supported_finding") -> ReviewPacket | None:
    try:
        from tests.fixtures import get_sample_packet
        return get_sample_packet(scenario)
    except Exception:
        pass

    fixture_path = Path("tests") / "fixtures" / "sample_packet.json"
    if fixture_path.exists():
        try:
            with open(fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ReviewPacket.model_validate(data)
        except Exception:
            return None
    return None


def render_workspace_view(
    repo: CaseRepository,
    doc_storage: DocumentStorage | None = None,
    retrieval: SqliteEvidenceRetrieval | None = None,
    review_repo: ReviewRepository | None = None,
    review_service: ReviewService | None = None,
) -> None:
    case_id = st.session_state.get("current_case_id")
    if not case_id:
        st.error("No case selected.")
        if st.button("⬅️ Return to Cases"):
            st.session_state.current_view = "home"
            st.rerun()
        return

    case = repo.get_case(case_id)
    if not case:
        st.error(f"Case '{case_id}' was not found in the database.")
        if st.button("⬅️ Return to Cases"):
            st.session_state.current_view = "home"
            st.rerun()
        return

    storage = doc_storage or DocumentStorage(db=repo.db)
    ev_retrieval = retrieval or SqliteEvidenceRetrieval(db=repo.db)
    r_repo = review_repo or ReviewRepository(db=repo.db)
    r_service = review_service or ReviewService(
        case_repo=repo, review_repo=r_repo, retrieval=ev_retrieval
    )

    # Top Navigation Row
    top_c1, top_c2, top_c3, top_c4 = st.columns([2, 4, 2, 2])
    with top_c1:
        if st.button("⬅️ Back to Cases", use_container_width=True):
            st.session_state.current_view = "home"
            st.rerun()
    with top_c2:
        patient_label = case.member_name or "Unknown Patient"
        st.markdown(
            f"<h3 style='margin: 0; padding: 0;'>Case: <code>{case.case_id}</code> &nbsp;|&nbsp; {patient_label}</h3>",
            unsafe_allow_html=True,
        )
    with top_c3:
        if st.button("✏️ Edit Case Facts", use_container_width=True):
            st.session_state.current_view = "setup"
            st.rerun()
    with top_c4:
        # Review available documents action trigger
        if st.button(
            "🔍 Review Available Documents",
            type="primary",
            use_container_width=True,
            help="Trigger automated policy review on ingested documents and case facts",
        ):
            with st.spinner("Analyzing case facts and policy documents..."):
                try:
                    packet = r_service.execute_review(case.case_id)
                    st.toast(f"Review completed: {packet.review_status.upper()}", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Review execution failed: {e}")

    st.markdown("---")

    # Fetch latest persisted ReviewPacket from SQLite for this case
    persisted_packet = r_repo.get_latest_review_packet(case.case_id)

    # Authorisation Status Banner (Non-negotiable invariant: strictly separate, defaults to unverified)
    auth_status = persisted_packet.authorization_status if persisted_packet else "not verified"
    render_authorization_badge(status=auth_status)

    # Next Action Banner
    if persisted_packet and persisted_packet.findings:
        next_action_text = persisted_packet.findings[0].next_action
    else:
        sample_packet_for_next = _load_sample_packet_fixture()
        next_action_text = (
            sample_packet_for_next.findings[0].next_action
            if (sample_packet_for_next and sample_packet_for_next.findings)
            else "Upload policy schedule or hospital estimate to initiate automated review."
        )

    st.markdown(
        f"""
        <div class="next-action-card">
            <h4 style="margin: 0 0 0.35rem 0; color: #1e3a8a;">Recommended Next Action</h4>
            <p style="margin: 0; color: #1e40af; font-size: 0.95rem;">{next_action_text}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Tab selection state
    tab_titles = [
        "📋 Case Facts & Provenance",
        "🔍 Findings & Review",
        "📄 Documents & Evidence Viewer",
        "🔄 Change Replay (M5)",
        "📥 Packet Export (M6)",
    ]
    tab_facts, tab_review, tab_docs, tab_replay, tab_export = st.tabs(tab_titles)

    # 1. Case Facts & Provenance
    with tab_facts:
        st.subheader("Supplied Case Facts")
        st.caption("Facts without user input remain explicitly `None` (Unknown).")

        fact_definitions = [
            ("Patient / Member Name", case.member_name, "member_name"),
            ("Policy Identifier", case.policy_id, "policy_id"),
            ("Planned Procedure", case.procedure, "procedure"),
            ("Hospital Name", case.hospital_name, "hospital_name"),
            (
                "Planned Admission Date",
                case.planned_admission_date.strftime("%d %b %Y")
                if case.planned_admission_date
                else None,
                "planned_admission_date",
            ),
            (
                "Continuous Coverage Start Date",
                case.continuous_coverage_start_date.strftime("%d %b %Y")
                if case.continuous_coverage_start_date
                else None,
                "continuous_coverage_start_date",
            ),
            (
                "Estimated Cost",
                f"₹{case.estimated_cost:,.2f}" if case.estimated_cost else None,
                "estimated_cost",
            ),
        ]

        for label, val, fact_key in fact_definitions:
            with st.container():
                fc1, fc2, fc3 = st.columns([3, 4, 3])
                with fc1:
                    st.markdown(f"**{label}**")
                with fc2:
                    if val is not None:
                        st.markdown(f"<code>{val}</code>", unsafe_allow_html=True)
                    else:
                        st.markdown("<span style='color: #94a3b8; font-style: italic;'>Unknown (Not provided)</span>", unsafe_allow_html=True)
                with fc3:
                    if fact_key in case.fact_sources:
                        src = case.fact_sources[fact_key]
                        st.markdown(
                            f"<span class='provenance-tag provenance-user'>{src.source_type}</span>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            "<span class='provenance-tag' style='background: #f1f5f9; color: #94a3b8;'>no source</span>",
                            unsafe_allow_html=True,
                        )
                st.markdown("<hr style='margin: 0.35rem 0;'>", unsafe_allow_html=True)

    # 2. Findings & Review
    with tab_review:
        if persisted_packet:
            # Render persisted review packet from SQLite
            status_color = "#16a34a" if persisted_packet.review_status == "complete" else "#ea580c"
            st.markdown(
                f"""
                <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 0.85rem 1rem; margin-bottom: 1rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; font-size: 1.1rem; color: #1e293b;">
                            Persisted Review Packet: <code>{persisted_packet.packet_id}</code> (v{persisted_packet.packet_version})
                        </span>
                        <span style="background-color: {status_color}; color: white; padding: 0.25rem 0.65rem; border-radius: 4px; font-weight: 700; font-size: 0.85rem; text-transform: uppercase;">
                            {persisted_packet.review_status}
                        </span>
                    </div>
                    <div style="display: flex; gap: 1.5rem; margin-top: 0.5rem; font-size: 0.85rem; color: #64748b;">
                        <span>Run ID: <code>{persisted_packet.run_id}</code></span>
                        <span>Tool Steps Used: <strong>{persisted_packet.tool_steps_used} / 8</strong></span>
                        <span>Stop Reason: <strong>{persisted_reason_label(persisted_packet.stopped_reason)}</strong></span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if persisted_packet.stop_details:
                st.caption(f"ℹ️ {persisted_packet.stop_details}")

            st.markdown("### Findings")
            for finding in persisted_packet.findings:
                status_badge = {
                    "supported": ("#16a34a", "SUPPORTED"),
                    "unresolved": ("#ea580c", "UNRESOLVED"),
                    "conflict": ("#dc2626", "CONFLICT"),
                    "needs_human_review": ("#7c3aed", "NEEDS HUMAN REVIEW"),
                }.get(finding.status, ("#64748b", finding.status.upper()))

                with st.expander(
                    f"{finding.topic} — {status_badge[1]} (Rev {finding.revision})",
                    expanded=True,
                ):
                    st.markdown(f"**Conclusion:** {finding.conclusion}")

                    # Citation Links with navigation to Evidence Viewer
                    if finding.evidence:
                        st.markdown("**Cited Evidence:**")
                        for idx, ev in enumerate(finding.evidence):
                            c_col1, c_col2 = st.columns([4, 1])
                            with c_col1:
                                st.markdown(
                                    f"""
                                    <div style="background-color: #f8fafc; border-left: 3px solid #64748b; padding: 0.5rem 0.75rem; font-size: 0.88rem;">
                                        <em>"{ev.quote}"</em><br>
                                        <span style="color: #64748b; font-size: 0.8rem;">
                                            Document: <code>{ev.document_id}</code> ({ev.document_version}) &bull; Physical Page: <strong>{ev.page}</strong>
                                        </span>
                                    </div>
                                    """,
                                    unsafe_allow_html=True,
                                )
                            with c_col2:
                                if st.button(
                                    f"🔗 View Page {ev.page}",
                                    key=f"cite_btn_{finding.finding_id}_{idx}",
                                    help="Jump to exact physical page in Evidence Viewer",
                                    use_container_width=True,
                                ):
                                    st.session_state.inspect_doc_id = ev.document_id
                                    st.session_state.inspect_version = ev.document_version
                                    st.session_state.inspect_page = ev.page
                                    st.session_state.inspect_quote = ev.quote
                                    st.info(f"Navigate to 'Documents & Evidence Viewer' tab to view Page {ev.page}.")

                    if finding.missing_facts:
                        st.markdown(f"**Missing Facts:** {', '.join(finding.missing_facts)}")
                    if finding.limitations:
                        st.markdown(f"**Limitations:** {', '.join(finding.limitations)}")
                    st.markdown(f"**Next Action:** {finding.next_action}")

            # Missing-Evidence Checklist
            if persisted_packet.missing_evidence_checklist:
                st.markdown("### Missing-Evidence Checklist")
                for item in persisted_packet.missing_evidence_checklist:
                    st.markdown(
                        f"""
                        <div class="fact-card">
                            <strong>Requested:</strong> {item.requested_information}<br>
                            <span style="font-size: 0.9rem; color: #475569;"><strong>Why it matters:</strong> {item.why_it_matters}</span><br>
                            <span style="font-size: 0.85rem; color: #64748b;"><strong>Suggested Source:</strong> {item.suggested_source or 'Insurer / TPA'}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            if persisted_packet.unresolved_questions:
                st.markdown("### Unresolved Questions for Hospital Desk / Insurer")
                for q in persisted_packet.unresolved_questions:
                    st.markdown(f"- ❓ {q}")

        else:
            # No review packet run yet for this case: offer scenario preview or trigger action
            st.info(
                "ℹ️ No review has been executed yet for this case. Click **🔍 Review Documents** "
                "above to analyze case facts and uploaded documents."
            )

            st.markdown("---")
            st.markdown("#### Preview Development Fixture Scenarios (Owner B Mock Data):")
            scenario_choice = st.selectbox(
                "Select Fixture Scenario to Preview:",
                ["supported_finding", "incomplete_review", "conflict_review", "revised_finding"],
                index=0,
            )
            sample_packet = _load_sample_packet_fixture(scenario=scenario_choice)
            if sample_packet:
                st.markdown(
                    """
                    <div class="fixture-tag">
                        ⚠️ <strong>DEVELOPMENT FIXTURE — Simulated Review Packet (Owner B Dependency)</strong><br>
                        This is mock fixture output used to test layout and contracts. It does not represent live review execution.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                for finding in sample_packet.findings:
                    with st.expander(f"{finding.topic} — {finding.status.upper()}", expanded=True):
                        st.markdown(f"**Conclusion:** {finding.conclusion}")
                        if finding.evidence:
                            st.markdown(f"**Cited Evidence:** *\"{finding.evidence[0].quote}\"* (Page {finding.evidence[0].page})")
                        st.markdown(f"**Next Action:** {finding.next_action}")

    # 3. Documents & Evidence Viewer
    with tab_docs:
        st.subheader("Document Ingestion & Immutable Version History")

        # Upload Container
        with st.expander("📤 Upload New PDF Document", expanded=True):
            up_col1, up_col2 = st.columns([3, 2])
            with up_col1:
                uploaded_file = st.file_uploader(
                    "Choose PDF file",
                    type=["pdf"],
                    help="Upload a policy wording, renewal schedule, endorsement, or hospital estimate (Max 10MB, Max 50 pages).",
                )
            with up_col2:
                doc_evidence_type = st.selectbox(
                    "Evidence Type:",
                    [
                        "policy_wording",
                        "policy_schedule",
                        "endorsement",
                        "hospital_estimate",
                        "admission_document",
                        "insurer_correspondence",
                        "other",
                    ],
                )

            if uploaded_file is not None:
                if st.button("Upload & Extract Document ➔", type="primary"):
                    try:
                        content = uploaded_file.getvalue()
                        record, is_duplicate = storage.save_document(
                            case_id=case.case_id,
                            filename=uploaded_file.name,
                            content=content,
                            evidence_type=doc_evidence_type,
                        )
                        if is_duplicate:
                            st.info(
                                f"ℹ️ **Duplicate Detected**: Identical file was already uploaded as "
                                f"version `{record.version}` of `{record.document_id}` (SHA-256: `{record.sha256[:12]}...`). No redundant version created."
                            )
                        else:
                            st.success(
                                f"✅ Successfully uploaded `{record.filename}` as **{record.version}**! "
                                f"Status: `{record.extraction_status.upper()}` ({record.total_pages} physical pages extracted)."
                            )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

            st.markdown("---")
            st.markdown("**Or Quick-Load Synthetic Fixtures for Testing:**")
            syn_c1, syn_c2, syn_c3, syn_c4, syn_c5 = st.columns(5)
            with syn_c1:
                if st.button("📄 Base Policy", use_container_width=True, help="15 pages: contains waiting period clause on p14 and blank p7"):
                    rec, dup = storage.save_document(
                        case.case_id, "Care_Health_Gold_Policy_Wording.pdf", build_synthetic_policy_pdf(), "policy_wording"
                    )
                    st.toast(f"Policy wording loaded as {rec.version}")
                    st.rerun()
            with syn_c2:
                if st.button("📋 Renewal Schedule", use_container_width=True, help="2 pages: 18 months continuous coverage"):
                    rec, dup = storage.save_document(
                        case.case_id, "Policy_Renewal_Schedule.pdf", build_synthetic_schedule_pdf(), "policy_schedule"
                    )
                    st.toast(f"Schedule loaded as {rec.version}")
                    st.rerun()
            with syn_c3:
                if st.button("📝 Endorsement", use_container_width=True, help="1 page: reduces waiting period to 12 months"):
                    rec, dup = storage.save_document(
                        case.case_id, "Joint_Replacement_Endorsement.pdf", build_synthetic_endorsement_pdf(), "endorsement"
                    )
                    st.toast(f"Endorsement loaded as {rec.version}")
                    st.rerun()
            with syn_c4:
                if st.button("🏥 Hospital Estimate", use_container_width=True, help="2 pages: knee replacement estimate"):
                    rec, dup = storage.save_document(
                        case.case_id, "Apex_Hospital_Estimate.pdf", build_synthetic_hospital_estimate_pdf(), "hospital_estimate"
                    )
                    st.toast(f"Estimate loaded as {rec.version}")
                    st.rerun()
            with syn_c5:
                if st.button("⚠️ Unreadable PDF", use_container_width=True, help="Tests explicit unreadable status"):
                    rec, dup = storage.save_document(
                        case.case_id, "Scanned_Receipt_Unreadable.pdf", build_synthetic_unreadable_pdf(), "other"
                    )
                    st.toast(f"Unreadable PDF loaded as {rec.version}")
                    st.rerun()

        # Documents List
        docs = storage.list_documents(case.case_id)
        if not docs:
            st.info("No documents uploaded yet for this case. Upload a PDF or load a synthetic fixture above.")
        else:
            st.markdown("### Uploaded Documents & Extraction Status")
            for doc in docs:
                status_badge_color = {
                    "extracted": "#16a34a",
                    "partial": "#ea580c",
                    "unreadable": "#eab308",
                    "error": "#dc2626",
                    "pending": "#64748b",
                }.get(doc.extraction_status, "#64748b")

                with st.container():
                    d1, d2, d3, d4 = st.columns([3, 2, 2, 3])
                    with d1:
                        st.markdown(f"📄 **{doc.filename}**")
                        st.caption(f"ID: `{doc.document_id}` • Version: **`{doc.version}`**")
                    with d2:
                        st.markdown(f"Type: `{doc.evidence_type}`")
                        st.markdown(f"Pages: **{doc.total_pages}**")
                    with d3:
                        st.markdown(
                            f"<span style='background-color: {status_badge_color}; color: white; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; text-transform: uppercase;'>{doc.extraction_status}</span>",
                            unsafe_allow_html=True,
                        )
                        if doc.error_message:
                            st.caption(f"Note: {doc.error_message}")
                    with d4:
                        st.caption(f"SHA-256: `{doc.sha256[:16]}...`")
                        st.caption(f"Uploaded: {doc.uploaded_at[:19]}")
                    st.markdown("<hr style='margin: 0.35rem 0;'>", unsafe_allow_html=True)

            # Interactive Evidence Viewer
            st.markdown("---")
            st.subheader("🔍 Physical Page Evidence Viewer")

            doc_options = {f"{d.filename} ({d.version})": (d.document_id, d.version) for d in docs}
            doc_labels = list(doc_options.keys())

            # Support jump from citation link in findings
            default_doc_idx = 0
            inspect_doc = st.session_state.get("inspect_doc_id")
            inspect_ver = st.session_state.get("inspect_version")
            if inspect_doc and inspect_ver:
                for idx, (lbl, (d_id, d_v)) in enumerate(doc_options.items()):
                    if d_id == inspect_doc and d_v == inspect_ver:
                        default_doc_idx = idx
                        break

            selected_label = st.selectbox(
                "Select Document & Version to Inspect:",
                doc_labels,
                index=default_doc_idx,
            )

            if selected_label:
                sel_doc_id, sel_ver = doc_options[selected_label]
                full_doc = storage.get_document(sel_doc_id, sel_ver)

                if full_doc and full_doc.pages:
                    total_p = full_doc.total_pages

                    default_page = 14 if total_p >= 14 else 1
                    if "inspect_page" in st.session_state and st.session_state.inspect_page <= total_p:
                        default_page = st.session_state.inspect_page

                    sel_page_num = st.number_input(
                        f"Select Physical Page Number (1 to {total_p}):",
                        min_value=1,
                        max_value=total_p,
                        value=default_page,
                        step=1,
                    )

                    page_obj = next((p for p in full_doc.pages if p.page_number == sel_page_num), None)

                    if page_obj:
                        if page_obj.is_blank:
                            st.warning(
                                f"⚠️ **Physical Page {page_obj.page_number} is Blank** (no extractable text).\n\n"
                                f"_Physical page positions are strictly preserved so citations do not drift._"
                            )
                        else:
                            st.markdown(
                                f"**Extracted Text from Physical Page {page_obj.page_number}** "
                                f"({page_obj.character_count} characters):"
                            )

                            quote_to_highlight = st.session_state.get("inspect_quote")
                            rendered_text = page_obj.text
                            if quote_to_highlight and quote_to_highlight.lower() in page_obj.text.lower():
                                # Highlight quote in yellow
                                start_idx = page_obj.text.lower().find(quote_to_highlight.lower())
                                end_idx = start_idx + len(quote_to_highlight)
                                exact_match = page_obj.text[start_idx:end_idx]
                                rendered_text = (
                                    page_obj.text[:start_idx]
                                    + f"<mark style='background-color: #fef08a; padding: 0.1rem 0.3rem;'>{exact_match}</mark>"
                                    + page_obj.text[end_idx:]
                                )

                            st.markdown(
                                f"""
                                <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 1rem; font-family: monospace; font-size: 0.9rem; line-height: 1.5; color: #1e293b;">
                                    {rendered_text}
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                            # Citation Verifier Tool
                            with st.expander("🔬 Test Citation on this Page"):
                                default_test_q = (
                                    st.session_state.get("inspect_quote")
                                    or ("twenty-four (24) continuous months" if page_obj.page_number == 14 else "")
                                )
                                test_quote = st.text_area(
                                    "Enter quote to verify against this physical page:",
                                    value=default_test_q,
                                )
                                if st.button("Verify Citation ➔"):
                                    test_ev = Evidence(
                                        document_id=sel_doc_id,
                                        document_version=sel_ver,
                                        page=page_obj.page_number,
                                        quote=test_quote,
                                        evidence_type=full_doc.evidence_type,
                                    )
                                    is_v, msg = ev_retrieval.verify_citation(test_ev)
                                    if is_v:
                                        st.success(f"✅ {msg}")
                                    else:
                                        st.error(f"❌ {msg}")

    with tab_replay:
        st.info(
            "ℹ️ **Evidence Change Replay (Milestone M5)**: Traceable before-and-after audit diffs "
            "showing how endorsements or new facts revise findings will be integrated in M5."
        )

    with tab_export:
        st.info(
            "ℹ️ **Packet Export (Milestone M6)**: Deterministic, self-contained HTML export rendering "
            "the exact saved review snapshot will be integrated in M6."
        )


def persisted_reason_label(reason: str) -> str:
    labels = {
        "review_complete": "Review Complete",
        "missing_information": "Missing Information",
        "conflicting_evidence": "Conflicting Evidence",
        "needs_human_review": "Needs Human Review",
        "tool_limit_reached": "Tool Limit Reached (Max 8)",
        "timeout": "Timeout",
        "processing_error": "Processing Error",
    }
    return labels.get(reason, reason)
