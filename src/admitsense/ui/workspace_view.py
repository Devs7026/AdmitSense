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
from admitsense.schemas import CaseDetails, Evidence, ReviewPacket
from admitsense.storage.case_repository import CaseRepository
from admitsense.ui.components import render_authorization_badge


def _load_sample_packet_fixture(scenario: str = "supported_finding") -> ReviewPacket | None:
    # First attempt to load from Owner B's test fixtures module
    try:
        from tests.fixtures import get_sample_packet
        return get_sample_packet(scenario)
    except Exception:
        pass

    # Fallback to tests/fixtures/sample_packet.json
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

    # Top Navigation Row
    top_c1, top_c2, top_c3 = st.columns([2, 5, 2])
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

    st.markdown("---")

    # Authorisation Status Banner (Non-negotiable invariant: defaults to unverified)
    render_authorization_badge(status="not verified")

    # Next Action Banner
    sample_packet = _load_sample_packet_fixture()
    next_action_text = (
        sample_packet.findings[0].next_action
        if (sample_packet and sample_packet.findings)
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

    # Main Workspace Tabs
    tab_facts, tab_review, tab_docs, tab_replay, tab_export = st.tabs(
        [
            "📋 Case Facts & Provenance",
            "🔍 Findings & Review",
            "📄 Documents & Evidence Viewer",
            "🔄 Change Replay (M5)",
            "📥 Packet Export (M6)",
        ]
    )

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

    with tab_review:
        f_col1, f_col2 = st.columns([2, 1])
        with f_col1:
            st.subheader("Review Findings (Development Fixture)")
        with f_col2:
            scenario_choice = st.selectbox(
                "Sample Fixture Scenario:",
                ["supported_finding", "incomplete_review", "conflict_review", "revised_finding"],
                index=0,
            )

        active_packet = _load_sample_packet_fixture(scenario=scenario_choice)
        if active_packet:
            st.markdown(
                """
                <div class="fixture-tag">
                    ⚠️ <strong>DEVELOPMENT FIXTURE — Sample Review Packet (Owner B Dependency)</strong><br>
                    This is a development mock fixture demonstrating the workspace review UI layout.
                    It does not represent real review execution.
                </div>
                """,
                unsafe_allow_html=True,
            )

            r1, r2, r3 = st.columns(3)
            with r1:
                st.metric("Packet ID", active_packet.packet_id)
            with r2:
                st.metric("Review Status", active_packet.review_status.upper())
            with r3:
                st.metric("Tool Steps Used", f"{active_packet.tool_steps_used} / 8")

            st.markdown("### Findings")
            for finding in active_packet.findings:
                status_color = "#ea580c" if finding.status == "unresolved" else "#16a34a"
                with st.expander(f"{finding.topic} — {finding.status.upper()}", expanded=True):
                    st.markdown(f"**Conclusion:** {finding.conclusion}")
                    if finding.evidence:
                        st.markdown("**Cited Evidence:**")
                        for ev in finding.evidence:
                            st.markdown(
                                f"""
                                <div style="background-color: #f8fafc; border-left: 3px solid #64748b; padding: 0.5rem 0.75rem; margin-bottom: 0.5rem; font-size: 0.88rem;">
                                    <em>"{ev.quote}"</em><br>
                                    <span style="color: #64748b; font-size: 0.8rem;">
                                        Document: <code>{ev.document_id}</code> ({ev.document_version}) &bull; Physical Page: <strong>{ev.page}</strong>
                                    </span>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                    if finding.limitations:
                        st.markdown(f"**Limitations:** {', '.join(finding.limitations)}")
                    st.markdown(f"**Next Action:** {finding.next_action}")

            if active_packet.missing_evidence_checklist:
                st.markdown("### Missing-Evidence Checklist")
                for item in active_packet.missing_evidence_checklist:
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
        else:
            st.info(
                "ℹ️ **Review Engine Pending**: Owner B's review engine, retrieval tools, and findings "
                "generation will be integrated in Milestone M3."
            )

    with tab_docs:
        st.subheader("Document Ingestion & Immutable Version History")

        # 1. Document Upload Section
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

        # 2. Documents List
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

            # 3. Interactive Evidence Viewer
            st.markdown("---")
            st.subheader("🔍 Physical Page Evidence Viewer")

            doc_options = {f"{d.filename} ({d.version})": (d.document_id, d.version) for d in docs}
            selected_label = st.selectbox("Select Document & Version to Inspect:", list(doc_options.keys()))

            if selected_label:
                sel_doc_id, sel_ver = doc_options[selected_label]
                full_doc = storage.get_document(sel_doc_id, sel_ver)

                if full_doc and full_doc.pages:
                    total_p = full_doc.total_pages
                    sel_page_num = st.number_input(
                        f"Select Physical Page Number (1 to {total_p}):",
                        min_value=1,
                        max_value=total_p,
                        value=14 if total_p >= 14 else 1,
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
                            st.markdown(
                                f"""
                                <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 1rem; font-family: monospace; font-size: 0.9rem; line-height: 1.5; color: #1e293b;">
                                    {page_obj.text}
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                            # Citation Verifier Tool
                            with st.expander("🔬 Test Citation on this Page"):
                                test_quote = st.text_area(
                                    "Enter quote to verify against this physical page:",
                                    value="twenty-four (24) continuous months" if page_obj.page_number == 14 else "",
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
