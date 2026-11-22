"""Build a Word draft of the v2 results chapter with tables and figures."""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figures"
OUT = ROOT / "docs" / "RESULTS_CHAPTER.docx"

doc = Document()
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(11)


def para(text: str, bold: bool = False, italic: bool = False) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic


def bullet(text: str) -> None:
    doc.add_paragraph(text, style="List Bullet")


def table(caption: str, headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
    p = doc.add_paragraph()
    r = p.add_run(caption)
    r.bold = True
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for pp in hdr[i].paragraphs:
            for rr in pp.runs:
                rr.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph()


def figure(filename: str, caption: str, width: float = 6.2) -> None:
    path = FIG / filename
    if path.exists():
        doc.add_picture(str(path), width=Inches(width))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        p = doc.add_paragraph()
        r = p.add_run(caption)
        r.italic = True
        r.font.size = Pt(9)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        para(f"[missing figure: {filename}]")


doc.add_heading("Results and Discussion", level=1)
para(
    "This chapter reports the evaluation of the v2 direct multi-horizon forecasting "
    "pipeline for the six Zambian security-wing sites. All numbers are generated "
    "from config/v2/metrics_horizons_combined.csv.",
    italic=True,
)

doc.add_heading("4.1 Evaluation protocol", level=2)
para(
    "The simulation contains 17,544 hourly observations per site (2024-01-01 to "
    "2025-12-31), driven by real Open-Meteo weather. Observed-load missingness is "
    "1.6-2.5% per site; the maximum gap is 7-23 h. The six sites are security-wing "
    "facilities assumed exempt from scheduled ZESCO load shedding. Unscheduled "
    "grid faults with generator backup are included and tracked separately."
)
para(
    "A forecast origin is the last observed hour. For horizon h, the target is load "
    "at origin + h. The evaluated horizons are 1, 6, 24 and 48 hours. The model is "
    "direct, not recursive."
)

table(
    "Table 4.1 - Chronological splits",
    ["Split", "Period", "Purpose"],
    [
        ["Training", "2024-01-01 - 2024-12-31", "Stage-1 fitting and OOF residuals"],
        ["Validation calibration", "2025-01-01 - 2025-03-31", "Fit residual shrinkage"],
        ["Validation selection", "2025-04-01 - 2025-06-30", "Choose XGB, LSTM or HGB"],
        ["Test", "2025-07-01 - 2025-12-31", "Final evaluation, used once"],
    ],
    widths=[1.3, 2.0, 2.6],
)
para(
    "Stage-2 residuals are out-of-fold: three expanding-window folds inside 2024 "
    "(Jan-Mar predicts Apr-Jun; Jan-Jun predicts Jul-Sep; Jan-Sep predicts Oct-Dec). "
    "Rows with missing or imputed targets are excluded from training and metrics. "
    "The common test set contains 4,075-4,231 observations per site/horizon."
)
para(
    "The comparison includes persistence, seasonal-naive 24 h and 168 h, standalone "
    "XGBoost, standalone LSTM, XGBoost + residual LSTM, XGBoost + residual HGB, and "
    "the validation-selected hybrid, plus readiness/weather ablations. Metrics are "
    "RMSE, MAE, MAPE, overall bias, top-decile peak bias/MAE, grid-fault MAE and "
    "per-readiness MAE."
)

doc.add_heading("4.2 Overall performance", level=2)
table(
    "Table 4.2 - Mean RMSE across the six sites (kW)",
    ["Horizon", "XGB", "Selected hybrid", "HGB residual", "LSTM residual", "Standalone LSTM", "Persistence"],
    [
        ["1 h", "53.3", "50.8", "50.3", "52.0", "92.6", "114.5"],
        ["6 h", "68.6", "62.2", "61.8", "67.6", "95.2", "352.5"],
        ["24 h", "74.2", "70.1", "69.4", "75.3", "97.8", "252.8"],
        ["48 h", "78.8", "75.3", "75.0", "81.0", "98.5", "334.6"],
    ],
    widths=[0.7, 0.8, 1.1, 1.0, 1.0, 1.2, 1.0],
)
figure("fig_mean_rmse_by_horizon.png", "Figure 4.1 - Mean RMSE by forecast horizon.")
para(
    "The selected hybrid reduces mean RMSE by 4.7%, 9.3%, 5.5% and 4.4% at 1, 6, "
    "24 and 48 h respectively. The mean MAE improvement is much smaller:"
)
table(
    "Table 4.3 - Mean MAE across the six sites (kW)",
    ["Horizon", "XGB", "Selected hybrid", "HGB residual", "LSTM residual", "Standalone LSTM"],
    [
        ["1 h", "35.6", "35.4", "35.3", "35.5", "61.0"],
        ["6 h", "42.6", "42.0", "42.1", "43.9", "63.4"],
        ["24 h", "47.4", "47.2", "47.2", "49.7", "65.9"],
        ["48 h", "51.8", "51.9", "51.8", "55.6", "67.1"],
    ],
    widths=[0.7, 0.9, 1.1, 1.1, 1.1, 1.2],
)
figure("fig_mean_mae_by_horizon.png", "Figure 4.2 - Mean MAE by forecast horizon.")
para(
    "At 48 h the selected hybrid is marginally worse than XGB on MAE (+0.1 kW) "
    "despite a lower RMSE; the improvement is concentrated in the largest errors "
    "and peak hours."
)

doc.add_heading("4.3 Per-site behaviour", level=2)
table(
    "Table 4.4 - Selected hybrid minus XGB RMSE (kW); negative is improvement",
    ["Site", "1 h", "6 h", "24 h", "48 h"],
    [
        ["Arakan", "-0.9", "-10.2", "-5.4", "0.0"],
        ["Kohima", "-14.5", "-28.4", "-18.9", "-20.8"],
        ["Makeni", "0.0", "0.0", "0.0", "0.0"],
        ["Mikango", "0.0", "0.0", "+0.1", "+0.2"],
        ["Peter Zuze", "+0.2", "-0.0", "-0.4", "0.0"],
        ["Tug Argan", "0.0", "0.0", "+0.1", "0.0"],
    ],
    widths=[1.2, 0.8, 0.8, 0.8, 0.8],
)
figure("fig_hybrid_delta_heatmap.png", "Figure 4.3 - Hybrid minus XGB RMSE (kW).")
figure("fig_per_site_rmse.png", "Figure 4.4 - XGBoost versus selected hybrid by site.")
para(
    "The gain is concentrated at Kohima (14-28 kW RMSE reduction) and, to a lesser "
    "extent, Arakan (up to 10 kW). Makeni and Mikango mostly gate to plain XGBoost; "
    "Tug Argan is essentially unchanged; Peter Zuze is mixed. Kohima and Arakan have "
    "larger readiness/weather-driven variability, while Makeni/Mikango have lower, "
    "more rigid load."
)

doc.add_heading("4.4 Peak-demand performance", level=2)
table(
    "Table 4.5 - Top-decile peak bias (kW); positive = under-prediction",
    ["Horizon", "XGB", "Selected hybrid", "HGB residual", "LSTM residual", "Standalone LSTM"],
    [
        ["1 h", "49.1", "29.1", "26.6", "36.9", "101.6"],
        ["6 h", "79.1", "49.2", "44.0", "62.1", "105.5"],
        ["24 h", "84.0", "62.7", "59.7", "68.2", "120.4"],
        ["48 h", "89.5", "68.1", "66.6", "64.3", "117.8"],
    ],
    widths=[0.7, 0.9, 1.1, 1.1, 1.1, 1.2],
)
figure("fig_peak_bias_by_horizon.png", "Figure 4.5 - Top-decile peak bias by horizon.")
para(
    "Peak bias falls by roughly 20-30 kW for the selected hybrid, and by more for "
    "the HGB candidate. This matters for maximum-demand charges, peak shaving and "
    "generator dispatch, even where MAE changes little. The standalone LSTM "
    "under-predicts peaks by 100-120 kW."
)

doc.add_heading("4.5 Ablations: readiness and weather", level=2)
table(
    "Table 4.6 - Mean RMSE by ablation (kW)",
    ["Horizon", "XGB", "No readiness", "No weather", "Core (history + calendar)"],
    [
        ["1 h", "53.3", "68.0", "61.0", "72.4"],
        ["6 h", "68.6", "115.0", "90.8", "127.3"],
        ["24 h", "74.2", "141.3", "86.5", "149.1"],
        ["48 h", "78.8", "151.7", "92.3", "159.6"],
    ],
    widths=[0.8, 0.9, 1.1, 1.0, 1.8],
)
figure("fig_ablation_rmse.png", "Figure 4.6 - Ablation of readiness and weather features.")
para(
    "Removing readiness increases RMSE by 28%, 68%, 90% and 92% at 1, 6, 24 and 48 h. "
    "This is the circularity risk identified in the proposal: the synthetic readiness "
    "signal directly drives the simulated load, so a large part of the apparent "
    "accuracy depends on a feature that would be a scheduled input in a real "
    "deployment. Removing weather increases RMSE by 14-32%, so weather adds value, "
    "but readiness dominates."
)

doc.add_heading("4.6 Stage 2 selection: HGB versus LSTM", level=2)
table(
    "Table 4.7 - Validation-selected Stage 2 counts",
    ["Horizon", "XGB", "HGB", "LSTM"],
    [
        ["1 h", "3", "3", "0"],
        ["6 h", "3", "3", "0"],
        ["24 h", "1", "3", "2"],
        ["48 h", "4", "1", "1"],
        ["Total", "11", "10", "3"],
    ],
    widths=[0.9, 0.8, 0.8, 0.8],
)
figure("fig_selection_counts.png", "Figure 4.7 - Validation-selected Stage 2.")
para(
    "The LSTM was selected at Mikango h=24/h=48 and Tug Argan h=24. In all three "
    "cases its test RMSE was 0.1-0.2 kW worse than XGB, and its correction was "
    "nearly constant. Post-hoc comparison shows that HGB was the best test model "
    "at 22 of 24 site/horizon combinations. The LSTM tied XGB at Peter Zuze h=1 "
    "(70.7 kW) and was never uniquely best; plain XGB was best at Tug Argan h=6."
)
para(
    "This is a validation-test shift, not a coding error. The 0.5% margin is "
    "deliberately conservative and misses some small HGB gains. For example, at "
    "Mikango h=24 the HGB improved validation RMSE by only 0.1% (below the gate), "
    "but its test RMSE was 45.2 kW versus 45.7 kW for XGB. Lowering the margin "
    "after seeing the test set would be test-set tuning, so it is not done here. "
    "For a prospective deployment, a lower HGB margin (e.g. 0.1%) combined with a "
    "non-degenerate-variance/correlation gate for the LSTM is recommended."
)
para(
    "The practical conclusion is that the residual signal in this simulation is "
    "tabular rather than sequential. A feature-vector HGB captures it better than "
    "a 168-hour LSTM. The LSTM is retained as the proposed architecture and as an "
    "ablation, but it is not the strongest Stage 2."
)

doc.add_heading("4.7 Standalone LSTM baseline", level=2)
para(
    "The standalone LSTM was trained on the same features, splits and 168-hour "
    "sequences with a 20-epoch budget on a Colab T4 GPU. Its mean RMSE is 92.6 / "
    "95.2 / 97.8 / 98.5 kW at 1/6/24/48 h, and its peak bias is 101.6 / 105.5 / "
    "120.4 / 117.8 kW. It is substantially weaker than XGBoost and the hybrid, and "
    "is reported as the required standalone baseline rather than a production model."
)

doc.add_heading("4.8 Discussion", level=2)
para(
    "First, the hybrid is most useful where the load is volatile. Kohima gains "
    "14-28 kW RMSE and Arakan up to 10 kW, with large peak-bias reductions; Makeni "
    "and Mikango do not. "
    "The high-variance sites have more readiness/weather-driven excursions, leaving "
    "more structured residual for Stage 2."
)
para(
    "Second, peak bias is a better indicator of operational value than MAE. The "
    "selected hybrid reduces top-decile bias from 49-90 kW to 29-68 kW, while MAE "
    "improves by only 0.1-0.6 kW. For peak-demand charges and generator dispatch, "
    "the peak metric is the more relevant one."
)
para(
    "Third, the LSTM is not the best residual learner on this data. HGB dominates "
    "at 22 of 24 combinations. This does not invalidate the hybrid framework; it "
    "changes the recommended Stage 2. The contribution can be framed as a "
    "validation-gated hybrid with candidate residual learners, of which the tabular "
    "HGB is strongest. The readiness ablation also shows that the synthetic activity "
    "signal is a major driver; the reported accuracy is a simulation result, not a "
    "validation on real defence telemetry."
)

doc.add_heading("4.9 Limitations", level=2)
for text in [
    "The demand series is synthetic; results demonstrate methodology, not real Zambian defence-load accuracy.",
    "The synthetic readiness schedule directly drives load, so the readiness ablation is essential and accuracy is partly circular.",
    "Weather forecasts are represented by archived observations plus an AR(1) forecast-error proxy, not an operational NWP product.",
    "Only 1-48 h hourly horizons are implemented; medium-term daily/weekly forecasts are future work.",
    "ARIMA is not yet implemented as a baseline.",
    "Peter Zuze and Tug Argan share one Open-Meteo grid cell and are not independent weather regimes.",
    "The validation gate is not infallible: LSTM selections at Mikango and Tug Argan were marginally worse on test.",
    "The test period is one six-month window; a rolling-origin evaluation over more years would be more robust.",
]:
    bullet(text)

doc.add_heading("4.10 Summary", level=2)
para(
    "The v2 pipeline produces a clean, reproducible simulation and a direct "
    "multi-horizon evaluation. The selected hybrid improves mean RMSE by 4.4-9.3% "
    "and reduces peak bias substantially, with gains concentrated at the "
    "high-variability sites. The HGB residual learner is stronger than the LSTM, and "
    "the LSTM is not competitive on this simulation. The readiness ablation nearly "
    "doubles RMSE at longer horizons, confirming the circularity caveat. These "
    "results support a validation-gated hybrid framework, but not an unconditional "
    "claim that XGBoost-LSTM is the best architecture for this data."
)

doc.save(OUT)
print(f"wrote {OUT}")
