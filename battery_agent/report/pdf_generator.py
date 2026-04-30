"""
PDF report generator using ReportLab Platypus.

Accepts the final assembled report dict from the orchestrator and returns PDF bytes.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Colour palette
DARK_BLUE = colors.HexColor("#1a3a5c")
MID_BLUE = colors.HexColor("#2e6da4")
LIGHT_BLUE = colors.HexColor("#d6e4f0")
ACCENT_GREEN = colors.HexColor("#27ae60")
ACCENT_RED = colors.HexColor("#c0392b")
LIGHT_GREY = colors.HexColor("#f5f5f5")
MID_GREY = colors.HexColor("#cccccc")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Normal"],
            fontSize=20,
            textColor=DARK_BLUE,
            fontName="Helvetica-Bold",
            spaceAfter=4,
            alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontSize=11,
            textColor=MID_BLUE,
            fontName="Helvetica",
            spaceAfter=2,
            alignment=TA_CENTER,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Normal"],
            fontSize=13,
            textColor=DARK_BLUE,
            fontName="Helvetica-Bold",
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.black,
            fontName="Helvetica",
            spaceAfter=4,
            leading=14,
        ),
        "label": ParagraphStyle(
            "Label",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.grey,
            fontName="Helvetica-Bold",
        ),
        "rec_title": ParagraphStyle(
            "RecTitle",
            parent=base["Normal"],
            fontSize=11,
            textColor=MID_BLUE,
            fontName="Helvetica-Bold",
            spaceAfter=3,
        ),
        "rec_body": ParagraphStyle(
            "RecBody",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.black,
            fontName="Helvetica",
            spaceAfter=3,
            leading=13,
        ),
    }


def _hr(color=MID_GREY) -> HRFlowable:
    return HRFlowable(width="100%", thickness=1, color=color, spaceAfter=8)


def _table_style_base() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
            ("GRID", (0, 0), (-1, -1), 0.5, MID_GREY),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]
    )


def generate_pdf(report: dict) -> bytes:
    """
    Generate a PDF report from the assembled report dict.

    Args:
        report: Dict with keys: metadata, data_manifest, analysis, recommendations,
                revenue_summary, gap_drivers, dispatch_comparison, soc_analysis.

    Returns:
        PDF file as bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    s = _styles()
    story = []

    # -------------------------------------------------------------------------
    # Title block
    # -------------------------------------------------------------------------
    metadata = report.get("metadata", {})
    battery_id = metadata.get("battery_id", "Battery Storage")
    analysis_date = metadata.get("analysis_date", datetime.now().strftime("%Y-%m-%d"))
    run_timestamp = metadata.get("run_timestamp", datetime.now().isoformat(timespec="seconds"))

    story.append(Paragraph("Battery Storage Performance Analysis", s["title"]))
    story.append(Paragraph(f"{battery_id} — {analysis_date}", s["subtitle"]))
    story.append(Paragraph(f"Report generated: {run_timestamp}", s["label"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(_hr(DARK_BLUE))

    # -------------------------------------------------------------------------
    # Executive Summary
    # -------------------------------------------------------------------------
    story.append(Paragraph("Executive Summary", s["section"]))

    rev_summary = report.get("revenue_summary", {})
    gap_drivers = report.get("gap_drivers", {})

    hist_rev = rev_summary.get("historical_cleared_total_revenue")
    perf_rev = rev_summary.get("perfect_cleared_total_revenue")
    gap_dollars = rev_summary.get("gap_dollars")
    gap_pct = rev_summary.get("gap_pct")

    def _fmt_dollar(v):
        if v is None:
            return "N/A"
        return f"${v:,.2f}"

    def _fmt_pct(v):
        if v is None:
            return "N/A"
        return f"{v:.1f}%"

    exec_text = (
        f"Historical operation achieved <b>{_fmt_dollar(hist_rev)}</b> in cleared revenue "
        f"against a perfect-foresight benchmark of <b>{_fmt_dollar(perf_rev)}</b>, "
        f"leaving a performance gap of <b>{_fmt_dollar(gap_dollars)} ({_fmt_pct(gap_pct)})</b>. "
    )

    primary = gap_drivers.get("primary_driver", {})
    secondary = gap_drivers.get("secondary_driver", {})

    if primary:
        exec_text += (
            f"The primary driver is <b>{primary.get('factor', '').replace('_', ' ')}</b>"
        )
        if primary.get("revenue_impact_dollars") is not None:
            exec_text += f" (${primary['revenue_impact_dollars']:,.2f} impact)"
        exec_text += ". "

    if secondary:
        exec_text += (
            f"A secondary contributing factor is <b>{secondary.get('factor', '').replace('_', ' ')}</b>."
        )

    story.append(Paragraph(exec_text, s["body"]))
    story.append(Spacer(1, 0.1 * inch))

    # -------------------------------------------------------------------------
    # Revenue Summary Table
    # -------------------------------------------------------------------------
    story.append(Paragraph("Revenue by Scenario / Schedule", s["section"]))

    by_combo = rev_summary.get("by_combo", {})
    tbl_data = [["Scenario", "Schedule", "Revenue ($)", "Avg Price ($/MWh)", "Intervals"]]
    for combo_key in sorted(by_combo.keys()):
        row_data = by_combo[combo_key]
        parts = combo_key.split("/", 1)
        scenario = parts[0].capitalize() if parts else combo_key
        schedule = parts[1].capitalize() if len(parts) > 1 else ""
        tbl_data.append([
            scenario,
            schedule,
            f"${row_data.get('total_revenue', 0):,.2f}",
            f"${row_data.get('avg_price', 0):,.4f}",
            str(row_data.get("intervals", 0)),
        ])

    # Gap row
    tbl_data.append([
        "GAP (Perfect − Historical)",
        "Cleared",
        _fmt_dollar(gap_dollars),
        "",
        "",
    ])

    tbl = Table(tbl_data, colWidths=[1.8 * inch, 1.2 * inch, 1.2 * inch, 1.4 * inch, 0.8 * inch])
    style = _table_style_base()
    # Highlight gap row
    gap_row_idx = len(tbl_data) - 1
    style.add("BACKGROUND", (0, gap_row_idx), (-1, gap_row_idx), LIGHT_BLUE)
    style.add("FONTNAME", (0, gap_row_idx), (-1, gap_row_idx), "Helvetica-Bold")
    style.add("TEXTCOLOR", (0, gap_row_idx), (0, gap_row_idx), ACCENT_RED)
    tbl.setStyle(style)
    story.append(tbl)
    story.append(Spacer(1, 0.1 * inch))

    # -------------------------------------------------------------------------
    # Dispatch Comparison
    # -------------------------------------------------------------------------
    dispatch = report.get("dispatch_comparison", {})
    if dispatch:
        story.append(Paragraph("Dispatch Comparison: Historical vs Perfect", s["section"]))

        dc_data = [
            ["Metric", "Historical/Cleared", "Perfect/Cleared", "Difference"],
            [
                "Total Charge (MWh)",
                f"{dispatch.get('total_charge_hist_MWh', 0):,.4f}",
                f"{dispatch.get('total_charge_perf_MWh', 0):,.4f}",
                f"{dispatch.get('charge_diff_MWh', 0):+,.4f}",
            ],
            [
                "Total Discharge (MWh)",
                f"{dispatch.get('total_discharge_hist_MWh', 0):,.4f}",
                f"{dispatch.get('total_discharge_perf_MWh', 0):,.4f}",
                f"{dispatch.get('discharge_diff_MWh', 0):+,.4f}",
            ],
            [
                "Missed Discharge Intervals",
                "—",
                "—",
                str(dispatch.get("missed_discharge_intervals", 0)),
            ],
            [
                "Unnecessary Charge Intervals",
                "—",
                "—",
                str(dispatch.get("unnecessary_charge_intervals", 0)),
            ],
            [
                "Missed Discharge Revenue",
                "—",
                "—",
                _fmt_dollar(dispatch.get("missed_discharge_revenue")),
            ],
        ]

        dc_tbl = Table(dc_data, colWidths=[2.2 * inch, 1.5 * inch, 1.5 * inch, 1.2 * inch])
        dc_tbl.setStyle(_table_style_base())
        story.append(dc_tbl)
        story.append(Spacer(1, 0.1 * inch))

    # -------------------------------------------------------------------------
    # SOC Analysis
    # -------------------------------------------------------------------------
    soc = report.get("soc_analysis", {})
    if soc:
        story.append(Paragraph("State of Charge (SOC) Analysis", s["section"]))

        hist_soc = soc.get("historical_cleared_soc", {})
        perf_soc = soc.get("perfect_cleared_soc", {})

        soc_data = [
            ["SOC Metric", "Historical/Cleared", "Perfect/Cleared"],
            ["Minimum SOC (%)", f"{hist_soc.get('min', 'N/A')}", f"{perf_soc.get('min', 'N/A')}"],
            ["Maximum SOC (%)", f"{hist_soc.get('max', 'N/A')}", f"{perf_soc.get('max', 'N/A')}"],
            ["Mean SOC (%)", f"{hist_soc.get('mean', 'N/A')}", f"{perf_soc.get('mean', 'N/A')}"],
            ["% Time Below 20%", f"{hist_soc.get('pct_time_below_20', 'N/A')}", f"{perf_soc.get('pct_time_below_20', 'N/A')}"],
            ["% Time Above 80%", f"{hist_soc.get('pct_time_above_80', 'N/A')}", f"{perf_soc.get('pct_time_above_80', 'N/A')}"],
            [
                "SOC-constrained discharge intervals",
                str(soc.get("soc_constrained_discharge_intervals", 0)),
                "—",
            ],
        ]

        soc_tbl = Table(soc_data, colWidths=[2.8 * inch, 2.0 * inch, 2.0 * inch])
        soc_tbl.setStyle(_table_style_base())
        story.append(soc_tbl)
        story.append(Spacer(1, 0.1 * inch))

    # -------------------------------------------------------------------------
    # Gap Driver Analysis
    # -------------------------------------------------------------------------
    story.append(Paragraph("Performance Gap — Root Cause Analysis", s["section"]))

    if primary:
        story.append(Paragraph("Primary Driver", s["rec_title"]))
        story.append(Paragraph(
            f"<b>{primary.get('factor', '').replace('_', ' ').title()}</b>: "
            f"{primary.get('evidence', '')}",
            s["body"],
        ))

    if secondary:
        story.append(Paragraph("Secondary Driver", s["rec_title"]))
        story.append(Paragraph(
            f"<b>{secondary.get('factor', '').replace('_', ' ').title()}</b>: "
            f"{secondary.get('evidence', '')}",
            s["body"],
        ))

    summary_text = gap_drivers.get("summary", "")
    if summary_text:
        story.append(Spacer(1, 0.05 * inch))
        story.append(Paragraph(summary_text, s["body"]))

    story.append(Spacer(1, 0.1 * inch))

    # -------------------------------------------------------------------------
    # Recommendations
    # -------------------------------------------------------------------------
    story.append(Paragraph("Actionable Recommendations", s["section"]))
    story.append(_hr(MID_BLUE))

    recs_data = report.get("recommendations", {})
    recs = recs_data.get("recommendations", []) if isinstance(recs_data, dict) else []

    if not recs:
        story.append(Paragraph("No validated recommendations available.", s["body"]))
    else:
        for i, rec in enumerate(recs):
            story.append(Paragraph(f"Recommendation {i + 1}", s["rec_title"]))

            rec_tbl_data = [
                ["Field", "Detail"],
                ["Action", rec.get("action", "")],
                ["Reasoning", rec.get("reasoning", "")],
                ["Expected Benefit", rec.get("expected_benefit", "")],
                ["Tradeoff", rec.get("tradeoff", "")],
            ]

            rec_tbl = Table(rec_tbl_data, colWidths=[1.4 * inch, 5.2 * inch])
            rec_style = _table_style_base()
            rec_style.add("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold")
            rec_style.add("BACKGROUND", (0, 1), (0, -1), LIGHT_BLUE)
            rec_style.add("ALIGN", (0, 0), (-1, -1), "LEFT")
            rec_style.add("VALIGN", (0, 0), (-1, -1), "TOP")
            rec_tbl.setStyle(rec_style)
            story.append(rec_tbl)
            story.append(Spacer(1, 0.1 * inch))

    # -------------------------------------------------------------------------
    # Footer note
    # -------------------------------------------------------------------------
    story.append(_hr())
    story.append(Paragraph(
        "This report was generated by the Battery Performance Analysis Agent. "
        "All findings are grounded in quantitative tool outputs from the loaded dataset. "
        "No recommendations were generated without supporting evidence.",
        ParagraphStyle("Footer", parent=_styles()["label"], fontSize=8, textColor=colors.grey),
    ))

    doc.build(story)
    return buf.getvalue()
