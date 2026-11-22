"""
Generate figures for the v2 results chapter from the final metrics.

Usage:
    python src/v2_make_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from v2_config import MODELS

OUT = Path(__file__).resolve().parents[1] / "docs" / "figures"
METRICS = MODELS / "metrics_horizons_combined.csv"

HORIZONS = [1, 6, 24, 48]
MODEL_LABELS = {
    "xgb": "XGBoost",
    "hybrid": "Selected hybrid",
    "hybrid_hgb": "HGB residual",
    "hybrid_lstm": "LSTM residual",
    "standalone_lstm": "Standalone LSTM",
    "persistence": "Persistence",
    "seasonal_naive_168": "Seasonal naive 168 h",
    "xgb_no_readiness": "No readiness",
    "xgb_no_weather": "No weather",
    "xgb_core": "Core (history + calendar)",
    "hybrid_ridge": "Ridge residual",
    "sarimax_harmonic": "SARIMAX / Harmonic",
    "seasonal_naive_7d": "Seasonal naive 7 d",
}
COLORS = {
    "xgb": "#4C72B0",
    "hybrid": "#111111",
    "hybrid_hgb": "#55A868",
    "hybrid_lstm": "#C44E52",
    "standalone_lstm": "#8172B2",
    "persistence": "#937860",
    "seasonal_naive_168": "#CCB974",
    "xgb_no_readiness": "#DD8452",
    "xgb_no_weather": "#55A868",
    "xgb_core": "#8172B2",
    "hybrid_ridge": "#2B8CBE",
    "sarimax_harmonic": "#E17C05",
    "seasonal_naive_7d": "#CCB974",
}


def mean_by_horizon(df: pd.DataFrame, models: list[str], metric: str) -> pd.DataFrame:
    return (
        df[df["model"].isin(models)]
        .groupby(["horizon", "model"])[metric]
        .mean()
        .unstack()[models]
    )


def grouped_bars(df: pd.DataFrame, models: list[str], metric: str, ylabel: str, title: str, path: Path) -> None:
    table = mean_by_horizon(df, models, metric)
    x = np.arange(len(table.index))
    width = 0.8 / len(models)
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for i, model in enumerate(models):
        ax.bar(
            x + (i - (len(models) - 1) / 2) * width,
            table[model].to_numpy(),
            width=width,
            label=MODEL_LABELS.get(model, model),
            color=COLORS.get(model),
            edgecolor="white",
            linewidth=0.5,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h} h" for h in table.index])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(ncol=3, fontsize=9, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def delta_heatmap(df: pd.DataFrame, path: Path) -> None:
    sites = sorted(df["site"].unique())
    mat = np.full((len(sites), len(HORIZONS)), np.nan)
    for i, site in enumerate(sites):
        for j, h in enumerate(HORIZONS):
            sub = df[(df["site"] == site) & (df["horizon"] == h) & (df["model"].isin(["xgb", "hybrid"]))]
            vals = sub.set_index("model")["rmse"]
            if "xgb" in vals and "hybrid" in vals:
                mat[i, j] = vals["hybrid"] - vals["xgb"]
    vmax = np.nanmax(np.abs(mat))
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    im = ax.imshow(mat, cmap="RdYlGn_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(HORIZONS)))
    ax.set_xticklabels([f"{h} h" for h in HORIZONS])
    ax.set_yticks(range(len(sites)))
    ax.set_yticklabels(sites)
    for i in range(len(sites)):
        for j in range(len(HORIZONS)):
            val = mat[i, j]
            ax.text(j, i, f"{val:+.1f}", ha="center", va="center", fontsize=9,
                    color="black" if abs(val) < vmax * 0.6 else "white")
    ax.set_title("Selected hybrid minus XGBoost RMSE (kW)\nnegative = improvement")
    fig.colorbar(im, ax=ax, label="Δ RMSE (kW)")
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def selection_counts(path: Path) -> None:
    rows = []
    for p in sorted((MODELS / "metrics").glob("run_*_h*.json")):
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        rows.append({"horizon": r["horizon"], "selected": r.get("selection", {}).get("selected")})
    df = pd.DataFrame(rows)
    table = df.groupby(["horizon", "selected"]).size().unstack(fill_value=0)
    table = table.reindex(HORIZONS).fillna(0).astype(int)
    for col in ("xgb", "hgb", "lstm"):
        if col not in table:
            table[col] = 0
    table = table[["xgb", "hgb", "lstm"]]

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    bottom = np.zeros(len(table))
    for col, color in [("xgb", COLORS["xgb"]), ("hgb", COLORS["hybrid_hgb"]), ("lstm", COLORS["hybrid_lstm"])]:
        ax.bar([f"{h} h" for h in table.index], table[col], bottom=bottom,
               label=col.upper(), color=color, edgecolor="white")
        bottom += table[col].to_numpy()
    ax.set_ylabel("Site/horizon combinations")
    ax.set_title("Validation-selected Stage 2")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def per_site_panels(df: pd.DataFrame, path: Path) -> None:
    sites = sorted(df["site"].unique())
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.5), sharex=True, sharey=False)
    for ax, site in zip(axes.flat, sites):
        sub = df[(df["site"] == site) & (df["model"].isin(["xgb", "hybrid"]))]
        pivot = sub.pivot_table(index="horizon", columns="model", values="rmse").reindex(HORIZONS)
        ax.plot(pivot.index, pivot["xgb"], marker="o", label="XGBoost", color=COLORS["xgb"])
        ax.plot(pivot.index, pivot["hybrid"], marker="o", label="Selected hybrid", color=COLORS["hybrid"])
        ax.set_title(site)
        ax.set_xticks(HORIZONS)
        ax.set_xlabel("Horizon (h)")
        ax.set_ylabel("RMSE (kW)")
        ax.grid(alpha=0.25)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False)
    fig.suptitle("XGBoost vs validation-selected hybrid, by site", y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(METRICS)

    grouped_bars(
        df, ["xgb", "hybrid", "hybrid_hgb", "hybrid_lstm", "standalone_lstm"],
        "rmse", "RMSE (kW)", "Mean RMSE by forecast horizon",
        OUT / "fig_mean_rmse_by_horizon.png",
    )
    grouped_bars(
        df, ["xgb", "hybrid", "hybrid_hgb", "hybrid_lstm", "standalone_lstm"],
        "mae", "MAE (kW)", "Mean MAE by forecast horizon",
        OUT / "fig_mean_mae_by_horizon.png",
    )
    grouped_bars(
        df, ["xgb", "hybrid", "hybrid_hgb", "hybrid_lstm", "standalone_lstm"],
        "peak_bias", "Top-decile bias (kW)", "Peak-hour bias by forecast horizon\n(positive = under-prediction)",
        OUT / "fig_peak_bias_by_horizon.png",
    )
    grouped_bars(
        df, ["xgb", "xgb_no_readiness", "xgb_no_weather", "xgb_core"],
        "rmse", "RMSE (kW)", "Ablation: mean RMSE by horizon",
        OUT / "fig_ablation_rmse.png",
    )
    delta_heatmap(df, OUT / "fig_hybrid_delta_heatmap.png")
    selection_counts(OUT / "fig_selection_counts.png")
    per_site_panels(df, OUT / "fig_per_site_rmse.png")

    midterm_path = MODELS / "metrics_midterm.csv"
    if midterm_path.exists():
        mdf = pd.read_csv(midterm_path)
        mid_models = ["xgb", "hybrid", "hybrid_ridge", "hybrid_hgb", "sarimax_harmonic"]
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), sharex=True)
        for ax, (tcol, title) in zip(
            axes,
            [
                ("daily_mean_kw", "Daily Mean Load / Energy (kW)"),
                ("daily_peak_kw", "Daily Peak Demand (kW)"),
            ],
        ):
            sub = mdf[(mdf["target"] == tcol) & (mdf["model"].isin(mid_models))]
            table = sub.groupby(["horizon_days", "model"])["rmse"].mean().unstack()[mid_models]
            x = np.arange(len(table.index))
            width = 0.8 / len(mid_models)
            for i, m in enumerate(mid_models):
                ax.bar(
                    x + (i - (len(mid_models) - 1) / 2) * width,
                    table[m].to_numpy(),
                    width=width,
                    label=MODEL_LABELS.get(m, m),
                    color=COLORS.get(m),
                    edgecolor="white",
                    linewidth=0.5,
                )
            ax.set_xticks(x)
            ax.set_xticklabels([f"{d} d" for d in table.index])
            ax.set_ylabel("Mean RMSE across sites (kW)")
            ax.set_title(title)
            ax.grid(axis="y", alpha=0.25)
            ax.set_axisbelow(True)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.suptitle("Mid- to Long-Term Forecast Accuracy (1 Week to 3 Months)", y=1.02, fontsize=12)
        fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=5, frameon=False, fontsize=9)
        fig.tight_layout()
        fig.savefig(OUT / "fig_midterm_rmse_by_horizon.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

        # Operational mid/long-term metrics: 30-day energy volume error (%) & monthly peak tariff error (ZMW)
        op_models = ["xgb", "hybrid", "hybrid_ridge", "sarimax_harmonic"]
        fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.8), sharex=True)

        sub_mean = mdf[(mdf["target"] == "daily_mean_kw") & (mdf["model"].isin(op_models))]
        t_vol = sub_mean.groupby(["horizon_days", "model"])["window_30d_mape"].mean().unstack()[op_models]
        for m in op_models:
            axes[0].plot(
                [f"{d} d" for d in t_vol.index],
                t_vol[m].to_numpy(),
                marker="o",
                linewidth=2.0,
                label=MODEL_LABELS.get(m, m),
                color=COLORS.get(m),
            )
        axes[0].set_ylabel("Rolling 30-Day Energy Volume MAPE (%)")
        axes[0].set_title("Monthly Energy / Fuel Budget Error (30-Day MWh)")
        axes[0].grid(alpha=0.25)

        sub_peak = mdf[(mdf["target"] == "daily_peak_kw") & (mdf["model"].isin(op_models))]
        t_zmw = (
            sub_peak.groupby(["horizon_days", "model"])["monthly_peak_mae_zmw"]
            .mean()
            .unstack()[op_models]
            / 1000.0
        )
        for m in op_models:
            axes[1].plot(
                [f"{d} d" for d in t_zmw.index],
                t_zmw[m].to_numpy(),
                marker="o",
                linewidth=2.0,
                label=MODEL_LABELS.get(m, m),
                color=COLORS.get(m),
            )
        axes[1].set_ylabel("Monthly Max-Demand Error (Thousand ZMW / site)")
        axes[1].set_title("Monthly Peak Tariff Error (@ 120 ZMW/kW/month)")
        axes[1].grid(alpha=0.25)

        handles, labels = axes[0].get_legend_handles_labels()
        fig.suptitle("Strategic Operational Metrics Across Mid- to Long-Term Horizons", y=1.02, fontsize=12)
        fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=4, frameon=False, fontsize=9)
        fig.tight_layout()
        fig.savefig(OUT / "fig_midterm_operational_metrics.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

    print(f"wrote figures to {OUT}")
    for p in sorted(OUT.glob("*.png")):
        print(" ", p.name)


if __name__ == "__main__":
    main()
