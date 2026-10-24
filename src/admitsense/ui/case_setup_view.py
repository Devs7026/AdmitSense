from __future__ import annotations

import datetime
from decimal import Decimal
import uuid

import streamlit as st
from admitsense.schemas import CaseDetails, FactSource
from admitsense.storage.case_repository import CaseRepository


def render_case_setup_view(repo: CaseRepository) -> None:
    is_editing = bool(st.session_state.get("current_case_id"))
    existing_case: CaseDetails | None = None

    if is_editing:
        existing_case = repo.get_case(st.session_state.current_case_id)
        st.subheader(f"Edit Case Facts: `{st.session_state.current_case_id}`")
    else:
        st.subheader("Setup New Hospital Admission Case")

    st.markdown(
        """
        Enter any facts you currently have.
        **Incomplete information is completely fine**: any field left blank or marked unknown
        is preserved as `None`. AdmitSense never invents dummy or placeholder values.
        """
    )

    # Prepopulate values if editing
    default_case_id = (
        existing_case.case_id
        if existing_case
        else f"case-{datetime.date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4]}"
    )
    default_name = existing_case.member_name if existing_case and existing_case.member_name else ""
    default_policy = existing_case.policy_id if existing_case and existing_case.policy_id else ""
    default_proc = existing_case.procedure if existing_case and existing_case.procedure else ""
    default_hosp = existing_case.hospital_name if existing_case and existing_case.hospital_name else ""
    default_cost = float(existing_case.estimated_cost) if existing_case and existing_case.estimated_cost else 0.0

    with st.form("case_setup_form"):
        col1, col2 = st.columns(2)

        with col1:
            case_id = st.text_input(
                "Case Identifier *",
                value=default_case_id,
                disabled=is_editing,
                help="Unique identifier for this hospital admission case.",
            )
            member_name = st.text_input(
                "Patient / Member Name",
                value=default_name,
                placeholder="e.g. Ramesh Sharma (leave blank if unknown)",
            )
            policy_id = st.text_input(
                "Policy ID / Policy Number",
                value=default_policy,
                placeholder="e.g. POL-998877 (leave blank if unknown)",
            )
            procedure = st.text_input(
                "Planned Procedure / Treatment",
                value=default_proc,
                placeholder="e.g. Total Knee Replacement",
            )

        with col2:
            hospital_name = st.text_input(
                "Hospital Name",
                value=default_hosp,
                placeholder="e.g. Apex Super Specialty Hospital",
            )

            # Dates with explicit unknown toggles
            col_d1, col_t1 = st.columns([3, 2])
            with col_d1:
                adm_date = st.date_input(
                    "Planned Admission Date",
                    value=existing_case.planned_admission_date
                    if (existing_case and existing_case.planned_admission_date)
                    else datetime.date.today(),
                )
            with col_t1:
                adm_unknown = st.checkbox(
                    "Date Unknown",
                    value=not (existing_case and existing_case.planned_admission_date),
                    key="adm_unknown_toggle",
                )

            col_d2, col_t2 = st.columns([3, 2])
            with col_d2:
                cov_date = st.date_input(
                    "Continuous Coverage Start Date",
                    value=existing_case.continuous_coverage_start_date
                    if (existing_case and existing_case.continuous_coverage_start_date)
                    else datetime.date.today() - datetime.timedelta(days=730),
                )
            with col_t2:
                cov_unknown = st.checkbox(
                    "Coverage Start Unknown",
                    value=not (existing_case and existing_case.continuous_coverage_start_date),
                    key="cov_unknown_toggle",
                )

            col_c1, col_c2 = st.columns([3, 2])
            with col_c1:
                cost_val = st.number_input(
                    "Estimated Cost (INR)",
                    min_value=0.0,
                    step=5000.0,
                    value=default_cost,
                )
            with col_c2:
                cost_unknown = st.checkbox(
                    "Cost Unknown",
                    value=not (existing_case and existing_case.estimated_cost is not None),
                    key="cost_unknown_toggle",
                )

        st.caption("ℹ️ Facts entered here will be recorded with provenance `user_provided`.")

        b1, b2 = st.columns([1, 4])
        with b1:
            submitted = st.form_submit_button(
                "Save Case ➔", type="primary", use_container_width=True
            )
        with b2:
            cancel = st.form_submit_button("Cancel", use_container_width=False)

    if cancel:
        if is_editing:
            st.session_state.current_view = "workspace"
        else:
            st.session_state.current_view = "home"
        st.rerun()

    if submitted:
        if not case_id or not case_id.strip():
            st.error("Case Identifier is required.")
            return

        # Build CaseDetails respecting unknown values and strict fact provenance
        fact_sources: dict[str, FactSource] = {}

        clean_name = member_name.strip() if member_name and member_name.strip() else None
        if clean_name:
            fact_sources["member_name"] = FactSource(source_type="user_provided")

        clean_policy = policy_id.strip() if policy_id and policy_id.strip() else None
        if clean_policy:
            fact_sources["policy_id"] = FactSource(source_type="user_provided")

        clean_proc = procedure.strip() if procedure and procedure.strip() else None
        if clean_proc:
            fact_sources["procedure"] = FactSource(source_type="user_provided")

        clean_hosp = hospital_name.strip() if hospital_name and hospital_name.strip() else None
        if clean_hosp:
            fact_sources["hospital_name"] = FactSource(source_type="user_provided")

        final_adm_date = None if adm_unknown else adm_date
        if final_adm_date:
            fact_sources["planned_admission_date"] = FactSource(source_type="user_provided")

        final_cov_date = None if cov_unknown else cov_date
        if final_cov_date:
            fact_sources["continuous_coverage_start_date"] = FactSource(
                source_type="user_provided"
            )

        final_cost = None if cost_unknown or cost_val <= 0 else Decimal(str(cost_val))
        if final_cost is not None:
            fact_sources["estimated_cost"] = FactSource(source_type="user_provided")

        try:
            case = CaseDetails(
                case_id=case_id.strip(),
                member_name=clean_name,
                policy_id=clean_policy,
                continuous_coverage_start_date=final_cov_date,
                planned_admission_date=final_adm_date,
                procedure=clean_proc,
                hospital_name=clean_hosp,
                estimated_cost=final_cost,
                currency="INR",
                fact_sources=fact_sources,
            )

            if is_editing:
                repo.update_case(case)
                st.success(f"Case '{case.case_id}' updated successfully.")
            else:
                repo.create_case(case)
                st.success(f"Case '{case.case_id}' created successfully.")

            st.session_state.current_case_id = case.case_id
            st.session_state.current_view = "workspace"
            st.rerun()

        except Exception as e:
            st.error(f"Validation error saving case: {e}")
