"""Report generation for the AMAKA backend (v2 multi-horizon).

CSV export streams the horizon's replay rows for the selected range as-is.
PDF export renders a one-page executive report with reportlab platypus and
an embedded dark-themed matplotlib chart of actual vs hybrid load for that
horizon. Titles, filenames and period text carry the horizon (H1/H6/H24/H48).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from .store import (REPLAY_COLUMNS, count_alerts, get_site_horizon,
                    load_replay, window_mask)

log = logging.getLogger("amaka.reports")

# Palette mirrors the dashboard: near-black green-tinted, lime accent,
# amber warning, red critical.
CLR_BG = "#070a09"
CLR_PANEL = "#0c1210"
CLR_LINE = "#223029"
CLR_TEXT = "#dfe9e3"
CLR_DIM = "#7d8f86"
CLR_LIME = "#b7f34a"
CLR_AMBER = "#ffb020"
CLR_RED = "#ff5d5d"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def build_csv(site: str, start: Optional[pd.Timestamp],
              end: Optional[pd.Timestamp], horizon: int) -> str:
    """Replay columns for the selected range as CSV text (timestamps as in
    source). Uses the requested horizon's replay file."""
    df = load_replay(site, horizon)
    window = df[window_mask(df, start, end)].copy()
    out = io.StringIO()
    # Write timestamps exactly like the source replay file.
    window["timestamp"] = window["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    window.to_csv(out, index=False, columns=REPLAY_COLUMNS, lineterminator="\n")
    return out.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _chart_png(site: str, start: Optional[pd.Timestamp],
               end: Optional[pd.Timestamp], horizon: int) -> Optional[bytes]:
    """Dark-themed actual-vs-hybrid chart for one horizon as PNG bytes;
    None on failure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    df = load_replay(site, horizon)
    window = df[window_mask(df, start, end)]
    if window.empty:
        return None

    cfg = get_site_horizon(site, horizon)
    threshold = float(cfg["load"]["threshold_kw"])

    x = window["timestamp"].to_numpy()
    actual = window["actual_kw"].to_numpy(dtype=float)
    hybrid = window["hybrid_kw"].to_numpy(dtype=float)
    lower = window["lower_kw"].to_numpy(dtype=float)
    upper = window["upper_kw"].to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(7.2, 2.15), dpi=150)
    fig.patch.set_facecolor(CLR_BG)
    ax.set_facecolor(CLR_PANEL)

    ax.fill_between(x, lower, upper, color=CLR_LIME, alpha=0.10,
                    linewidth=0, label="95% forecast range")
    ax.plot(x, actual, color=CLR_TEXT, linewidth=0.9, label="Actual load")
    ax.plot(x, hybrid, color=CLR_LIME, linewidth=0.9, linestyle="--",
            label=f"H{horizon} forecast")
    ax.axhline(threshold, color=CLR_AMBER, linewidth=0.8, linestyle="--",
               label=f"Peak threshold {threshold:,.0f} kW")

    ax.tick_params(colors=CLR_DIM, labelsize=6.5, length=2)
    for spine in ax.spines.values():
        spine.set_color(CLR_LINE)
    ax.grid(True, color=CLR_LINE, linewidth=0.4, alpha=0.5)
    ax.set_ylabel("kW", color=CLR_DIM, fontsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    leg = ax.legend(loc="upper left", fontsize=6.2, ncol=4,
                    frameon=False, handlelength=1.6, columnspacing=1.0)
    for t in leg.get_texts():
        t.set_color(CLR_DIM)

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _fmt_zmw(v: float) -> str:
    return f"ZMW {v:,.0f}"


def build_pdf(site: str, start: Optional[pd.Timestamp],
              end: Optional[pd.Timestamp], horizon: int) -> bytes:
    """One-page executive PDF report for one forecast horizon. Falls back to
    a chart-less PDF if matplotlib fails. Always returns a valid PDF unless
    reportlab itself is broken."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                    PageTemplate, Paragraph, Spacer, Table,
                                    TableStyle)

    htag = f"H{horizon}"
    cfg = get_site_horizon(site, horizon)
    df = load_replay(site, horizon)
    window = df[window_mask(df, start, end)]
    if window.empty:
        raise ValueError("empty report range")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    period_from = window["timestamp"].iloc[0]
    period_to = window["timestamp"].iloc[-1]

    # ---- colors ----
    c_bg = colors.HexColor(CLR_BG)
    c_panel = colors.HexColor(CLR_PANEL)
    c_line = colors.HexColor(CLR_LINE)
    c_text = colors.HexColor(CLR_TEXT)
    c_dim = colors.HexColor(CLR_DIM)
    c_lime = colors.HexColor(CLR_LIME)
    c_amber = colors.HexColor(CLR_AMBER)
    c_red = colors.HexColor(CLR_RED)

    # ---- styles ----
    st_title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18,
                              textColor=c_text, leading=20, spaceAfter=0)
    st_sub = ParagraphStyle("s", fontName="Helvetica", fontSize=7.5,
                            textColor=c_lime, leading=10)
    st_h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=8,
                           textColor=c_lime, leading=10, spaceBefore=2,
                           spaceAfter=3)
    st_body = ParagraphStyle("b", fontName="Helvetica", fontSize=7.5,
                             textColor=c_text, leading=10)
    st_small = ParagraphStyle("sm", fontName="Helvetica", fontSize=6.5,
                              textColor=c_dim, leading=9)
    st_strip = ParagraphStyle("strip", fontName="Helvetica-Bold", fontSize=7.5,
                              textColor=colors.white, alignment=TA_CENTER,
                              leading=10)
    st_kpi_val = ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=10,
                                textColor=c_text, alignment=TA_CENTER,
                                leading=12)
    st_kpi_lab = ParagraphStyle("kl", fontName="Helvetica", fontSize=6,
                                textColor=c_dim, alignment=TA_CENTER,
                                leading=8)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=14 * mm, rightMargin=14 * mm,
                          topMargin=10 * mm, bottomMargin=10 * mm,
                          title=f"AMAKA — {cfg['label']} {htag} energy report",
                          author="AMAKA v0.1 PROTOTYPE")
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    avail_w = doc.width

    def page_bg(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(c_bg)
        canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        # classification strip across the top
        canvas.setFillColor(colors.HexColor("#3a0d0d"))
        canvas.rect(0, A4[1] - 9 * mm, A4[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(c_red)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawCentredString(A4[0] / 2, A4[1] - 6.2 * mm,
                                 "UNCLASSIFIED  //  SYNTHETIC DEMO DATA")
        # hairline under the strip
        canvas.setStrokeColor(c_lime)
        canvas.setLineWidth(0.6)
        canvas.line(0, A4[1] - 9 * mm, A4[0], A4[1] - 9 * mm)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="page", frames=[frame],
                                       onPage=page_bg)])

    story = []

    # ---- header ----
    header = Table(
        [[Paragraph("AMAKA", st_title),
          Paragraph(f"REPORT GENERATED {generated}<br/>REPLAY 2025 H2 · "
                    f"{htag} FORECAST · v2 PIPELINE",
                    ParagraphStyle("hr", fontName="Helvetica", fontSize=7,
                                   textColor=c_dim, alignment=2, leading=10))],
         [Paragraph("ENERGY COMMAND · AI LOAD FORECASTING", st_sub),
          Paragraph(f"PERIOD {period_from:%Y-%m-%d %H:%M} → {period_to:%Y-%m-%d %H:%M} · "
                    f"{htag} · {len(window):,} hourly rows",
                    ParagraphStyle("hr2", fontName="Helvetica", fontSize=7,
                                   textColor=c_dim, alignment=2, leading=10))]],
        colWidths=[avail_w * 0.55, avail_w * 0.45])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(Spacer(1, 3 * mm))
    story.append(header)
    story.append(Spacer(1, 2.5 * mm))

    # ---- site metadata ----
    story.append(Paragraph("SITE", st_h2))
    meta_rows = [
        ["Site", f"{cfg['label']} ({cfg['id']})", "Location", cfg["location"],
         "Type", cfg["type"]],
        ["Base load", f"{cfg['base_load_kw']:,} kW", "PV array",
         f"{cfg['pv_kwp']} kWp", "Headcount", f"{cfg['headcount']:,}"],
        ["Coordinates", f"{cfg['lat']:.3f}, {cfg['lon']:.3f}", "Floor area",
         f"{cfg['floor_area_m2']:,} m²", "Peak threshold",
         f"{cfg['load']['threshold_kw']:,.1f} kW"],
    ]
    meta = Table(meta_rows, colWidths=[avail_w * w for w in
                                       (0.11, 0.25, 0.11, 0.19, 0.13, 0.21)])
    meta.setStyle(TableStyle([
        ("TEXTCOLOR", (0, 0), (-1, -1), c_text),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica"),
        ("FONTNAME", (4, 0), (4, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("FONTNAME", (5, 0), (5, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("TEXTCOLOR", (0, 0), (0, -1), c_dim),
        ("TEXTCOLOR", (2, 0), (2, -1), c_dim),
        ("TEXTCOLOR", (4, 0), (4, -1), c_dim),
        ("BACKGROUND", (0, 0), (-1, -1), c_panel),
        ("GRID", (0, 0), (-1, -1), 0.4, c_line),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(meta)
    story.append(Spacer(1, 3 * mm))

    # ---- KPI table ----
    m = cfg["metrics"]
    load = cfg["load"]
    kpis = [
        ("FORECAST MAPE", f"{m['hyb_mape']:.2f} %"),
        ("FORECAST RMSE", f"{m['hyb_rmse']:,.1f} kW"),
        ("XGBOOST MAE", f"{m['xgb_mae']:,.1f} kW"),
        ("FORECAST MAE", f"{m['hyb_mae']:,.1f} kW"),
        ("TEST-PERIOD PEAK", f"{load['peak_kw']:,.0f} kW"),
        ("TEST-PERIOD AVERAGE", f"{load['avg_kw']:,.0f} kW"),
        ("PEAK THRESHOLD", f"{load['threshold_kw']:,.0f} kW"),
    ]
    kpi_data = [[Paragraph(k, st_kpi_lab) for k, _ in kpis],
                [Paragraph(v, st_kpi_val) for _, v in kpis]]
    cw = avail_w / len(kpis)
    kpi = Table(kpi_data, colWidths=[cw] * len(kpis))
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_panel),
        ("GRID", (0, 0), (-1, -1), 0.4, c_line),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(Paragraph(f"MODEL ACCURACY & LOAD · {htag} FORECAST", st_h2))
    story.append(kpi)
    story.append(Spacer(1, 3 * mm))

    # ---- chart (best-effort) ----
    try:
        png = _chart_png(site, start, end, horizon)
    except Exception as exc:  # pragma: no cover - defensive for live demo
        log.warning("chart generation failed for %s: %s", site, exc)
        png = None
    if png:
        story.append(Paragraph(f"ACTUAL VS {htag} FORECAST", st_h2))
        img = Image(io.BytesIO(png))
        img._restrictSize(avail_w, 56 * mm)
        story.append(img)
        story.append(Spacer(1, 3 * mm))

    # ---- alert counts ----
    counts = count_alerts(site, start, end, horizon)
    story.append(Paragraph("ALERTS IN PERIOD", st_h2))
    alert_data = [
        [Paragraph("PEAK THRESHOLD (CRITICAL)", st_kpi_lab),
         Paragraph("PEAK THRESHOLD (WARNING)", st_kpi_lab),
         Paragraph("HIGH READINESS HOURS", st_kpi_lab),
         Paragraph("OUTSIDE FORECAST RANGE", st_kpi_lab)],
        [Paragraph(f"{counts['peak_critical']}", ParagraphStyle(
            "a1", parent=st_kpi_val, textColor=c_red if counts['peak_critical'] else c_text)),
         Paragraph(f"{counts['peak_warning']}", ParagraphStyle(
            "a2", parent=st_kpi_val, textColor=c_amber if counts['peak_warning'] else c_text)),
         Paragraph(f"{counts['surge']}", ParagraphStyle(
            "a3", parent=st_kpi_val, textColor=c_text)),
         Paragraph(f"{counts['variance']}", ParagraphStyle(
            "a4", parent=st_kpi_val, textColor=c_text))],
    ]
    alerts_tbl = Table(alert_data, colWidths=[avail_w / 4] * 4)
    alerts_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_panel),
        ("GRID", (0, 0), (-1, -1), 0.4, c_line),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(alerts_tbl)
    story.append(Spacer(1, 3 * mm))

    # ---- savings ----
    cost = cfg["cost"]
    assump = load_config_cost()
    story.append(Paragraph("ESTIMATED SAVINGS", st_h2))
    sav_rows = [
        ["Baseline monthly bill", _fmt_zmw(cost["baseline_monthly_zmw"]),
         "Monthly saving", _fmt_zmw(cost["monthly_saving_zmw"])],
        ["Demand-charge saving", _fmt_zmw(cost["demand_saving_zmw"]),
         "Fuel-efficiency saving", _fmt_zmw(cost["fuel_saving_zmw"])],
        ["Annual saving", _fmt_zmw(cost["annual_saving_zmw"]),
         "Saving vs baseline", f"{cost['saving_pct']:.2f} %"],
    ]
    sav = Table(sav_rows, colWidths=[avail_w * w for w in (0.27, 0.23, 0.27, 0.23)])
    sav.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, -1), c_text),
        ("TEXTCOLOR", (3, 2), (3, 2), c_lime),
        ("TEXTCOLOR", (0, 0), (0, -1), c_dim),
        ("TEXTCOLOR", (2, 0), (2, -1), c_dim),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, -1), c_panel),
        ("GRID", (0, 0), (-1, -1), 0.4, c_line),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(sav)
    story.append(Spacer(1, 2 * mm))

    # ---- footer / assumptions ----
    assumptions = (
        f"Assumptions — tariff {assump.get('energy_tariff_zmw_kwh', 0)} ZMW/kWh · "
        f"demand charge {assump.get('demand_charge_zmw_kw_month', 0)} ZMW/kW/month · "
        f"diesel {assump.get('diesel_price_zmw_litre', 0)} ZMW/L at "
        f"{assump.get('generator_litres_per_kwh', 0)} L/kWh, generator share "
        f"{assump.get('generator_share_of_energy', 0):.0%} of energy · "
        f"peak shaving {assump.get('peak_shaving_fraction', 0):.0%} of peak · "
        f"gen-set efficiency gain {assump.get('fuel_efficiency_gain', 0):.0%} · "
        f"{assump.get('hours_per_month', 730)} h/month. "
        f"Baseline = {cfg['load']['avg_kw']:,.0f} kW average × hours × tariff + "
        f"{load['peak_kw']:,.0f} kW peak × demand charge."
    )
    story.append(Paragraph(assumptions, st_small))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        f"Forecast horizon: {htag} ({horizon} hours ahead) · "
        f"{get_model_cfg()['name']} · {get_model_cfg()['stage1']} · "
        f"{get_model_cfg()['stage2']}. "
        f"Data is synthetic and for demonstration only. "
        f"Built for ICT431 · Mulungushi University · Generated {generated}.",
        st_small))

    doc.build(story)
    return buf.getvalue()


def load_config_cost() -> dict:
    from .store import load_config
    return load_config().get("cost_assumptions", {})


def get_model_cfg() -> dict:
    from .store import load_config
    return load_config().get("model", {})
