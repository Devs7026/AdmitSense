from __future__ import annotations

import json
from pathlib import Path

from datetime import date
from decimal import Decimal

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
from admitsense.documents.hospital_directory import (
    HospitalLookupResult,
    LocalSyntheticHospitalDirectory,
)
from admitsense.export import generate_review_packet_html
from admitsense.review.service import ReviewService
from admitsense.schemas import CaseDetails, Evidence, FactSource, HospitalRecordReference, ReviewPacket
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

    # Fetch latest persisted ReviewPacket from SQLite for this case
    persisted_packet = r_repo.get_latest_review_packet(case.case_id)
    documents = storage.list_documents(case.case_id)

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
        action_label = "🔄 Resume Review (New Run)" if persisted_packet else "🔍 Review Available Documents"
        action_help = (
            "Trigger an explicit new review run linked to this case, retaining previous run history"
            if persisted_packet
            else "Trigger automated policy review on ingested documents and case facts"
        )
        if st.button(
            action_label,
            type="primary",
            use_container_width=True,
            help=action_help,
            key="btn_trigger_review_top",
        ):
            with st.status("Analyzing case facts and policy documents...", expanded=True) as status_box:
                def on_tool_activity(evt):
                    step = getattr(evt, "step_number", "?")
                    tool_name = getattr(evt, "tool_name", "tool")
                    summary = getattr(evt, "summary", str(evt))
                    status = getattr(evt, "status", "invoked")
                    status_box.write(f"Step {step}/8: `{tool_name}` — {summary} ({status})")

                try:
                    packet = r_service.execute_review(case.case_id, event_callback=on_tool_activity)
                    status_box.update(
                        label=f"Review Finished: {packet.review_status.upper()}",
                        state="complete",
                    )
                    st.toast(f"Review completed: {packet.review_status.upper()}", icon="✅")
                    st.rerun()
                except Exception as e:
                    status_box.update(label="Review encountered an issue", state="error")
                    st.error(f"Review execution failed: {e}")

    st.markdown("---")

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
            <h4>Recommended Next Action</h4>
            <p>{next_action_text}</p>
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
                            "<span class='provenance-tag' style='background: rgba(148, 163, 184, 0.15); color: #94a3b8;'>no source</span>",
                            unsafe_allow_html=True,
                        )
                st.markdown("<hr style='margin: 0.35rem 0;'>", unsafe_allow_html=True)

        # Hospital Directory Reference (Synthetic Demonstration)
        st.markdown("### 🏥 Hospital Directory Reference (Demonstration Data)")
        hosp_dir = LocalSyntheticHospitalDirectory()
        hosp_res = hosp_dir.lookup_hospital(case.hospital_name)
        if hosp_res.status == "matched" and hosp_res.record:
            rec = hosp_res.record
            st.markdown(
                f"""
                <div class="hospital-box">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                        <div>
                            <span style="background-color: rgba(168, 85, 247, 0.2); color: #7e22ce; border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 4px; padding: 2px 6px; font-size: 0.72rem; font-weight: 700;">SYNTHETIC DEMONSTRATION DATA</span>
                            <h4>{rec.hospital_name}</h4>
                            <span style="font-size: 0.88rem;">
                                City: <strong>{rec.city}</strong> &bull; Record ID: <code>{rec.record_id}</code> &bull; Dataset Version: <strong>{rec.dataset_version}</strong> ({rec.dataset_date.strftime('%d %b %Y')})
                            </span>
                        </div>
                        <div style="text-align: right;">
                            <span style="background-color: rgba(14, 165, 233, 0.2); color: #0284c7; border: 1px solid rgba(14, 165, 233, 0.4); border-radius: 4px; padding: 2px 8px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;">{rec.network_tier.replace('_', ' ')}</span>
                            <div style="font-size: 0.82rem; margin-top: 0.35rem;">
                                TPA Desk: <strong>{rec.tpa_desk_contact or 'Not listed'}</strong>
                            </div>
                        </div>
                    </div>
                    <div style="margin-top: 0.65rem; font-size: 0.82rem; color: #7c3aed; background-color: rgba(139, 92, 246, 0.12); padding: 0.5rem 0.85rem; border-radius: 4px; line-height: 1.45;">
                        ⚠️ <strong>Invariant & Limitations:</strong> Synthetic hospital directory match does NOT verify live insurer network status, cashless eligibility, or claim approval. Cashless agreements must be verified directly with the hospital admission desk and insurance TPA.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif hosp_res.status == "no_match":
            st.warning(
                f"⚠️ **No Directory Match**: '{hosp_res.query}' was not found in the synthetic hospital dataset ({hosp_res.dataset_version}). "
                "Confirm facility network credentials directly with the hospital admission desk."
            )
        elif hosp_res.status == "ambiguous_match":
            candidate_list = ", ".join(f"'{c.hospital_name}'" for c in hosp_res.candidates)
            st.warning(
                f"⚠️ **Ambiguous Match**: Multiple facilities match '{hosp_res.query}': {candidate_list}. "
                "Specify the exact facility name in Case Setup."
            )
        else:
            st.info(
                "ℹ️ **Hospital Not Specified**: No hospital name was provided in case details. "
                "Specify a hospital facility in Case Setup to view synthetic directory reference."
            )

    # 2. Findings & Review
    with tab_review:
        if persisted_packet:
            # 1. Packet Run Status & Safety Gauge
            status_color = "#16a34a" if persisted_packet.review_status == "complete" else "#ea580c"
            st.markdown(
                f"""
                <div class="packet-banner">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; font-size: 1.1rem;">
                            Persisted Review Packet: <code>{persisted_packet.packet_id}</code> (v{persisted_packet.packet_version})
                        </span>
                        <span style="background-color: {status_color}; color: white !important; padding: 0.25rem 0.65rem; border-radius: 4px; font-weight: 700; font-size: 0.85rem; text-transform: uppercase;">
                            {persisted_packet.review_status}
                        </span>
                    </div>
                    <div style="display: flex; gap: 1.5rem; margin-top: 0.5rem; font-size: 0.88rem;">
                        <span>Run ID: <code>{persisted_packet.run_id}</code></span>
                        <span>Tool Steps Used: <strong>{persisted_packet.tool_steps_used} / 8</strong></span>
                        <span>Stop Reason: <strong>{persisted_reason_label(persisted_packet.stopped_reason)}</strong></span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Honest Stop Reason Reporting
            if persisted_packet.stopped_reason == "tool_limit_reached":
                st.warning(
                    f"⚠️ **Tool Limit Reached ({persisted_packet.tool_steps_used}/8 calls)**: "
                    "The agent halted after exhausting its execution budget. Showing validated partial findings below."
                )
            elif persisted_packet.stopped_reason == "missing_information":
                st.info(
                    "ℹ️ **Missing Information**: Required document evidence or case facts are missing. "
                    "You can answer follow-up questions below or upload missing documents."
                )
            elif persisted_packet.stopped_reason == "processing_error":
                st.error(f"❌ **Processing Error**: {persisted_packet.stop_details}")
            elif persisted_packet.stop_details:
                st.caption(f"ℹ️ {persisted_packet.stop_details}")

            # 2. Activity Event Stream Display (Concise real tool calls from SQLite)
            activity_events = r_repo.list_activity_events(run_id=persisted_packet.run_id)
            if not activity_events:
                activity_events = r_repo.list_activity_events(case_id=case.case_id)

            with st.expander(f"⚡ Agent Tool Activity Log ({len(activity_events)} actual steps)", expanded=False):
                if activity_events:
                    for evt in activity_events:
                        st_badge = {
                            "completed": ("#16a34a", "COMPLETED"),
                            "failed": ("#dc2626", "FAILED"),
                            "invoked": ("#2563eb", "INVOKED"),
                        }.get(evt.get("status"), ("#64748b", evt.get("status", "").upper()))
                        tool_nm = evt.get("tool_name", "")
                        step_num = evt.get("step_number", "?")
                        summary_txt = evt.get("summary", "")
                        st.markdown(
                            f"""
                            <div class="activity-step-box">
                                <div>
                                    <span style="font-weight: 700; font-size: 0.84rem;">Step {step_num}/8</span> &nbsp;
                                    <code style="font-size: 0.85rem;">{tool_nm}</code> &nbsp;
                                    <span style="font-size: 0.88rem;">{summary_txt}</span>
                                </div>
                                <span style="background-color: {st_badge[0]}; color: white !important; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">
                                    {st_badge[1]}
                                </span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if evt.get("error"):
                            st.caption(f"⚠️ Error: {evt['error']}")
                else:
                    st.caption("No real tool events recorded yet for this run.")

            # 3. Findings
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
                                    <div class="evidence-quote-box">
                                        <em>"{ev.quote}"</em>
                                        <span>
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

            # 4. Missing-Evidence Checklist with "I Don't Have This"
            if persisted_packet.missing_evidence_checklist:
                st.markdown("### Missing-Evidence Checklist")
                for chk_idx, item in enumerate(persisted_packet.missing_evidence_checklist):
                    with st.container():
                        st.markdown(
                            f"""
                            <div class="fact-card" style="margin-bottom: 0.5rem;">
                                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                    <div>
                                        <strong>Requested:</strong> <span style="font-weight: 600;">{item.requested_information}</span><br>
                                        <span style="font-size: 0.9rem;"><strong>Why it matters:</strong> {item.why_it_matters}</span><br>
                                        <span style="font-size: 0.85rem;"><strong>Suggested Source:</strong> {item.suggested_source or 'Insurer / TPA'}</span>
                                    </div>
                                    <span style="font-size: 0.8rem; font-weight: 700; padding: 0.25rem 0.55rem; border-radius: 4px; background: {'rgba(34, 197, 94, 0.2); color: #15803d' if item.status == 'provided_pending_review' else 'rgba(245, 158, 11, 0.2); color: #b45309' if item.status == 'requested' else 'rgba(100, 116, 139, 0.2); color: #475569'};">
                                        {item.status.upper().replace('_', ' ')}
                                    </span>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if item.status == "requested":
                            btn_c1, btn_c2 = st.columns([1, 1])
                            with btn_c1:
                                if st.button(
                                    "⚠️ I Don't Have This",
                                    key=f"btn_dont_have_{item.item_id}_{chk_idx}",
                                    help="Declare that you do not have this evidence; topic will remain unresolved without proof",
                                    use_container_width=True,
                                ):
                                    r_repo.update_checklist_item_status(
                                        case_id=case.case_id,
                                        item_id=item.item_id,
                                        status="user_does_not_have",
                                        resolution_note="Caregiver declared evidence unavailable.",
                                    )
                                    st.toast("Item marked as unavailable. Finding will remain unresolved.")
                                    st.rerun()
                            with btn_c2:
                                st.caption("👉 You can upload documents in the Documents tab or answer below.")

                        elif item.status == "user_does_not_have":
                            st.warning(
                                "⚠️ **Caregiver declared this evidence unavailable.** "
                                "Under insurance rules, the relevant policy condition/waiting period remains unresolved without documentation."
                            )
                            if st.button("Undo / Provide Now", key=f"btn_undo_dont_have_{item.item_id}_{chk_idx}"):
                                r_repo.update_checklist_item_status(
                                    case_id=case.case_id,
                                    item_id=item.item_id,
                                    status="requested",
                                    resolution_note=None,
                                )
                                st.rerun()

                        elif item.status == "provided_pending_review":
                            st.info(f"📋 **Provided (Pending Re-review)**: {item.resolution_note or 'Answer recorded.'}")

                        st.markdown("<hr style='margin: 0.4rem 0;'>", unsafe_allow_html=True)

            # 5. Follow-Up Answering Form (User Answers & Missing Facts Provenance)
            st.markdown("### User Follow-Up & Missing Facts")
            with st.expander("✍️ Answer Questions & Provide Missing Case Facts", expanded=True):
                st.caption(
                    "All facts provided here are explicitly recorded with `FactSource(source_type='user_provided')` "
                    "provenance and saved to SQLite."
                )

                # Show fields that are currently None or can be updated
                up_form = st.form(key=f"user_followup_form_{persisted_packet.packet_id}")

                col_f1, col_f2 = up_form.columns(2)
                with col_f1:
                    new_cont_date = up_form.date_input(
                        "Continuous Coverage Start Date",
                        value=case.continuous_coverage_start_date or None,
                        help="Date when insurance first started (including prior ported policies)",
                    )
                    new_policy_date = up_form.date_input(
                        "Current Policy Inception / Start Date",
                        value=case.policy_start_date or None,
                        help="Start date of current policy year",
                    )
                    new_policy_age = up_form.number_input(
                        "Policy Age in Months",
                        min_value=0,
                        max_value=360,
                        value=int(case.policy_age_months) if case.policy_age_months is not None else 0,
                        help="Continuous months covered",
                    )

                with col_f2:
                    new_proc = up_form.text_input(
                        "Procedure Name",
                        value=case.procedure or "",
                        help="Planned surgical procedure (e.g. Total Knee Replacement)",
                    )
                    new_cost = up_form.number_input(
                        "Estimated Hospital Cost (INR)",
                        min_value=0.0,
                        value=float(case.estimated_cost) if case.estimated_cost is not None else 0.0,
                        step=1000.0,
                    )
                    new_hosp = up_form.text_input(
                        "Hospital Name",
                        value=case.hospital_name or "",
                    )

                # Unresolved Questions
                free_answers: dict[str, str] = {}
                if persisted_packet.unresolved_questions:
                    up_form.markdown("**Answer Clarification Questions:**")
                    for q_idx, question in enumerate(persisted_packet.unresolved_questions):
                        free_answers[question] = up_form.text_area(
                            f"Question: {question}",
                            key=f"q_ans_{q_idx}",
                            placeholder="Enter clarification or details here...",
                        )

                submitted = up_form.form_submit_button("Save Answers & Update Case Facts ➔", type="primary")
                if submitted:
                    updated_case = case.model_copy()
                    fact_sources = dict(updated_case.fact_sources)

                    if new_cont_date:
                        updated_case.continuous_coverage_start_date = new_cont_date
                        fact_sources["continuous_coverage_start_date"] = FactSource(source_type="user_provided")
                    if new_policy_date:
                        updated_case.policy_start_date = new_policy_date
                        fact_sources["policy_start_date"] = FactSource(source_type="user_provided")
                    if new_policy_age > 0:
                        updated_case.policy_age_months = int(new_policy_age)
                        fact_sources["policy_age_months"] = FactSource(source_type="user_provided")
                    if new_proc.strip():
                        updated_case.procedure = new_proc.strip()
                        fact_sources["procedure"] = FactSource(source_type="user_provided")
                    if new_cost > 0.0:
                        updated_case.estimated_cost = Decimal(str(new_cost))
                        fact_sources["estimated_cost"] = FactSource(source_type="user_provided")
                    if new_hosp.strip():
                        updated_case.hospital_name = new_hosp.strip()
                        fact_sources["hospital_name"] = FactSource(source_type="user_provided")

                    updated_case.fact_sources = fact_sources
                    repo.update_case(updated_case)

                    # Update checklist items to provided_pending_review
                    if persisted_packet.missing_evidence_checklist:
                        for chk in persisted_packet.missing_evidence_checklist:
                            if chk.status == "requested":
                                r_repo.update_checklist_item_status(
                                    case_id=case.case_id,
                                    item_id=chk.item_id,
                                    status="provided_pending_review",
                                    resolution_note="User supplied follow-up case facts.",
                                )

                    st.toast("✅ Follow-up information saved with user provenance!", icon="✅")
                    st.rerun()

            # 6. Explicit Resume Review Action
            st.markdown("---")
            res_c1, res_c2 = st.columns([3, 2])
            with res_c1:
                st.markdown(
                    "**Ready to evaluate updated information?**<br>"
                    "<span style='color: #64748b; font-size: 0.85rem;'>"
                    "Resuming creates an explicit new run record linked to this case, preserving all prior runs."
                    "</span>",
                    unsafe_allow_html=True,
                )
            with res_c2:
                if st.button("🔄 Resume Review (New Run)", type="primary", use_container_width=True, key="btn_resume_review_tab"):
                    with st.status("Resuming review with updated case facts...", expanded=True) as res_status:
                        def on_resume_tool_evt(evt):
                            step = getattr(evt, "step_number", "?")
                            tool_name = getattr(evt, "tool_name", "tool")
                            summary = getattr(evt, "summary", str(evt))
                            res_status.write(f"Step {step}/8: `{tool_name}` — {summary}")

                        try:
                            new_packet = r_service.execute_review(case.case_id, event_callback=on_resume_tool_evt)
                            res_status.update(label=f"Review Finished: {new_packet.review_status.upper()}", state="complete")
                            st.toast(f"New review run completed: {new_packet.review_status.upper()}", icon="✅")
                            st.rerun()
                        except Exception as e:
                            res_status.update(label="Resume failed", state="error")
                            st.error(f"Review execution failed: {e}")

            # 7. Historical Review Runs
            historical_packets = r_repo.list_review_packets(case.case_id)
            if len(historical_packets) > 1:
                with st.expander(f"📜 Review Run History ({len(historical_packets)} runs recorded)", expanded=False):
                    for pkt in historical_packets:
                        is_current = pkt.packet_id == persisted_packet.packet_id
                        st.markdown(
                            f"""
                            <div class="packet-banner" style="margin-bottom: 0.4rem; padding: 0.55rem 0.85rem; display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <strong>v{pkt.packet_version}</strong> &bull; <code>{pkt.packet_id}</code> &bull; Run: <code>{pkt.run_id}</code><br>
                                    <span style="font-size: 0.82rem;">Tool Steps: <strong>{pkt.tool_steps_used}/8</strong> &bull; Stop Reason: <strong>{persisted_reason_label(pkt.stopped_reason)}</strong></span>
                                </div>
                                <div style="text-align: right;">
                                    <span style="font-weight: 700; font-size: 0.8rem; color: {'#16a34a' if pkt.review_status == 'complete' else '#ea580c'};">{pkt.review_status.upper()}</span><br>
                                    <span style="font-size: 0.75rem;">{pkt.generated_at.strftime('%H:%M:%S') if getattr(pkt, 'generated_at', None) else ''}</span>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

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
                                    + f"<mark style='background-color: #fef08a; color: #1e293b; font-weight: 600; padding: 0.1rem 0.3rem; border-radius: 3px;'>{exact_match}</mark>"
                                    + page_obj.text[end_idx:]
                                )

                            st.markdown(
                                f"""
                                <div class="extracted-text-viewer">
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
        st.subheader("🔄 Evidence Change Replay")
        st.caption(
            "Traceable before-and-after diffs showing how newly uploaded policy endorsements, "
            "revised schedules, or updated case facts modified administrative preparation findings."
        )

        replay_packet = persisted_packet
        is_fixture_mode = False

        if not replay_packet:
            # Check if user wants to preview development fixture
            st.info(
                "ℹ️ No review has been executed for this case yet. "
                "You can preview a simulated Evidence Change Replay fixture below (Owner B Mock Data)."
            )
            sample_revised = _load_sample_packet_fixture(scenario="revised_finding")
            if sample_revised:
                st.markdown(
                    """
                    <div class="fixture-tag" style="margin-bottom: 1rem;">
                        ⚠️ <strong>DEVELOPMENT FIXTURE — Simulated Evidence Change Replay</strong><br>
                        Demonstrating how an uploaded endorsement amends waiting period terms from 24 to 12 months.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                replay_packet = sample_revised
                is_fixture_mode = True

        if replay_packet:
            # If multiple historical packets exist, provide version selector
            hist_packets = r_repo.list_review_packets(case.case_id) if not is_fixture_mode else [replay_packet]
            selected_pkt = replay_packet

            if len(hist_packets) > 1:
                ver_options = [f"v{p.packet_version} (Run: {p.run_id[:16]}...)" for p in hist_packets]
                sel_idx = st.selectbox(
                    "Select Review Packet Version to Inspect Replay:",
                    range(len(ver_options)),
                    format_func=lambda i: ver_options[i],
                    index=0,
                )
                selected_pkt = hist_packets[sel_idx]

            st.markdown(
                f"""
                <div class="packet-banner" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <div>
                        <strong>Packet Version:</strong> <code>v{selected_pkt.packet_version}</code> &bull;
                        <strong>Run ID:</strong> <code>{selected_pkt.run_id}</code> &bull;
                        <strong>Total Findings:</strong> <strong>{len(selected_pkt.findings)}</strong> &bull;
                        <strong>Revisions in this Packet:</strong> <strong>{len(selected_pkt.revisions)}</strong>
                    </div>
                    <div>
                        <span style="font-size: 0.82rem;">
                            Authorisation: <strong style="text-transform: uppercase;">{selected_pkt.authorization_status}</strong>
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Categorize findings: Changed, Unchanged, Newly Introduced
            revisions_by_finding: dict[str, Revision] = {
                r.finding_id: r for r in selected_pkt.revisions
            }

            changed_findings: list[tuple[Finding, Revision]] = []
            unchanged_findings: list[Finding] = []
            new_findings: list[Finding] = []

            for f in selected_pkt.findings:
                if f.finding_id in revisions_by_finding:
                    changed_findings.append((f, revisions_by_finding[f.finding_id]))
                elif f.revision > 1:
                    # Carried forward from an earlier revision, but unchanged in this run
                    unchanged_findings.append(f)
                else:
                    # Revision == 1: check if this finding existed in earlier packet
                    if selected_pkt.packet_version > 1 and len(hist_packets) > 1:
                        # Check prior packets
                        prior_pkts = [p for p in hist_packets if p.packet_version < selected_pkt.packet_version]
                        in_prior = any(any(pf.finding_id == f.finding_id for pf in p.findings) for p in prior_pkts)
                        if in_prior:
                            unchanged_findings.append(f)
                        else:
                            new_findings.append(f)
                    else:
                        new_findings.append(f)

            # 1. Changed Findings Section
            st.markdown(f"### ⚡ Changed Findings ({len(changed_findings)})")
            if not changed_findings:
                st.caption(
                    "No findings were revised in this review run. All existing findings remained unaltered by the evidence."
                )

            for idx, (f, rev) in enumerate(changed_findings):
                st_old_badge = {
                    "supported": ("#16a34a", "SUPPORTED"),
                    "unresolved": ("#ea580c", "UNRESOLVED"),
                    "conflict": ("#dc2626", "CONFLICT"),
                    "needs_human_review": ("#7c3aed", "NEEDS HUMAN REVIEW"),
                }.get(rev.old_status, ("#64748b", rev.old_status.upper()))

                st_new_badge = {
                    "supported": ("#16a34a", "SUPPORTED"),
                    "unresolved": ("#ea580c", "UNRESOLVED"),
                    "conflict": ("#dc2626", "CONFLICT"),
                    "needs_human_review": ("#7c3aed", "NEEDS HUMAN REVIEW"),
                }.get(rev.new_status, ("#64748b", rev.new_status.upper()))

                with st.expander(
                    f"🔄 {f.topic} — Revised from {st_old_badge[1]} to {st_new_badge[1]} (Rev {rev.old_finding_revision} ➔ Rev {rev.new_finding_revision})",
                    expanded=True,
                ):
                    # Why it changed banner
                    trigger_label = {
                        "new_document": "📄 New Document Upload",
                        "user_correction": "✏️ User Fact Correction",
                        "case_details_changed": "📋 Case Details Updated",
                    }.get(rev.trigger_type, rev.trigger_type.upper())

                    st.markdown(
                        f"""
                        <div class="next-action-card" style="margin-bottom: 0.75rem; padding: 0.65rem 0.95rem;">
                            <span style="font-size: 0.8rem; font-weight: 700; color: #2563eb; text-transform: uppercase;">
                                {trigger_label}
                            </span><br>
                            <span style="font-size: 0.92rem;">
                                <strong>Why it changed:</strong> {rev.reason}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Two-column before / after display
                    diff_col1, diff_col2 = st.columns(2)

                    with diff_col1:
                        st.markdown(
                            f"""
                            <div class="diff-card-old">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                                    <span style="font-weight: 700; font-size: 0.85rem;">PREVIOUS (Rev {rev.old_finding_revision})</span>
                                    <span style="background-color: {st_old_badge[0]}; color: white !important; padding: 0.12rem 0.45rem; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">
                                        {st_old_badge[1]}
                                    </span>
                                </div>
                                <p>
                                    {rev.old_conclusion}
                                </p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        # Look up previous finding snapshot if available
                        if not is_fixture_mode:
                            old_snapshot = r_repo.get_finding_snapshot(
                                case_id=case.case_id,
                                finding_id=f.finding_id,
                                revision=rev.old_finding_revision,
                            )
                            if old_snapshot and old_snapshot.evidence:
                                with st.expander(f"📜 View Previous Evidence ({len(old_snapshot.evidence)} citations)"):
                                    for p_idx, p_ev in enumerate(old_snapshot.evidence):
                                        st.caption(
                                            f"**Doc:** `{p_ev.document_id}` ({p_ev.document_version}) &bull; **Page:** {p_ev.page}\n\n"
                                            f"*\"{p_ev.quote}\"*"
                                        )
                                        if st.button(
                                            f"🔗 Open Old Page {p_ev.page}",
                                            key=f"btn_old_ev_{f.finding_id}_{p_idx}",
                                            use_container_width=True,
                                        ):
                                            st.session_state.inspect_doc_id = p_ev.document_id
                                            st.session_state.inspect_version = p_ev.document_version
                                            st.session_state.inspect_page = p_ev.page
                                            st.session_state.inspect_quote = p_ev.quote
                                            st.info(f"Navigate to 'Documents & Evidence Viewer' to view Page {p_ev.page}.")

                    with diff_col2:
                        st.markdown(
                            f"""
                            <div class="diff-card-new">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                                    <span style="font-weight: 700; font-size: 0.85rem;">UPDATED (Rev {rev.new_finding_revision})</span>
                                    <span style="background-color: {st_new_badge[0]}; color: white !important; padding: 0.12rem 0.45rem; border-radius: 4px; font-size: 0.75rem; font-weight: 700;">
                                        {st_new_badge[1]}
                                    </span>
                                </div>
                                <p>
                                    {rev.new_conclusion}
                                </p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # Triggering Evidence Card
                    if rev.triggering_evidence:
                        st.markdown("**Triggering Evidence Cited in Revision:**")
                        for t_idx, t_ev in enumerate(rev.triggering_evidence):
                            tr_col1, tr_col2 = st.columns([4, 1])
                            with tr_col1:
                                st.markdown(
                                    f"""
                                    <div class="evidence-quote-box">
                                        <em>"{t_ev.quote}"</em>
                                        <span>
                                            Document: <code>{t_ev.document_id}</code> ({t_ev.document_version}) &bull; Physical Page: <strong>{t_ev.page}</strong>
                                        </span>
                                    </div>
                                    """,
                                    unsafe_allow_html=True,
                                )
                            with tr_col2:
                                if st.button(
                                    f"🔗 View Page {t_ev.page}",
                                    key=f"btn_trig_ev_{f.finding_id}_{t_idx}",
                                    use_container_width=True,
                                    help="Jump to triggering endorsement/revision page in Evidence Viewer",
                                ):
                                    st.session_state.inspect_doc_id = t_ev.document_id
                                    st.session_state.inspect_version = t_ev.document_version
                                    st.session_state.inspect_page = t_ev.page
                                    st.session_state.inspect_quote = t_ev.quote
                                    st.info(f"Navigate to 'Documents & Evidence Viewer' to view Page {t_ev.page}.")

                    # Updated next action banner
                    st.markdown(
                        f"""
                        <div class="next-action-card" style="margin-top: 0.6rem; padding: 0.55rem 0.85rem;">
                            <strong style="font-size: 0.88rem;">Updated Next Action:</strong>
                            <span style="font-size: 0.9rem;"> {f.next_action}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # 2. Unchanged Findings Section
            st.markdown(f"### 📌 Unchanged Findings ({len(unchanged_findings)})")
            if unchanged_findings:
                for uf in unchanged_findings:
                    u_badge = {
                        "supported": ("#16a34a", "SUPPORTED"),
                        "unresolved": ("#ea580c", "UNRESOLVED"),
                        "conflict": ("#dc2626", "CONFLICT"),
                        "needs_human_review": ("#7c3aed", "NEEDS HUMAN REVIEW"),
                    }.get(uf.status, ("#64748b", uf.status.upper()))
                    with st.expander(f"{uf.topic} — {u_badge[1]} (Unchanged, Rev {uf.revision})", expanded=False):
                        st.caption("ℹ️ This finding was evaluated in a previous run and was not modified by the latest evidence.")
                        st.markdown(f"**Conclusion:** {uf.conclusion}")
                        if uf.evidence:
                            st.markdown(f"**Active Evidence:** *\"{uf.evidence[0].quote}\"* (Page {uf.evidence[0].page})")
                        st.markdown(f"**Next Action:** {uf.next_action}")
            else:
                st.caption("None.")

            # 3. Newly Introduced Findings Section
            st.markdown(f"### ✨ Newly Introduced Findings ({len(new_findings)})")
            if new_findings:
                for nf in new_findings:
                    n_badge = {
                        "supported": ("#16a34a", "SUPPORTED"),
                        "unresolved": ("#ea580c", "UNRESOLVED"),
                        "conflict": ("#dc2626", "CONFLICT"),
                        "needs_human_review": ("#7c3aed", "NEEDS HUMAN REVIEW"),
                    }.get(nf.status, ("#64748b", nf.status.upper()))
                    with st.expander(f"{nf.topic} — {n_badge[1]} (Newly Introduced, Rev 1)", expanded=False):
                        st.markdown(f"**Conclusion:** {nf.conclusion}")
                        if nf.evidence:
                            st.markdown(f"**Evidence:** *\"{nf.evidence[0].quote}\"* (Page {nf.evidence[0].page})")
                        st.markdown(f"**Next Action:** {nf.next_action}")
            else:
                st.caption("None.")


    with tab_export:
        st.subheader("📥 Review Packet Preview & Deterministic Export")
        st.caption(
            "Preview and download an immutable, self-contained HTML Review Packet for administrative "
            "preparation, hospital admission desk clarification, and insurer correspondence."
        )

        # 1. Collect available packets
        all_packets: list[ReviewPacket] = []
        if review_repo:
            all_packets = review_repo.list_review_packets(case.case_id)
        if not all_packets and persisted_packet:
            all_packets = [persisted_packet]

        selected_export_packet: ReviewPacket | None = None

        if all_packets:
            if len(all_packets) > 1:
                packet_options = {
                    f"v{p.packet_version} • {p.packet_id} ({p.generated_at.strftime('%H:%M:%S UTC')}) — {p.review_status.upper()}": p
                    for p in all_packets
                }
                selected_label = st.selectbox(
                    "Select Packet Snapshot Version to Preview & Export:",
                    options=list(packet_options.keys()),
                    index=0,
                    key="export_packet_version_selector",
                )
                selected_export_packet = packet_options[selected_label]
            else:
                selected_export_packet = all_packets[0]
        else:
            st.info(
                "ℹ️ **No Review Packet Yet**: No analysis has been executed yet for this case. "
                "Execute a review in the **🔍 Findings & Review** tab to produce a saved review packet."
            )
            with st.expander("🧪 Preview & Export Sample Review Packet (M6 Demonstration)", expanded=False):
                st.caption("Demonstrates the M6 HTML export and preview format using a sample fixture.")
                sample_pkt = _load_sample_packet_fixture("supported_finding")
                if sample_pkt:
                    selected_export_packet = sample_pkt

        if selected_export_packet:
            # Perform hospital lookup
            hosp_directory = LocalSyntheticHospitalDirectory()
            hosp_result = hosp_directory.lookup_hospital(case.hospital_name)

            # Generate deterministic HTML string
            exported_html = generate_review_packet_html(
                packet=selected_export_packet,
                hospital_result=hosp_result,
                available_documents=documents,
            )

            # Prominent Action Bar
            col_dl1, col_dl2 = st.columns([2, 3])
            with col_dl1:
                st.download_button(
                    label=f"📥 Download Review Packet (v{selected_export_packet.packet_version} HTML)",
                    data=exported_html,
                    file_name=f"review_packet_{case.case_id}_v{selected_export_packet.packet_version}.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True,
                )
            with col_dl2:
                st.caption(
                    "✅ **Deterministic Export**: Rendered directly from the saved SQLite snapshot without "
                    "re-running model queries. Standalone file opens independently in any browser."
                )

            st.markdown("---")

            # ----------------------------------------------------------
            # 2. Live Review Packet Preview
            # ----------------------------------------------------------
            st.markdown("### 📄 Review Packet Live Preview")

            # Status Banner & Metadata Header
            st.markdown(
                f"""
                <div class="packet-banner" style="margin-bottom: 1rem; padding: 1rem 1.25rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-size: 1.25rem; font-weight: 800; color: #2563eb;">AdmitSense Review Packet</span><br>
                            <span style="font-size: 0.85rem;">
                                Packet ID: <code>{selected_export_packet.packet_id}</code> &bull; Version: <strong>v{selected_export_packet.packet_version}</strong> &bull; Run: <code>{selected_export_packet.run_id}</code>
                            </span>
                        </div>
                        <div style="text-align: right;">
                            <span style="background-color: {'#16a34a' if selected_export_packet.review_status == 'complete' else '#ea580c'}; color: white !important; padding: 0.25rem 0.75rem; border-radius: 4px; font-weight: 700; font-size: 0.85rem;">
                                {selected_export_packet.review_status.upper()}
                            </span><br>
                            <span style="font-size: 0.75rem;">{selected_export_packet.generated_at.strftime('%d %b %Y, %H:%M:%S UTC')}</span>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Incomplete Notice
            if selected_export_packet.review_status != "complete" or selected_export_packet.stopped_reason != "review_complete":
                stopped_label = persisted_reason_label(selected_export_packet.stopped_reason)
                st.warning(
                    f"⚠️ **Incomplete Review Packet Notice • Stop Reason: {stopped_label.upper()}**\n\n"
                    f"This review packet represents partial or bounded execution results. "
                    f"Stop details: {selected_export_packet.stop_details or 'Budget or timeout reached'}. "
                    "Findings, checklist items, and limitations reflect documents reviewed prior to stop."
                )

            # Mandatory Insurer Authorisation Banner
            render_authorization_badge(selected_export_packet.authorization_status)
            st.info(
                "🛡️ **Authorisation Invariant Notice**: AdmitSense assists administrative preparation for planned hospital "
                "admission. Findings describe condition satisfaction against available documents; they do NOT establish "
                "overall insurance policy coverage, cashless eligibility, or insurer approval."
            )

            # Case & Admission Details
            with st.expander("📋 1. Case & Planned Admission Details", expanded=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**Patient Name:** {case.member_name or 'Unknown'}")
                    st.markdown(f"**Policy ID:** `{case.policy_id or 'Unknown'}`")
                with c2:
                    st.markdown(f"**Procedure:** {case.procedure or 'Unknown'}")
                    st.markdown(f"**Planned Admission:** {case.planned_admission_date.strftime('%d %b %Y') if case.planned_admission_date else 'Unknown'}")
                with c3:
                    st.markdown(f"**Coverage Start:** {case.continuous_coverage_start_date.strftime('%d %b %Y') if case.continuous_coverage_start_date else 'Unknown'}")
                    st.markdown(f"**Estimated Cost:** {f'INR {case.estimated_cost:,.2f}' if case.estimated_cost else 'Unknown'}")

            # Hospital Reference Display
            with st.expander("🏥 2. Hospital Directory Reference (Demonstration Data)", expanded=True):
                if hosp_result.status == "matched" and hosp_result.record:
                    rec = hosp_result.record
                    st.markdown(
                        f"""
                        <div class="hospital-box">
                            <span style="background-color: rgba(168, 85, 247, 0.2); color: #7e22ce; font-weight: 700; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px;">SYNTHETIC DEMONSTRATION DATA</span>
                            <h4>{rec.hospital_name}</h4>
                            <div style="font-size: 0.85rem;">
                                City: <strong>{rec.city}</strong> &bull; Record ID: <code>{rec.record_id}</code> &bull; Tier: <strong>{rec.network_tier.upper().replace('_', ' ')}</strong> &bull; TPA Desk: <strong>{rec.tpa_desk_contact or 'Not listed'}</strong>
                            </div>
                            <div style="font-size: 0.8rem; margin-top: 0.35rem;">
                                Dataset Version: <strong>{rec.dataset_version}</strong> &bull; Date: {rec.dataset_date.strftime('%d %b %Y')}
                            </div>
                            <div style="font-size: 0.8rem; color: #7c3aed; background-color: rgba(139, 92, 246, 0.12); padding: 0.45rem 0.65rem; border-radius: 4px; margin-top: 0.5rem;">
                                ⚠️ <strong>Notice:</strong> Synthetic hospital directory match does NOT verify live insurer network agreement, cashless eligibility, or claim approval.
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                elif hosp_result.status == "no_match":
                    st.warning(f"⚠️ **No Directory Match**: '{hosp_result.query}' was not found in synthetic dataset ({hosp_result.dataset_version}).")
                elif hosp_result.status == "ambiguous_match":
                    candidate_str = ", ".join(f"'{c.hospital_name}'" for c in hosp_result.candidates)
                    st.warning(f"⚠️ **Ambiguous Match**: Multiple facilities match query: {candidate_str}.")
                else:
                    st.info("ℹ️ **Hospital Not Specified**: No hospital facility recorded in case facts.")

            # Documents Reviewed
            with st.expander(f"📄 3. Documents Reviewed ({len(documents)})", expanded=False):
                if documents:
                    for d in documents:
                        pages_cnt = getattr(d, "total_pages", getattr(d, "page_count", len(getattr(d, "pages", []))))
                        st.markdown(f"- **{d.filename}** (`{d.document_id}`, {d.version}) — {pages_cnt} pages [{d.extraction_status}]")
                else:
                    st.caption("No document records attached.")

            # Current Findings
            with st.expander(f"🔍 4. Administrative Findings ({len(selected_export_packet.findings)})", expanded=True):
                for f in selected_export_packet.findings:
                    f_color = "#16a34a" if f.status == "supported" else ("#ea580c" if f.status == "unresolved" else "#dc2626")
                    st.markdown(
                        f"""
                        <div class="finding-preview-box" style="border-left: 5px solid {f_color} !important;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <strong>Rev {f.revision} &bull; {f.topic}</strong>
                                <span style="font-weight: 700; font-size: 0.75rem; color: {f_color} !important; text-transform: uppercase;">{f.status}</span>
                            </div>
                            <p style="margin: 0.4rem 0 0.4rem 0; font-size: 0.92rem;">{f.conclusion}</p>
                            <div style="font-size: 0.85rem; color: #166534; background: rgba(34, 197, 94, 0.12); padding: 0.45rem 0.65rem; border-radius: 4px;">
                                <strong>Next Action:</strong> {f.next_action}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if f.evidence:
                        for ev in f.evidence:
                            st.caption(f"📍 Cited: `{ev.document_id}` ({ev.document_version}), Page {ev.page}: *\"{ev.quote[:100]}...\"*")

            # Missing Evidence Checklist
            with st.expander(f"📝 5. Missing Evidence Checklist ({len(selected_export_packet.missing_evidence_checklist)})", expanded=True):
                if selected_export_packet.missing_evidence_checklist:
                    for item in selected_export_packet.missing_evidence_checklist:
                        st.markdown(f"- **{item.requested_information}** [{item.status.upper()}] — *{item.why_it_matters}* (Source: {item.suggested_source or 'Caregiver'})")
                else:
                    st.caption("No missing evidence items recorded.")

            # Questions for Hospital Desk / Insurer
            with st.expander("❓ 6. Questions for Hospital Admission Desk & Insurer", expanded=True):
                q_items = list(selected_export_packet.unresolved_questions)
                for item in selected_export_packet.missing_evidence_checklist:
                    if item.status == "requested":
                        q_items.append(f"Ask {item.suggested_source or 'admission desk'}: {item.requested_information} ({item.why_it_matters})")
                if q_items:
                    for q in q_items:
                        st.markdown(f"- ❓ {q}")
                else:
                    st.caption("No unresolved questions recorded.")

            # Revisions History
            if selected_export_packet.revisions:
                with st.expander(f"🔄 7. Revision Audit Trail ({len(selected_export_packet.revisions)})", expanded=False):
                    for rev in selected_export_packet.revisions:
                        st.markdown(
                            f"- **{rev.finding_id}**: Rev {rev.old_finding_revision} ({rev.old_status}) &rarr; **Rev {rev.new_finding_revision} ({rev.new_status})** &bull; Trigger: `{rev.trigger_type}`<br>"
                            f"  *Reason:* {rev.reason}",
                            unsafe_allow_html=True,
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
