from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _fmt(val: Any, suffix: str = "", decimals: int = 1) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.{decimals}f}{suffix}"
    return f"{val}{suffix}"


def build_sleep_doctor_pdf(report_data: Dict[str, Any]) -> bytes:
    """Render a clean 1-2 page clinical Sleep Doctor Summary PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="Sleep Therapy & Nocturnal Vitals Clinical Summary",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ClinicalTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "ClinicalSub",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=11.5,
        textColor=colors.HexColor("#0369a1"),
        spaceBefore=10,
        spaceAfter=6,
    )

    summary_7d = report_data.get("last_7_days_summary") or {}
    summary_30d = report_data.get("last_30_days_summary") or {}
    best_30 = report_data.get("best_30_summary") or {}
    nightly = report_data.get("nightly_rows") or []

    elements: List[Any] = []
    elements.append(
        Paragraph("Sleep Therapy &amp; Nocturnal Vitals Clinical Summary", title_style)
    )
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elements.append(
        Paragraph(
            f"Window Ending: <b>{report_data.get('window_end_date', '—')}</b> &nbsp;|&nbsp; "
            f"CPAP Start Date: <b>{report_data.get('cpap_start_date', '—')}</b> &nbsp;|&nbsp; "
            f"Device SN: <b>{report_data.get('device_sn', '—')}</b> &nbsp;|&nbsp; "
            f"Generated: {generated_at}",
            sub_style,
        )
    )

    # Summary Comparison Table: Past 7 Days vs Past 30 Days vs Best 30
    elements.append(Paragraph("Adherence &amp; Therapy Overview", section_style))
    overview_rows = [
        ["Metric", "Past 7 Days", "Past 30 Days", "Best 30 Window"],
        [
            "Compliance (>= 4h/night)",
            f"{_fmt(summary_7d.get('adherence_4h_pct'), '%')} ({summary_7d.get('days_ge_4h', '—')}/{summary_7d.get('calendar_days', 7)}d)",
            f"{_fmt(summary_30d.get('adherence_4h_pct'), '%')} ({summary_30d.get('days_ge_4h', '—')}/{summary_30d.get('calendar_days', 30)}d)",
            f"{_fmt(best_30.get('adherence_pct'), '%')} ({best_30.get('days_ge_4h', '—')}/30d)",
        ],
        [
            "Avg Usage (Days Used / All Days)",
            f"{_fmt(summary_7d.get('avg_hours_days_used'), 'h', 2)} / {_fmt(summary_7d.get('avg_hours_all_days'), 'h', 2)}",
            f"{_fmt(summary_30d.get('avg_hours_days_used'), 'h', 2)} / {_fmt(summary_30d.get('avg_hours_all_days'), 'h', 2)}",
            f"{_fmt(best_30.get('avg_hours_used'), 'h', 2)} ({best_30.get('start_date', '—')} to {best_30.get('end_date', '—')})",
        ],
        [
            "AHI / CAI (events/hr)",
            f"{_fmt(summary_7d.get('avg_ahi'), '', 2)} / {_fmt(summary_7d.get('avg_cai'), '', 2)}",
            f"{_fmt(summary_30d.get('avg_ahi'), '', 2)} / {_fmt(summary_30d.get('avg_cai'), '', 2)}",
            f"AHI {_fmt(best_30.get('avg_ahi'), '', 2)}",
        ],
        [
            "Pressure (Median / Avg P95 cmH2O)",
            f"{_fmt(summary_7d.get('median_pressure'), '', 1)} / {_fmt(summary_7d.get('avg_p95_pressure'), '', 1)}",
            f"{_fmt(summary_30d.get('median_pressure'), '', 1)} / {_fmt(summary_30d.get('avg_p95_pressure'), '', 1)}",
            "—",
        ],
        [
            "Avg Mask Leak (L/min)",
            _fmt(summary_7d.get('avg_leak'), " L/min", 1),
            _fmt(summary_30d.get('avg_leak'), " L/min", 1),
            "—",
        ],
        [
            "Google Health SpO2 (Avg / Min)",
            f"{_fmt(summary_7d.get('avg_spo2'), '%', 1)} / {_fmt(summary_7d.get('min_spo2'), '%', 1)}",
            f"{_fmt(summary_30d.get('avg_spo2'), '%', 1)} / {_fmt(summary_30d.get('min_spo2'), '%', 1)}",
            "—",
        ],
        [
            "Resting HR / HRV (RMSSD)",
            f"{_fmt(summary_7d.get('avg_rhr'), ' bpm', 1)} / {_fmt(summary_7d.get('avg_hrv'), ' ms', 1)}",
            f"{_fmt(summary_30d.get('avg_rhr'), ' bpm', 1)} / {_fmt(summary_30d.get('avg_hrv'), ' ms', 1)}",
            "—",
        ],
    ]
    overview_tbl = Table(
        overview_rows,
        colWidths=[2.3 * inch, 1.65 * inch, 1.65 * inch, 1.8 * inch],
    )
    overview_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(overview_tbl)
    elements.append(Spacer(1, 10))

    # Past 7 Days Nightly Breakdown
    elements.append(Paragraph("Past 7 Nights Detail (America/Los_Angeles Wake-Up Date)", section_style))
    nightly_header = [
        "Date",
        "CPAP Hrs",
        "P / P95",
        "AHI / CAI",
        "Leak",
        "Sleep Hrs",
        "Deep/REM%",
        "SpO2 Avg/Min",
        "RHR / HRV",
    ]
    nightly_table_data = [nightly_header]
    for r in nightly:
        nightly_table_data.append(
            [
                str(r.get("health_date", "—")),
                f"{_fmt(r.get('cpap_usage_hours'), 'h', 2)}",
                f"{_fmt(r.get('cpap_pressure'), '', 1)} / {_fmt(r.get('cpap_p95_pressure'), '', 1)}",
                f"{_fmt(r.get('cpap_ahi'), '', 1)} / {_fmt(r.get('cpap_cai'), '', 1)}",
                f"{_fmt(r.get('cpap_avg_leak'), '', 1)}",
                f"{_fmt(r.get('total_sleep_hours'), 'h', 2)}",
                f"{_fmt(r.get('deep_sleep_pct'), '%', 0)} / {_fmt(r.get('rem_sleep_pct'), '%', 0)}",
                f"{_fmt(r.get('spo2_avg_pct'), '%', 1)} / {_fmt(r.get('spo2_min_pct'), '%', 1)}",
                f"{_fmt(r.get('resting_heart_rate'), '', 0)} / {_fmt(r.get('hrv_rmssd_ms'), '', 0)}",
            ]
        )

    nightly_tbl = Table(
        nightly_table_data,
        colWidths=[
            0.88 * inch,
            0.72 * inch,
            0.76 * inch,
            0.78 * inch,
            0.55 * inch,
            0.72 * inch,
            0.85 * inch,
            1.1 * inch,
            1.04 * inch,
        ],
    )
    nightly_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0369a1")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(nightly_tbl)
    elements.append(Spacer(1, 10))
    elements.append(
        Paragraph(
            "Notes: CPAP metrics sourced from ReactHealth Sleep Therapy PDF reports; "
            "sleep architecture, SpO2, resting HR, and HRV RMSSD sourced from Google Health Takeout (Pixel Watch), "
            "aligned on America/Los_Angeles wake-up calendar dates.",
            sub_style,
        )
    )

    doc.build(elements)
    return buf.getvalue()
