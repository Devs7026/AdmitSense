from __future__ import annotations

import streamlit as st


def apply_custom_styles() -> None:
    st.markdown(
        """
        <style>
        /* Modern healthcare card and badge styling */
        .admit-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            padding: 1.25rem 1.5rem;
            border-radius: 10px;
            color: #f8fafc;
            margin-bottom: 1.25rem;
            border: 1px solid #334155;
        }
        .admit-header h1 {
            color: #ffffff;
            font-size: 1.75rem;
            margin: 0;
            padding: 0;
            font-weight: 700;
        }
        .admit-header p {
            color: #94a3b8;
            margin: 0.25rem 0 0 0;
            font-size: 0.95rem;
        }
        .emergency-banner {
            background-color: #fffbeb;
            border-left: 4px solid #f59e0b;
            color: #92400e;
            padding: 0.75rem 1rem;
            border-radius: 4px;
            margin-bottom: 1rem;
            font-size: 0.9rem;
            font-weight: 500;
        }
        .auth-banner-unverified {
            background-color: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 0.75rem 1rem;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .next-action-card {
            background: #eff6ff;
            border-left: 4px solid #3b82f6;
            padding: 1rem;
            border-radius: 6px;
            margin-bottom: 1.25rem;
        }
        .fact-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.85rem;
            margin-bottom: 0.5rem;
        }
        .provenance-tag {
            font-size: 0.75rem;
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .provenance-user {
            background-color: #e0f2fe;
            color: #0369a1;
        }
        .provenance-doc {
            background-color: #f3e8ff;
            color: #7e22ce;
        }
        .provenance-derived {
            background-color: #fef3c7;
            color: #b45309;
        }
        .fixture-tag {
            background-color: #fef2f2;
            border: 1px dashed #ef4444;
            color: #b91c1c;
            padding: 0.5rem 0.75rem;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_emergency_notice() -> None:
    st.markdown(
        """
        <div class="emergency-banner">
            ⚠️ <strong>Medical Emergency Notice:</strong> AdmitSense is an administrative preparation aid.
            Never delay emergency medical treatment for insurance review or paperwork.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_app_header() -> None:
    st.markdown(
        """
        <div class="admit-header">
            <h1>🏥 AdmitSense</h1>
            <p>Hospital Admission Administrative Review & Evidence Preparation</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_emergency_notice()


def render_authorization_badge(status: str) -> None:
    if status == "pending insurer review":
        color = "#d97706"
        bg = "#fffbeb"
        text = "Pending Insurer Review"
    else:
        color = "#475569"
        bg = "#f1f5f9"
        text = "Not Verified (Default)"

    st.markdown(
        f"""
        <div style="background-color: {bg}; border: 1px solid {color}44; border-radius: 6px; padding: 0.65rem 0.9rem; margin-bottom: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600; color: #1e293b;">Pre-authorisation Status:</span>
                <span style="background-color: {color}; color: white; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; font-weight: 600;">{text}</span>
            </div>
            <p style="margin: 0.35rem 0 0 0; font-size: 0.8rem; color: #64748b;">
                AdmitSense findings support administrative preparation; they never establish overall policy coverage or insurer claim approval.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
