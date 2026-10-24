"""Self-Contained Review Packet HTML Exporter (Milestone M6).

Conforms to DEC-004, DEC-006, and CONTRACTS.md:
- Deterministic rendering directly from a saved ReviewPacket snapshot.
- No live model calls, reassessments, or database writes during export.
- Complete HTML escaping of all user, document, model, and hospital strings (safe against XSS).
- No secrets, local filesystem paths, or broken internal links.
- Embedded responsive CSS and print stylesheet (@media print).
- Visible incomplete-review notices, synthetic hospital disclaimers, and strict
  non-authorisation invariants.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from typing import Sequence

from admitsense.documents.hospital_directory import HospitalLookupResult
from admitsense.documents.models import DocumentRecord
from admitsense.schemas import (
    Evidence,
    Finding,
    HospitalRecordReference,
    ReviewPacket,
    Revision,
)


def _esc(val: object | None) -> str:
    """Safely escapes text for inclusion in HTML."""
    if val is None:
        return ""
    return html.escape(str(val))


def _format_date(d: date | datetime | str | None) -> str:
    if d is None:
        return "Not specified"
    if isinstance(d, datetime):
        return d.strftime("%d %b %Y, %H:%M:%S UTC")
    if isinstance(d, date):
        return d.strftime("%d %b %Y")
    return _esc(str(d))


def _status_color_class(status: str) -> str:
    mapping = {
        "supported": "badge-supported",
        "unresolved": "badge-unresolved",
        "conflict": "badge-conflict",
        "needs_human_review": "badge-human-review",
        "complete": "badge-complete",
        "incomplete": "badge-incomplete",
        "failed": "badge-failed",
    }
    return mapping.get(status.lower(), "badge-default")


def _stopped_reason_label(reason: str) -> str:
    labels = {
        "review_complete": "Review Complete",
        "missing_information": "Missing Information",
        "conflicting_evidence": "Conflicting Evidence",
        "needs_human_review": "Needs Human Review",
        "tool_limit_reached": "Tool Limit Reached (Max 8 Calls)",
        "timeout": "Timeout (Execution Time Limit)",
        "processing_error": "Processing Error",
    }
    return labels.get(reason, reason.replace("_", " ").title())


def generate_review_packet_html(
    packet: ReviewPacket,
    hospital_result: HospitalLookupResult | None = None,
    hospital_record: HospitalRecordReference | None = None,
    available_documents: Sequence[DocumentRecord] | None = None,
) -> str:
    """Renders a self-contained, standalone HTML document from a saved ReviewPacket snapshot.

    Arguments:
        packet: The exact saved ReviewPacket model retrieved from SQLite.
        hospital_result: Optional HospitalLookupResult for directory display.
        hospital_record: Optional HospitalRecordReference if already attached.
        available_documents: Optional list of DocumentRecord objects describing reviewed files.

    Returns:
        A standalone HTML5 string ready for browser rendering or offline saving.
    """
    case = packet.case
    active_hospital = hospital_record or packet.hospital_record or getattr(packet, "hospital_reference", None)
    if active_hospital is None and hospital_result and hospital_result.record:
        active_hospital = hospital_result.record

    # 1. Document summary collection
    doc_rows_html = []
    if available_documents:
        for doc in available_documents:
            doc_rows_html.append(
                f"""<tr>
                    <td><strong>{_esc(doc.filename)}</strong></td>
                    <td><code>{_esc(doc.document_id)}</code></td>
                    <td>{_esc(doc.version)}</td>
                    <td><span class="badge badge-default">{_esc(doc.extraction_status)}</span></td>
                    <td>{_esc(doc.page_count)} pages</td>
                </tr>"""
            )
    else:
        # Collect distinct document references from evidence citations
        cited_docs: dict[tuple[str, str], set[int]] = {}
        for f in packet.findings:
            for ev in f.evidence:
                key = (ev.document_id, ev.document_version)
                cited_docs.setdefault(key, set()).add(ev.page)
        for rev in packet.revisions:
            for ev in rev.triggering_evidence:
                key = (ev.document_id, ev.document_version)
                cited_docs.setdefault(key, set()).add(ev.page)

        if cited_docs:
            for (doc_id, doc_ver), pages in cited_docs.items():
                page_str = ", ".join(f"p.{p}" for p in sorted(pages))
                doc_rows_html.append(
                    f"""<tr>
                        <td><code>{_esc(doc_id)}</code></td>
                        <td><code>{_esc(doc_id)}</code></td>
                        <td>{_esc(doc_ver)}</td>
                        <td><span class="badge badge-default">active</span></td>
                        <td>Cited: {page_str}</td>
                    </tr>"""
                )
        else:
            doc_rows_html.append(
                "<tr><td colspan='5' style='color: #64748b; font-style: italic;'>No documents cited in this packet.</td></tr>"
            )

    docs_table_body = "\n".join(doc_rows_html)

    # 2. Findings cards
    findings_html_list = []
    for f in packet.findings:
        evidence_html_list = []
        if f.evidence:
            for ev in f.evidence:
                evidence_html_list.append(
                    f"""<div class="evidence-box">
                        <div class="evidence-meta">
                            <strong>Document:</strong> <code>{_esc(ev.document_id)}</code> &bull;
                            <strong>Version:</strong> {_esc(ev.document_version)} &bull;
                            <strong>Physical Page:</strong> Page {_esc(ev.page)}
                            {f'&bull; <span class="badge badge-default">{_esc(ev.evidence_type)}</span>' if ev.evidence_type else ''}
                        </div>
                        <blockquote class="evidence-quote">"{_esc(ev.quote)}"</blockquote>
                    </div>"""
                )
        else:
            evidence_html_list.append(
                "<p class='no-evidence-text'><em>No documentary evidence attached.</em></p>"
            )

        limitations_html = ""
        if f.limitations or f.missing_facts:
            items = [f"<li>{_esc(item)}</li>" for item in (f.limitations + f.missing_facts)]
            limitations_html = f"""
            <div class="limitations-block">
                <strong>Limitations & Missing Facts:</strong>
                <ul>{''.join(items)}</ul>
            </div>
            """

        status_class = _status_color_class(f.status)
        findings_html_list.append(
            f"""<div class="finding-card {status_class}">
                <div class="finding-header">
                    <div class="finding-title">
                        <span class="badge badge-rev">Rev {_esc(f.revision)}</span>
                        <strong>{_esc(f.topic)}</strong>
                    </div>
                    <span class="badge {status_class}">{_esc(f.status.upper())}</span>
                </div>
                <div class="finding-body">
                    <p class="finding-conclusion">{_esc(f.conclusion)}</p>
                    <div class="next-action-box">
                        <strong>Recommended Next Action:</strong> {_esc(f.next_action)}
                    </div>
                    {limitations_html}
                    <div class="evidence-section">
                        <h4>Supporting Evidence & Citations</h4>
                        {''.join(evidence_html_list)}
                    </div>
                </div>
            </div>"""
        )

    findings_content = "\n".join(findings_html_list) if findings_html_list else "<p><em>No findings recorded.</em></p>"

    # 3. Missing Evidence Checklist table
    checklist_rows = []
    for item in packet.missing_evidence_checklist:
        status_badge = "badge-unresolved" if item.status == "requested" else "badge-default"
        if item.status == "resolved":
            status_badge = "badge-supported"
        elif item.status == "user_does_not_have":
            status_badge = "badge-conflict"

        checklist_rows.append(
            f"""<tr>
                <td><strong>{_esc(item.requested_information)}</strong></td>
                <td>{_esc(item.why_it_matters)}</td>
                <td>{_esc(item.suggested_source or 'Caregiver / Hospital desk')}</td>
                <td><span class="badge {status_badge}">{_esc(item.status.replace('_', ' ').upper())}</span></td>
                <td>{_esc(item.resolution_note or '—')}</td>
            </tr>"""
        )

    checklist_table_body = (
        "\n".join(checklist_rows)
        if checklist_rows
        else "<tr><td colspan='5' style='color: #64748b;'>No outstanding checklist items.</td></tr>"
    )

    # 4. Questions for Hospital Desk / Insurer
    questions_list = []
    if packet.unresolved_questions:
        for q in packet.unresolved_questions:
            questions_list.append(f"<li>{_esc(q)}</li>")

    # Add questions derived from unresolved findings and checklist
    for item in packet.missing_evidence_checklist:
        if item.status == "requested":
            questions_list.append(
                f"<li><strong>Clarify with {item.suggested_source or 'admission desk'}:</strong> {_esc(item.requested_information)} — <em>{_esc(item.why_it_matters)}</em></li>"
            )

    questions_html = (
        f"<ul class='questions-list'>{''.join(questions_list)}</ul>"
        if questions_list
        else "<p style='color: #64748b; font-style: italic;'>No outstanding questions recorded.</p>"
    )

    # 5. Revisions History table
    revisions_rows = []
    for rev in packet.revisions:
        evidence_snippet = ""
        if rev.triggering_evidence:
            ev = rev.triggering_evidence[0]
            evidence_snippet = f"<code>{_esc(ev.document_id)}</code> p.{_esc(ev.page)}: \"{_esc(ev.quote[:90])}...\""

        revisions_rows.append(
            f"""<tr>
                <td><code>{_esc(rev.finding_id)}</code></td>
                <td>Rev {_esc(rev.old_finding_revision)} &rarr; <strong>Rev {_esc(rev.new_finding_revision)}</strong></td>
                <td>
                    <span class="badge {_status_color_class(rev.old_status)}">{_esc(rev.old_status)}</span> &rarr;
                    <span class="badge {_status_color_class(rev.new_status)}">{_esc(rev.new_status)}</span>
                </td>
                <td><span class="badge badge-default">{_esc(rev.trigger_type.replace('_', ' '))}</span></td>
                <td>{_esc(rev.reason)}</td>
                <td>{evidence_snippet or '—'}</td>
            </tr>"""
        )

    revisions_table_body = (
        "\n".join(revisions_rows)
        if revisions_rows
        else "<tr><td colspan='6' style='color: #64748b; font-style: italic;'>No historical revisions in this packet snapshot.</td></tr>"
    )

    # 6. Incomplete notice banner
    incomplete_banner_html = ""
    if packet.review_status != "complete" or packet.stopped_reason != "review_complete":
        stopped_label = _stopped_reason_label(packet.stopped_reason)
        details_text = f" ({_esc(packet.stop_details)})" if packet.stop_details else ""
        incomplete_banner_html = f"""
        <div class="banner banner-incomplete">
            <div class="banner-title">⚠️ INCOMPLETE REVIEW PACKET &bull; STOP REASON: {_esc(stopped_label).upper()}</div>
            <p>This review packet represents partial or bounded execution results{details_text}.
            Findings, checklist items, and limitations below reflect evidence reviewed prior to execution stop.
            Topics marked with pending reassessment notices require additional evidence or review execution before admission.</p>
        </div>
        """

    # 7. Hospital Information Card
    hospital_html = ""
    if active_hospital:
        limitations_items = "".join(f"<li>{_esc(lim)}</li>" for lim in active_hospital.limitations)
        hospital_html = f"""
        <div class="hospital-card matched">
            <div class="hospital-header">
                <div>
                    <span class="badge badge-synth">SYNTHETIC DEMONSTRATION DATA</span>
                    <h3 style="margin: 0.25rem 0 0.1rem 0;">{_esc(active_hospital.hospital_name)}</h3>
                    <div style="font-size: 0.85rem; color: #475569;">
                        City: <strong>{_esc(active_hospital.city)}</strong> &bull;
                        Record ID: <code>{_esc(active_hospital.record_id)}</code> &bull;
                        Dataset Version: <strong>{_esc(active_hospital.dataset_version)}</strong> ({_format_date(active_hospital.dataset_date)})
                    </div>
                </div>
                <div style="text-align: right;">
                    <span class="badge badge-tier">{_esc(active_hospital.network_tier.upper().replace('_', ' '))}</span>
                    <div style="font-size: 0.85rem; color: #475569; margin-top: 0.35rem;">
                        TPA Desk: {_esc(active_hospital.tpa_desk_contact or 'Not listed')}
                    </div>
                </div>
            </div>
            <div class="hospital-limitations">
                <strong>Demonstration Limitations & Invariants:</strong>
                <ul>{limitations_items}</ul>
            </div>
            <div class="hospital-disclaimer">
                <strong>Notice:</strong> Synthetic hospital directory match does NOT verify live insurer network agreement,
                cashless hospitalisation eligibility, or claim approval. Network status and cashless agreements must be
                confirmed directly with the hospital TPA desk and insurer.
            </div>
        </div>
        """
    elif hospital_result and hospital_result.status == "no_match":
        hospital_html = f"""
        <div class="hospital-card no-match">
            <div class="hospital-header">
                <div>
                    <span class="badge badge-conflict">NO DIRECTORY MATCH</span>
                    <h3 style="margin: 0.25rem 0 0.1rem 0;">{_esc(hospital_result.query or 'Unknown')}</h3>
                    <p style="margin: 0.25rem 0; font-size: 0.85rem; color: #64748b;">{_esc(hospital_result.message)}</p>
                </div>
                <div style="text-align: right; font-size: 0.8rem; color: #64748b;">
                    Dataset: {_esc(hospital_result.dataset_version)} ({_format_date(hospital_result.dataset_date)})
                </div>
            </div>
            <div class="hospital-disclaimer">
                <strong>Notice:</strong> No facility record matches the specified name in synthetic dataset.
                Confirm facility credentials directly with the hospital admission desk.
            </div>
        </div>
        """
    elif hospital_result and hospital_result.status == "ambiguous_match":
        candidate_names = ", ".join(f"'{c.hospital_name}'" for c in hospital_result.candidates[:3])
        hospital_html = f"""
        <div class="hospital-card ambiguous">
            <div class="hospital-header">
                <div>
                    <span class="badge badge-unresolved">AMBIGUOUS DIRECTORY MATCH</span>
                    <h3 style="margin: 0.25rem 0 0.1rem 0;">Multiple Matches for '{_esc(hospital_result.query)}'</h3>
                    <p style="margin: 0.25rem 0; font-size: 0.85rem; color: #64748b;">
                        {_esc(hospital_result.message)} Potential candidates include: {_esc(candidate_names)}.
                    </p>
                </div>
            </div>
            <div class="hospital-disclaimer">
                <strong>Notice:</strong> Please specify the exact hospital name in case details to obtain directory reference.
            </div>
        </div>
        """
    else:
        hospital_html = f"""
        <div class="hospital-card missing">
            <div class="hospital-header">
                <div>
                    <span class="badge badge-default">HOSPITAL NOT SPECIFIED</span>
                    <h3 style="margin: 0.25rem 0 0.1rem 0;">No Hospital Name Provided</h3>
                    <p style="margin: 0.25rem 0; font-size: 0.85rem; color: #64748b;">
                        Hospital facility is not recorded in case details. Add hospital name in Case Setup to view directory references.
                    </p>
                </div>
            </div>
            <div class="hospital-disclaimer">
                <strong>Notice:</strong> Synthetic hospital directory match does not verify live network status or insurer authorisation.
            </div>
        </div>
        """

    # 8. Complete HTML Template
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AdmitSense Review Packet — {_esc(case.case_id)} (v{_esc(packet.packet_version)})</title>
    <style>
        /* Modern, clean typography & layout */
        :root {{
            --primary: #1e40af;
            --primary-bg: #eff6ff;
            --text-main: #0f172a;
            --text-muted: #475569;
            --border-light: #e2e8f0;
            --surface: #ffffff;
            --surface-subtle: #f8fafc;
            --status-supported: #15803d;
            --status-supported-bg: #dcfce7;
            --status-unresolved: #c2410c;
            --status-unresolved-bg: #ffedd5;
            --status-conflict: #b91c1c;
            --status-conflict-bg: #fee2e2;
            --status-human: #7e22ce;
            --status-human-bg: #f3e8ff;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.5;
            color: var(--text-main);
            background-color: #f1f5f9;
            margin: 0;
            padding: 24px;
        }}

        .packet-container {{
            max-width: 960px;
            margin: 0 auto;
            background: var(--surface);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            padding: 36px 44px;
        }}

        /* Header */
        .app-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            border-bottom: 2px solid var(--border-light);
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .brand-title {{
            font-size: 1.75rem;
            font-weight: 800;
            color: var(--primary);
            letter-spacing: -0.025em;
            margin: 0;
        }}
        .brand-subtitle {{
            font-size: 0.9rem;
            color: var(--text-muted);
            margin: 4px 0 0 0;
        }}
        .packet-meta {{
            text-align: right;
            font-size: 0.85rem;
            color: var(--text-muted);
        }}
        .packet-meta strong {{
            color: var(--text-main);
        }}

        /* Mandatory Banners */
        .banner {{
            border-radius: 6px;
            padding: 14px 18px;
            margin-bottom: 20px;
            font-size: 0.9rem;
        }}
        .banner-title {{
            font-weight: 700;
            margin-bottom: 4px;
            text-transform: uppercase;
            font-size: 0.85rem;
            letter-spacing: 0.05em;
        }}
        .banner-auth {{
            background-color: #fffbeb;
            border: 2px solid #f59e0b;
            color: #92400e;
        }}
        .banner-auth .banner-title {{
            color: #b45309;
        }}
        .banner-incomplete {{
            background-color: #fef2f2;
            border: 2px solid #ef4444;
            color: #991b1b;
        }}
        .banner-incomplete .banner-title {{
            color: #dc2626;
        }}
        .banner-emergency {{
            background-color: #f8fafc;
            border-left: 4px solid #64748b;
            color: #334155;
            padding: 10px 14px;
            font-size: 0.85rem;
            margin-bottom: 24px;
        }}

        /* Section Headings */
        h2 {{
            font-size: 1.25rem;
            font-weight: 700;
            color: #1e293b;
            border-bottom: 1px solid var(--border-light);
            padding-bottom: 8px;
            margin-top: 32px;
            margin-bottom: 16px;
        }}
        h3 {{
            font-size: 1.05rem;
            font-weight: 600;
            margin: 0 0 8px 0;
        }}
        h4 {{
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-muted);
            margin: 12px 0 6px 0;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }}

        /* Summary Grid */
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            background-color: var(--surface-subtle);
            border: 1px solid var(--border-light);
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 24px;
        }}
        .summary-item label {{
            display: block;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 2px;
        }}
        .summary-item .value {{
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--text-main);
        }}

        /* Badges */
        .badge {{
            display: inline-block;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }}
        .badge-supported {{
            background-color: var(--status-supported-bg);
            color: var(--status-supported);
            border: 1px solid #86efac;
        }}
        .badge-unresolved {{
            background-color: var(--status-unresolved-bg);
            color: var(--status-unresolved);
            border: 1px solid #fdba74;
        }}
        .badge-conflict {{
            background-color: var(--status-conflict-bg);
            color: var(--status-conflict);
            border: 1px solid #fca5a5;
        }}
        .badge-human-review {{
            background-color: var(--status-human-bg);
            color: var(--status-human);
            border: 1px solid #d8b4fe;
        }}
        .badge-complete {{
            background-color: var(--status-supported-bg);
            color: var(--status-supported);
        }}
        .badge-incomplete {{
            background-color: var(--status-unresolved-bg);
            color: var(--status-unresolved);
        }}
        .badge-failed {{
            background-color: var(--status-conflict-bg);
            color: var(--status-conflict);
        }}
        .badge-default {{
            background-color: #e2e8f0;
            color: #475569;
        }}
        .badge-rev {{
            background-color: #0284c7;
            color: #ffffff;
            font-weight: 700;
            margin-right: 6px;
        }}
        .badge-synth {{
            background-color: #f3e8ff;
            color: #6b21a8;
            border: 1px solid #d8b4fe;
            font-size: 0.7rem;
            padding: 2px 6px;
        }}
        .badge-tier {{
            background-color: #e0f2fe;
            color: #0369a1;
            border: 1px solid #7dd3fc;
        }}

        /* Hospital Card */
        .hospital-card {{
            border-radius: 6px;
            padding: 16px 20px;
            margin-bottom: 24px;
            border: 1px solid var(--border-light);
            background-color: var(--surface);
        }}
        .hospital-card.matched {{
            border-left: 4px solid #8b5cf6;
            background-color: #faf5ff;
        }}
        .hospital-card.no-match {{
            border-left: 4px solid #ef4444;
            background-color: #fef2f2;
        }}
        .hospital-card.ambiguous {{
            border-left: 4px solid #f59e0b;
            background-color: #fffbeb;
        }}
        .hospital-card.missing {{
            border-left: 4px solid #94a3b8;
            background-color: var(--surface-subtle);
        }}
        .hospital-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 10px;
        }}
        .hospital-limitations {{
            font-size: 0.85rem;
            color: var(--text-muted);
            margin: 8px 0;
        }}
        .hospital-limitations ul {{
            margin: 4px 0 8px 20px;
            padding: 0;
        }}
        .hospital-disclaimer {{
            font-size: 0.8rem;
            color: #6b21a8;
            background-color: #f3e8ff;
            padding: 8px 12px;
            border-radius: 4px;
            margin-top: 10px;
        }}

        /* Findings */
        .finding-card {{
            border: 1px solid var(--border-light);
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 18px;
            background-color: var(--surface);
        }}
        .finding-card.badge-supported {{
            border-left: 5px solid var(--status-supported);
        }}
        .finding-card.badge-unresolved {{
            border-left: 5px solid var(--status-unresolved);
        }}
        .finding-card.badge-conflict {{
            border-left: 5px solid var(--status-conflict);
        }}
        .finding-card.badge-human-review {{
            border-left: 5px solid var(--status-human);
        }}
        .finding-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        .finding-title {{
            font-size: 1.05rem;
            font-weight: 700;
        }}
        .finding-conclusion {{
            font-size: 0.95rem;
            line-height: 1.5;
            margin: 0 0 12px 0;
        }}
        .next-action-box {{
            background-color: #f0fdf4;
            border: 1px solid #bbf7d0;
            color: #166534;
            padding: 10px 14px;
            border-radius: 4px;
            font-size: 0.85rem;
            margin-bottom: 12px;
        }}
        .limitations-block {{
            background-color: #fff7ed;
            border: 1px solid #ffedd5;
            color: #9a3412;
            padding: 10px 14px;
            border-radius: 4px;
            font-size: 0.85rem;
            margin-bottom: 12px;
        }}
        .limitations-block ul {{
            margin: 4px 0 0 20px;
            padding: 0;
        }}
        .evidence-box {{
            background-color: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 4px;
            padding: 10px 14px;
            margin-top: 8px;
            font-size: 0.85rem;
        }}
        .evidence-meta {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 6px;
        }}
        .evidence-quote {{
            margin: 0;
            padding: 4px 0 4px 12px;
            border-left: 3px solid #3b82f6;
            font-style: italic;
            color: #1e293b;
        }}

        /* Tables */
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            margin-bottom: 24px;
        }}
        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border-light);
        }}
        th {{
            background-color: var(--surface-subtle);
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.025em;
        }}
        tr:hover td {{
            background-color: #f8fafc;
        }}

        /* Questions List */
        .questions-list {{
            margin: 0;
            padding-left: 20px;
            font-size: 0.9rem;
            line-height: 1.6;
        }}
        .questions-list li {{
            margin-bottom: 8px;
        }}

        /* Footer */
        .packet-footer {{
            border-top: 1px solid var(--border-light);
            padding-top: 16px;
            margin-top: 40px;
            font-size: 0.75rem;
            color: #64748b;
            text-align: center;
        }}

        /* Print Stylesheet */
        @media print {{
            body {{
                background: #ffffff;
                padding: 0;
            }}
            .packet-container {{
                border: none;
                box-shadow: none;
                padding: 0;
                max-width: 100%;
            }}
            .banner, .finding-card, .hospital-card {{
                break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="packet-container">
        <!-- Application Brand & Metadata Header -->
        <div class="app-header">
            <div>
                <h1 class="brand-title">AdmitSense</h1>
                <p class="brand-subtitle">Caregiver Administrative Hospital Admission Review Packet</p>
            </div>
            <div class="packet-meta">
                <div>Packet ID: <strong><code>{_esc(packet.packet_id)}</code></strong></div>
                <div>Version: <strong>v{_esc(packet.packet_version)}</strong> &bull; Run: <code>{_esc(packet.run_id)}</code></div>
                <div>Generated: <strong>{_format_date(packet.generated_at)}</strong></div>
                <div style="margin-top: 4px;">Status: <span class="badge {_status_color_class(packet.review_status)}">{_esc(packet.review_status.upper())}</span></div>
            </div>
        </div>

        <!-- Incomplete Notice (if applicable) -->
        {incomplete_banner_html}

        <!-- Mandatory Insurer Authorisation Status Banner -->
        <div class="banner banner-auth">
            <div class="banner-title">INSURER AUTHORISATION STATUS: {_esc(packet.authorization_status.upper())}</div>
            <p style="margin: 4px 0 0 0;">
                <strong>Notice of Domain Boundary:</strong> AdmitSense assists administrative preparation for planned hospital
                admission. Findings in this packet describe condition evaluation against supplied documents; they do NOT
                establish overall insurance policy coverage, cashless hospitalisation approval, or insurer claim authorization.
                Final coverage must be verified directly with the hospital admission desk and insurer/TPA prior to admission.
            </p>
        </div>

        <!-- Emergency Care Disclaimer -->
        <div class="banner-emergency">
            <strong>Emergency Care Advisory:</strong> Emergency medical care should never be delayed for insurance administrative review or documentation preparation.
        </div>

        <!-- Case & Admission Summary -->
        <h2>1. Case & Admission Summary</h2>
        <div class="summary-grid">
            <div class="summary-item">
                <label>Patient / Member Name</label>
                <div class="value">{_esc(case.member_name or 'Not specified')}</div>
            </div>
            <div class="summary-item">
                <label>Policy Identifier</label>
                <div class="value"><code>{_esc(case.policy_id or 'Not specified')}</code></div>
            </div>
            <div class="summary-item">
                <label>Planned Procedure</label>
                <div class="value">{_esc(case.procedure or 'Not specified')}</div>
            </div>
            <div class="summary-item">
                <label>Planned Admission Date</label>
                <div class="value">{_format_date(case.planned_admission_date)}</div>
            </div>
            <div class="summary-item">
                <label>Continuous Coverage Start</label>
                <div class="value">{_format_date(case.continuous_coverage_start_date)}</div>
            </div>
            <div class="summary-item">
                <label>Estimated Admission Cost</label>
                <div class="value">{f"INR {_esc(f'{case.estimated_cost:,.2f}')}" if case.estimated_cost is not None else 'Not specified'}</div>
            </div>
        </div>

        <!-- Hospital Directory Reference (Synthetic) -->
        <h2>2. Hospital Directory Reference (Demonstration Data)</h2>
        {hospital_html}

        <!-- Documents Reviewed Table -->
        <h2>3. Documents Reviewed</h2>
        <table>
            <thead>
                <tr>
                    <th>Document</th>
                    <th>ID</th>
                    <th>Version</th>
                    <th>Extraction Status</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {docs_table_body}
            </tbody>
        </table>

        <!-- Findings & Administrative Review -->
        <h2>4. Administrative Findings & Condition Analysis</h2>
        {findings_content}

        <!-- Missing Evidence Checklist -->
        <h2>5. Missing Evidence & Clarification Checklist</h2>
        <table>
            <thead>
                <tr>
                    <th>Requested Information</th>
                    <th>Why It Matters</th>
                    <th>Suggested Source</th>
                    <th>Status</th>
                    <th>Resolution Note</th>
                </tr>
            </thead>
            <tbody>
                {checklist_table_body}
            </tbody>
        </table>

        <!-- Questions for Hospital Admission Desk / Insurer -->
        <h2>6. Questions for Hospital Desk & Insurer Staff</h2>
        {questions_html}

        <!-- Revision History & Change Traceability -->
        <h2>7. Evidence Change Replay & Revision Audit Trail</h2>
        <table>
            <thead>
                <tr>
                    <th>Finding ID</th>
                    <th>Revision</th>
                    <th>Status Transition</th>
                    <th>Trigger</th>
                    <th>Reason for Change</th>
                    <th>Triggering Citation</th>
                </tr>
            </thead>
            <tbody>
                {revisions_table_body}
            </tbody>
        </table>

        <!-- Footer -->
        <div class="packet-footer">
            <p>
                AdmitSense Review Packet Snapshot &bull; Packet ID: <code>{_esc(packet.packet_id)}</code> &bull; Version: {_esc(packet.packet_version)} &bull; Run ID: <code>{_esc(packet.run_id)}</code><br>
                Generated: {_format_date(packet.generated_at)} &bull; Deterministic export generated directly from saved SQLite database snapshot without model re-evaluation.
            </p>
        </div>
    </div>
</body>
</html>
"""
