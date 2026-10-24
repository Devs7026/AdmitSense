from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from admitsense.schemas import CaseDetails, ReviewPacket
from admitsense.storage.case_repository import CaseRepository
from admitsense.ui.components import render_authorization_badge


def _load_sample_packet_fixture() -> ReviewPacket | None:
    fixture_path = Path("tests") / "fixtures" / "sample_packet.json"
    if fixture_path.exists():
        try:
            with open(fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ReviewPacket.model_validate(data)
        except Exception:
            return None
    return None


def render_workspace_view(repo: CaseRepository) -> None:
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
            "📄 Documents (M2)",
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
        if sample_packet:
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
                st.metric("Packet ID", sample_packet.packet_id)
            with r2:
                st.metric("Review Status", sample_packet.review_status.upper())
            with r3:
                st.metric("Tool Steps Used", f"{sample_packet.tool_steps_used} / 8")

            st.markdown("### Findings")
            for finding in sample_packet.findings:
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

            if sample_packet.missing_evidence_checklist:
                st.markdown("### Missing-Evidence Checklist")
                for item in sample_packet.missing_evidence_checklist:
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
        st.info(
            "ℹ️ **Document Ingestion (Milestone M2)**: PDF upload limits, SHA-256 versioning, "
            "and pypdf page extraction retaining 1-based page numbers will be integrated in M2."
        )

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
