from __future__ import annotations

import streamlit as st


def apply_custom_styles() -> None:
    st.markdown(
        """
        <style>
        /* ==========================================================================
           AdmitSense Design System & Contrast Optimization (Dark & High-Contrast Mode)
           Guarantees crisp, luminous readability: no white-on-white and no black-on-black.
           ========================================================================== */

        /* Base Typography */
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMarkdownContainer"] label {
            letter-spacing: -0.01em;
        }

        /* All Inline Code & Monospace Badges (Fixes Black-on-Black) */
        code,
        [data-testid="stMarkdownContainer"] code {
            background-color: rgba(56, 189, 248, 0.12) !important;
            color: #38bdf8 !important;
            border: 1px solid rgba(56, 189, 248, 0.28) !important;
            padding: 0.15rem 0.42rem !important;
            border-radius: 4px !important;
            font-size: 0.88em !important;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
        }

        /* App Header */
        .admit-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            padding: 1.25rem 1.5rem;
            border-radius: 10px;
            color: #f8fafc !important;
            margin-bottom: 1.25rem;
            border: 1px solid #334155;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }
        .admit-header h1 {
            color: #ffffff !important;
            font-size: 1.75rem;
            margin: 0;
            padding: 0;
            font-weight: 700;
        }
        .admit-header p {
            color: #94a3b8 !important;
            margin: 0.25rem 0 0 0;
            font-size: 0.95rem;
        }

        /* Medical Emergency Notice */
        .emergency-banner {
            background-color: rgba(245, 158, 11, 0.16) !important;
            border: 1px solid rgba(245, 158, 11, 0.4) !important;
            border-left: 5px solid #f59e0b !important;
            color: #fde68a !important;
            padding: 0.85rem 1.15rem !important;
            border-radius: 6px !important;
            margin-bottom: 1rem !important;
            font-size: 0.92rem !important;
            font-weight: 500 !important;
            line-height: 1.5 !important;
        }
        .emergency-banner strong,
        .emergency-banner span {
            color: #fef08a !important;
        }

        /* Pre-authorisation Status Banner */
        .auth-banner-box {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 6px !important;
            padding: 0.75rem 1rem !important;
            margin-bottom: 1rem !important;
        }
        .auth-banner-box span,
        .auth-banner-box strong {
            color: #f8fafc !important;
        }
        .auth-banner-box p {
            color: #94a3b8 !important;
            margin: 0.35rem 0 0 0 !important;
            font-size: 0.82rem !important;
            line-height: 1.4 !important;
        }

        /* Recommended Next Action Card */
        .next-action-card {
            background-color: rgba(30, 58, 138, 0.35) !important;
            border: 1px solid rgba(59, 130, 246, 0.45) !important;
            border-left: 5px solid #3b82f6 !important;
            padding: 1rem 1.25rem !important;
            border-radius: 8px !important;
            margin-bottom: 1.25rem !important;
        }
        .next-action-card h4 {
            margin: 0 0 0.35rem 0 !important;
            color: #60a5fa !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
        }
        .next-action-card p,
        .next-action-card span,
        .next-action-card strong {
            margin: 0 !important;
            color: #f1f5f9 !important;
            font-size: 0.95rem !important;
            line-height: 1.5 !important;
        }

        /* Generic Fact Card / Checklist Item Card */
        .fact-card {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
            padding: 0.9rem 1.15rem !important;
            margin-bottom: 0.6rem !important;
            color: #f8fafc !important;
        }
        .fact-card strong {
            color: #ffffff !important;
            font-weight: 700 !important;
        }
        .fact-card p,
        .fact-card span,
        .fact-card div {
            color: #e2e8f0 !important;
        }

        /* Cited Evidence Card & Quotes (Fixes Quote Readability) */
        .evidence-quote-box {
            background-color: rgba(30, 41, 59, 0.85) !important;
            border: 1px solid #334155 !important;
            border-left: 4px solid #3b82f6 !important;
            padding: 0.75rem 1rem !important;
            border-radius: 6px !important;
            margin-bottom: 0.6rem !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3) !important;
        }
        .evidence-quote-box em {
            color: #f8fafc !important;
            font-style: italic !important;
            font-weight: 500 !important;
            display: block !important;
            margin-bottom: 0.45rem !important;
            line-height: 1.55 !important;
            font-size: 0.95rem !important;
        }
        .evidence-quote-box span {
            color: #94a3b8 !important;
            font-size: 0.82rem !important;
        }
        .evidence-quote-box strong {
            color: #f1f5f9 !important;
            font-weight: 700 !important;
        }

        /* Hospital Reference Box */
        .hospital-box {
            background-color: rgba(88, 28, 135, 0.25) !important;
            border: 1px solid rgba(168, 85, 247, 0.4) !important;
            border-left: 5px solid #a855f7 !important;
            border-radius: 8px !important;
            padding: 0.95rem 1.25rem !important;
            margin-top: 0.5rem !important;
            color: #f8fafc !important;
        }
        .hospital-box h4 {
            margin: 0.35rem 0 0.2rem 0 !important;
            font-size: 1.1rem !important;
            color: #e9d5ff !important;
            font-weight: 700 !important;
        }
        .hospital-box strong,
        .hospital-box span,
        .hospital-box div {
            color: #e2e8f0 !important;
        }
        .hospital-box code {
            background-color: rgba(168, 85, 247, 0.25) !important;
            color: #c084fc !important;
            border-color: rgba(168, 85, 247, 0.35) !important;
        }

        /* Review Packet Status Banner */
        .packet-banner {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
            padding: 0.85rem 1.15rem !important;
            margin-bottom: 0.75rem !important;
            color: #f8fafc !important;
        }
        .packet-banner span,
        .packet-banner strong,
        .packet-banner div {
            color: #f8fafc !important;
        }

        /* Agent Tool Activity Steps */
        .activity-step-box {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 6px !important;
            padding: 0.5rem 0.85rem !important;
            margin-bottom: 0.4rem !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
        }
        .activity-step-box span,
        .activity-step-box strong {
            color: #f1f5f9 !important;
        }

        /* Replay Diff Cards */
        .diff-card-old {
            background-color: rgba(239, 68, 68, 0.15) !important;
            border: 1px solid rgba(239, 68, 68, 0.4) !important;
            border-radius: 6px !important;
            padding: 0.85rem 1rem !important;
            height: 100% !important;
        }
        .diff-card-old span,
        .diff-card-old strong {
            color: #fca5a5 !important;
        }
        .diff-card-old p {
            color: #fecaca !important;
            font-size: 0.92rem !important;
            margin: 0 !important;
            line-height: 1.5 !important;
        }

        .diff-card-new {
            background-color: rgba(34, 197, 94, 0.15) !important;
            border: 1px solid rgba(34, 197, 94, 0.4) !important;
            border-radius: 6px !important;
            padding: 0.85rem 1rem !important;
            height: 100% !important;
        }
        .diff-card-new span,
        .diff-card-new strong {
            color: #86efac !important;
        }
        .diff-card-new p {
            color: #bbf7d0 !important;
            font-size: 0.92rem !important;
            margin: 0 !important;
            line-height: 1.5 !important;
        }

        /* Export Preview Finding Card */
        .finding-preview-box {
            border: 1px solid #334155 !important;
            border-radius: 6px !important;
            padding: 0.85rem 1.15rem !important;
            margin-bottom: 0.75rem !important;
            background-color: #1e293b !important;
            color: #f8fafc !important;
        }
        .finding-preview-box strong {
            color: #ffffff !important;
        }
        .finding-preview-box p,
        .finding-preview-box span,
        .finding-preview-box div {
            color: #e2e8f0 !important;
        }

        /* Extracted Text Monospace Box */
        .extracted-text-viewer {
            background-color: #0f172a !important;
            border: 1px solid #334155 !important;
            border-radius: 6px !important;
            padding: 1.1rem !important;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
            font-size: 0.9rem !important;
            line-height: 1.55 !important;
            color: #f1f5f9 !important;
            white-space: pre-wrap !important;
        }
        .extracted-text-viewer * {
            color: inherit !important;
        }

        /* Provenance and Status Tags */
        .provenance-tag {
            font-size: 0.75rem !important;
            padding: 0.2rem 0.5rem !important;
            border-radius: 4px !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            display: inline-block !important;
        }
        .provenance-user {
            background-color: rgba(14, 165, 233, 0.2) !important;
            color: #38bdf8 !important;
            border: 1px solid rgba(14, 165, 233, 0.4) !important;
        }
        .provenance-doc {
            background-color: rgba(168, 85, 247, 0.2) !important;
            color: #c084fc !important;
            border: 1px solid rgba(168, 85, 247, 0.4) !important;
        }
        .provenance-derived {
            background-color: rgba(245, 158, 11, 0.2) !important;
            color: #fbbf24 !important;
            border: 1px solid rgba(245, 158, 11, 0.4) !important;
        }
        .fixture-tag {
            background-color: rgba(239, 68, 68, 0.15) !important;
            border: 1px dashed #ef4444 !important;
            color: #fca5a5 !important;
            padding: 0.65rem 0.9rem !important;
            border-radius: 6px !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            margin-bottom: 1rem !important;
        }
        .fixture-tag strong {
            color: #fecaca !important;
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
        text = "Pending Insurer Review"
    else:
        color = "#64748b"
        text = "Not Verified (Default)"

    st.markdown(
        f"""
        <div class="auth-banner-box">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600; font-size: 0.95rem;">Pre-authorisation Status:</span>
                <span style="background-color: {color}; color: white !important; padding: 0.25rem 0.65rem; border-radius: 4px; font-size: 0.85rem; font-weight: 700;">{text}</span>
            </div>
            <p>
                AdmitSense findings support administrative preparation; they never establish overall policy coverage or insurer claim approval.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
