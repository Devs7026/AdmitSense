from __future__ import annotations

import streamlit as st


def apply_custom_styles() -> None:
    st.markdown(
        """
        <style>
        /* ==========================================================================
           AdmitSense Design System & Contrast Optimization
           Guarantees high-contrast, crystal-clear readability in both Light and Dark themes
           ========================================================================== */

        /* Base Typography & Streamlit Markdown Invariants */
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMarkdownContainer"] label {
            letter-spacing: -0.01em;
        }

        /* Streamlit Dark & Light Theme Adaptive Variables */
        :root {
            --as-text-primary: var(--text-color, #0f172a);
            --as-text-muted: #64748b;
            --as-card-bg: var(--secondary-background-color, #ffffff);
            --as-card-border: rgba(148, 163, 184, 0.25);
            --as-accent-blue: #2563eb;
            --as-accent-purple: #7c3aed;
            --as-accent-amber: #d97706;
            --as-accent-emerald: #059669;
            --as-accent-rose: #e11d48;
        }

        /* Header Component */
        .admit-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            padding: 1.25rem 1.5rem;
            border-radius: 10px;
            color: #f8fafc !important;
            margin-bottom: 1.25rem;
            border: 1px solid #334155;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
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
            background-color: rgba(245, 158, 11, 0.15) !important;
            border: 1px solid rgba(245, 158, 11, 0.4) !important;
            border-left: 5px solid #f59e0b !important;
            color: #b45309 !important;
            padding: 0.85rem 1.15rem !important;
            border-radius: 6px !important;
            margin-bottom: 1rem !important;
            font-size: 0.92rem !important;
            font-weight: 500 !important;
            line-height: 1.45 !important;
        }
        .emergency-banner strong,
        .emergency-banner span {
            color: #92400e !important;
        }

        /* Pre-authorisation Status Banner */
        .auth-banner-box {
            background-color: var(--secondary-background-color, #f8fafc) !important;
            border: 1px solid rgba(148, 163, 184, 0.3) !important;
            border-radius: 6px !important;
            padding: 0.75rem 1rem !important;
            margin-bottom: 1rem !important;
        }
        .auth-banner-box span,
        .auth-banner-box strong {
            color: var(--text-color, #1e293b) !important;
        }
        .auth-banner-box p {
            color: var(--text-color, #64748b) !important;
            opacity: 0.85;
            margin: 0.35rem 0 0 0 !important;
            font-size: 0.82rem !important;
        }

        /* Recommended Next Action Card */
        .next-action-card {
            background-color: rgba(37, 99, 235, 0.12) !important;
            border: 1px solid rgba(37, 99, 235, 0.35) !important;
            border-left: 5px solid #2563eb !important;
            padding: 1rem 1.25rem !important;
            border-radius: 8px !important;
            margin-bottom: 1.25rem !important;
        }
        .next-action-card h4 {
            margin: 0 0 0.35rem 0 !important;
            color: #1d4ed8 !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
        }
        .next-action-card p,
        .next-action-card span,
        .next-action-card strong {
            margin: 0 !important;
            color: var(--text-color, #1e40af) !important;
            font-size: 0.95rem !important;
            line-height: 1.5 !important;
        }

        /* Generic Fact Card / Checklist Item Card */
        .fact-card {
            background-color: var(--secondary-background-color, #ffffff) !important;
            border: 1px solid rgba(148, 163, 184, 0.25) !important;
            border-radius: 8px !important;
            padding: 0.9rem 1.15rem !important;
            margin-bottom: 0.6rem !important;
            color: var(--text-color, #0f172a) !important;
        }
        .fact-card strong {
            color: var(--text-color, #0f172a) !important;
            font-weight: 700 !important;
        }
        .fact-card p,
        .fact-card span,
        .fact-card div {
            color: var(--text-color, #334155) !important;
        }
        .fact-card code {
            background-color: rgba(148, 163, 184, 0.18) !important;
            color: var(--text-color, #0f172a) !important;
            padding: 0.15rem 0.4rem !important;
            border-radius: 4px !important;
        }

        /* Cited Evidence Card & Quotes */
        .evidence-quote-box {
            background-color: rgba(148, 163, 184, 0.1) !important;
            border: 1px solid rgba(148, 163, 184, 0.25) !important;
            border-left: 4px solid #2563eb !important;
            padding: 0.65rem 0.95rem !important;
            border-radius: 6px !important;
            margin-bottom: 0.5rem !important;
            font-size: 0.9rem !important;
        }
        .evidence-quote-box em {
            color: var(--text-color, #1e293b) !important;
            font-style: italic !important;
            font-weight: 500 !important;
            display: block !important;
            margin-bottom: 0.35rem !important;
            line-height: 1.45 !important;
        }
        .evidence-quote-box span,
        .evidence-quote-box strong {
            color: var(--text-color, #475569) !important;
            font-size: 0.82rem !important;
        }
        .evidence-quote-box code {
            background-color: rgba(148, 163, 184, 0.2) !important;
            color: var(--text-color, #0f172a) !important;
            padding: 0.1rem 0.35rem !important;
            border-radius: 4px !important;
        }

        /* Hospital Reference Box */
        .hospital-box {
            background-color: rgba(139, 92, 246, 0.08) !important;
            border: 1px solid rgba(139, 92, 246, 0.3) !important;
            border-left: 5px solid #8b5cf6 !important;
            border-radius: 8px !important;
            padding: 0.95rem 1.25rem !important;
            margin-top: 0.5rem !important;
            color: var(--text-color, #1e1b4b) !important;
        }
        .hospital-box h4 {
            margin: 0.35rem 0 0.2rem 0 !important;
            font-size: 1.1rem !important;
            color: var(--text-color, #1e1b4b) !important;
            font-weight: 700 !important;
        }
        .hospital-box strong,
        .hospital-box span,
        .hospital-box div {
            color: var(--text-color, #334155) !important;
        }
        .hospital-box code {
            background-color: rgba(139, 92, 246, 0.18) !important;
            color: var(--text-color, #4c1d95) !important;
            padding: 0.15rem 0.4rem !important;
            border-radius: 4px !important;
        }

        /* Review Packet Status Banner */
        .packet-banner {
            background-color: var(--secondary-background-color, #f8fafc) !important;
            border: 1px solid rgba(148, 163, 184, 0.25) !important;
            border-radius: 8px !important;
            padding: 0.85rem 1.15rem !important;
            margin-bottom: 0.75rem !important;
        }
        .packet-banner span,
        .packet-banner strong,
        .packet-banner div {
            color: var(--text-color, #1e293b) !important;
        }
        .packet-banner code {
            background-color: rgba(148, 163, 184, 0.2) !important;
            color: var(--text-color, #0f172a) !important;
            padding: 0.15rem 0.45rem !important;
            border-radius: 4px !important;
        }

        /* Agent Tool Activity Steps */
        .activity-step-box {
            background-color: var(--secondary-background-color, #f8fafc) !important;
            border: 1px solid rgba(148, 163, 184, 0.2) !important;
            border-radius: 6px !important;
            padding: 0.5rem 0.85rem !important;
            margin-bottom: 0.4rem !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
        }
        .activity-step-box span,
        .activity-step-box strong {
            color: var(--text-color, #334155) !important;
        }
        .activity-step-box code {
            background-color: rgba(148, 163, 184, 0.2) !important;
            color: var(--text-color, #0f172a) !important;
            padding: 0.15rem 0.4rem !important;
            border-radius: 4px !important;
        }

        /* Replay Diff Cards */
        .diff-card-old {
            background-color: rgba(239, 68, 68, 0.08) !important;
            border: 1px solid rgba(239, 68, 68, 0.3) !important;
            border-radius: 6px !important;
            padding: 0.85rem 1rem !important;
            height: 100% !important;
        }
        .diff-card-old span,
        .diff-card-old strong {
            color: #dc2626 !important;
        }
        .diff-card-old p {
            color: var(--text-color, #7f1d1d) !important;
            font-size: 0.9rem !important;
            margin: 0 !important;
            line-height: 1.45 !important;
        }

        .diff-card-new {
            background-color: rgba(34, 197, 94, 0.08) !important;
            border: 1px solid rgba(34, 197, 94, 0.3) !important;
            border-radius: 6px !important;
            padding: 0.85rem 1rem !important;
            height: 100% !important;
        }
        .diff-card-new span,
        .diff-card-new strong {
            color: #16a34a !important;
        }
        .diff-card-new p {
            color: var(--text-color, #14532d) !important;
            font-size: 0.9rem !important;
            margin: 0 !important;
            line-height: 1.45 !important;
        }

        /* Export Preview Finding Card */
        .finding-preview-box {
            border: 1px solid rgba(148, 163, 184, 0.25) !important;
            border-radius: 6px !important;
            padding: 0.85rem 1.15rem !important;
            margin-bottom: 0.75rem !important;
            background-color: var(--secondary-background-color, #ffffff) !important;
        }
        .finding-preview-box strong,
        .finding-preview-box p,
        .finding-preview-box span,
        .finding-preview-box div {
            color: var(--text-color, #0f172a) !important;
        }

        /* Extracted Text Monospace Box */
        .extracted-text-viewer {
            background-color: var(--secondary-background-color, #f8fafc) !important;
            border: 1px solid rgba(148, 163, 184, 0.25) !important;
            border-radius: 6px !important;
            padding: 1.1rem !important;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
            font-size: 0.9rem !important;
            line-height: 1.55 !important;
            color: var(--text-color, #1e293b) !important;
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
            background-color: rgba(14, 165, 233, 0.18) !important;
            color: #0284c7 !important;
            border: 1px solid rgba(14, 165, 233, 0.35) !important;
        }
        .provenance-doc {
            background-color: rgba(168, 85, 247, 0.18) !important;
            color: #9333ea !important;
            border: 1px solid rgba(168, 85, 247, 0.35) !important;
        }
        .provenance-derived {
            background-color: rgba(245, 158, 11, 0.18) !important;
            color: #d97706 !important;
            border: 1px solid rgba(245, 158, 11, 0.35) !important;
        }
        .fixture-tag {
            background-color: rgba(239, 68, 68, 0.12) !important;
            border: 1px dashed #ef4444 !important;
            color: #dc2626 !important;
            padding: 0.65rem 0.9rem !important;
            border-radius: 6px !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            margin-bottom: 1rem !important;
        }
        .fixture-tag strong {
            color: #b91c1c !important;
        }

        /* Streamlit Default Code & Inline Text Overrides */
        code {
            background-color: rgba(148, 163, 184, 0.2) !important;
            color: var(--text-color, #0f172a) !important;
            padding: 0.15rem 0.35rem !important;
            border-radius: 4px !important;
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
