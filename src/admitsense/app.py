from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is on sys.path
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
from admitsense.storage.case_repository import CaseRepository
from admitsense.ui.case_setup_view import render_case_setup_view
from admitsense.ui.components import apply_custom_styles, render_app_header
from admitsense.ui.home_view import render_home_view
from admitsense.ui.workspace_view import render_workspace_view


def init_session_state() -> CaseRepository:
    if "current_view" not in st.session_state:
        st.session_state.current_view = "home"
    if "current_case_id" not in st.session_state:
        st.session_state.current_case_id = None
    if "repo" not in st.session_state:
        st.session_state.repo = CaseRepository()

    return st.session_state.repo


def main() -> None:
    st.set_page_config(
        page_title="AdmitSense — Hospital Admission Insurance Review",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    apply_custom_styles()
    repo = init_session_state()

    # Sidebar Navigation & Status
    with st.sidebar:
        st.markdown("### 🏥 AdmitSense")
        st.caption("Caregiver Admission Prep Assistant")
        st.markdown("---")

        if st.button("🏠 Home (Saved Cases)", use_container_width=True):
            st.session_state.current_view = "home"
            st.rerun()

        if st.button("➕ New Case Setup", use_container_width=True):
            st.session_state.current_case_id = None
            st.session_state.current_view = "setup"
            st.rerun()

        if st.session_state.current_case_id:
            st.markdown("---")
            st.markdown(f"**Active Case:**")
            st.code(st.session_state.current_case_id, language="text")
            if st.button("📂 Open Workspace", use_container_width=True):
                st.session_state.current_view = "workspace"
                st.rerun()

        st.markdown("---")
        st.caption("AdmitSense v0.1.0 • Milestone M1-A")

    # Header
    render_app_header()

    # Route View
    current_view = st.session_state.current_view
    if current_view == "home":
        render_home_view(repo)
    elif current_view == "setup":
        render_case_setup_view(repo)
    elif current_view == "workspace":
        render_workspace_view(repo)
    else:
        st.session_state.current_view = "home"
        render_home_view(repo)


if __name__ == "__main__":
    main()
