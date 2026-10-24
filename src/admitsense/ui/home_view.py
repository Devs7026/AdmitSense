from __future__ import annotations

import streamlit as st
from admitsense.storage.case_repository import CaseRepository


def render_home_view(repo: CaseRepository) -> None:
    st.subheader("Welcome, Caregiver")
    st.markdown(
        """
        Preparing for a planned hospital admission? AdmitSense helps you organize policy facts,
        trace citations, identify missing evidence, and clarify questions before hospital desk check-in.
        """
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("➕ Create New Case", type="primary", use_container_width=True):
            st.session_state.current_case_id = None
            st.session_state.current_view = "setup"
            st.rerun()

    st.markdown("---")
    st.subheader("Saved Cases")

    cases = repo.list_cases()
    if not cases:
        st.info(
            "No cases created yet. Click **Create New Case** above to begin preparing for an admission."
        )
        return

    for case in cases:
        with st.container():
            c1, c2, c3, c4 = st.columns([2, 3, 3, 2])
            with c1:
                st.markdown(f"**ID:** `{case.case_id}`")
                patient_display = case.member_name or "_Unknown / Unspecified_"
                st.markdown(f"**Patient:** {patient_display}")
            with c2:
                proc_display = case.procedure or "_Not specified_"
                hosp_display = case.hospital_name or "_Not specified_"
                st.markdown(f"**Procedure:** {proc_display}")
                st.markdown(f"**Hospital:** {hosp_display}")
            with c3:
                pol_display = case.policy_id or "_Not specified_"
                date_display = (
                    case.planned_admission_date.strftime("%d %b %Y")
                    if case.planned_admission_date
                    else "_Not specified_"
                )
                st.markdown(f"**Policy:** {pol_display}")
                st.markdown(f"**Admission Date:** {date_display}")
            with c4:
                if st.button(
                    "Open Case ➔",
                    key=f"open_{case.case_id}",
                    use_container_width=True,
                ):
                    st.session_state.current_case_id = case.case_id
                    st.session_state.current_view = "workspace"
                    st.rerun()
            st.markdown("<hr style='margin: 0.5rem 0;'>", unsafe_allow_html=True)
