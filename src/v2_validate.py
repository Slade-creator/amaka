"""
Data-contract validation for the v2 pipeline.

Run after v2_generate_load.py and v2_preprocess.py:

    python src/v2_validate.py

The script exits non-zero on the first failed contract. It is deliberately
dependency-free (no pytest) so it can run on a fresh Colab VM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from v2_config import (
    PROCESSED, SITE_CONFIGS, SITES, TEST_END, TEST_START, TRAIN_END, TRAIN_START,
    VAL_END, VAL_START, stable_site_seed,
)
from v2_holidays import holiday_mask, zambian_holidays
from v2_horizons import FEATURE_COLS, build_horizon, load_base

FORBIDDEN_FEATURES = {
    "load_kw", "load_kw_feature", "net_load_kw", "gross_load_kw", "pv_kw",
    "is_target_imputed", "grid_fault", "generator_backup", "disruption_type",
    "disruption_fault_trip", "disruption_comms_dropout", "target",
    "target_valid", "target_imputed",
}

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  PASS  {message}")
    else:
        print(f"  FAIL  {message}")
        failures.append(message)


def main() -> int:
    print("1. Facility files")
    grid_fault_total = 0
    for site in SITES:
        path = PROCESSED / f"facility_load_{site}.csv"
        check(path.exists(), f"{site}: facility file exists")
        df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp").sort_index()
        expected = pd.date_range("2024-01-01", "2025-12-31 23:00", freq="h")
        check(len(df) == len(expected), f"{site}: 17,544 hourly rows")
        check(df.index.equals(expected), f"{site}: complete hourly index")
        check(not df.index.duplicated().any(), f"{site}: no duplicate timestamps")
        check((df["load_kw"].dropna() >= 0).all(), f"{site}: no negative observed load")
        check((df["net_load_kw"] >= 0).all(), f"{site}: no negative underlying net load")
        check(df[["temperature_2m", "relative_humidity_2m", "shortwave_radiation"]].notna().all().all(),
              f"{site}: weather complete")
        check(set(df["readiness_code"].unique()).issubset({1, 2, 3, 4}),
              f"{site}: readiness codes are 1..4")
        check(set(df["disruption_type"].unique()).issubset(
            {"none", "fault_trip", "maintenance", "comms_dropout"}),
            f"{site}: disruption labels valid")
        check(((df["grid_fault"] == 0) | (df["grid_fault"] == 1)).all(),
              f"{site}: grid_fault is binary")
        check(((df["generator_backup"] == df["grid_fault"]).all()),
              f"{site}: generator_backup mirrors grid_fault")
        grid_fault_total += int(df["grid_fault"].sum())
        # At least some internal disruptions should exist.
        check(int((df["disruption_type"] != "none").sum()) > 0,
              f"{site}: internal disruptions present")
        # Weather identity: tug_argan uses the Peter Zuze grid cell.
        wx_site = "peter_zuze" if site == "tug_argan" else site
        wx = pd.read_csv(PROCESSED.parent / "raw" / f"weather_{wx_site}.csv",
                          parse_dates=["timestamp"], index_col="timestamp")
        check(np.allclose(df["temperature_2m"], wx.reindex(df.index)["temperature_2m"]),
              f"{site}: temperature matches raw weather ({wx_site})")

    print(f"  grid-fault hours across all sites: {grid_fault_total}")
    check(grid_fault_total > 0, "unscheduled grid faults are present")

    print("\n2. Preprocessed features")
    for site in SITES:
        f = load_base(site)
        check(f["is_target_imputed"].sum() == f["load_kw"].isna().sum(),
              f"{site}: is_target_imputed matches load_kw NaNs")
        check(f["load_kw_feature"].notna().all(), f"{site}: feature series is continuous")
        check(f["readiness_code"].between(1, 4).all(), f"{site}: readiness encoded")
        check(f["is_holiday"].isin([0, 1]).all(), f"{site}: holiday flag binary")
        check(bool(np.array_equal(f["is_holiday"].to_numpy(),
                                  holiday_mask(f.index).astype(int))),
              f"{site}: holiday flag matches calendar")
        for lag in (1, 2, 24, 168):
            diff = (f[f"load_lag_{lag}h"] - f["load_kw_feature"].shift(lag)).abs().max()
            check(float(diff) < 1e-9, f"{site}: lag {lag}h exact")
        check(float((f["load_roll_mean_24h"] -
                     f["load_kw_feature"].shift(1).rolling(24).mean()).abs().max()) < 1e-9,
              f"{site}: rolling mean exact")

    print("\n3. Horizon alignment")
    base = load_base("arakan")
    for h in (1, 6, 24, 48):
        hz = build_horizon(base, "arakan", h)
        shift = h - 1
        expected_target = base["load_kw"].shift(-shift).reindex(hz.index)
        check(np.allclose(hz["target"], expected_target, equal_nan=True),
              f"h={h}: target is load at origin+{h} hours")
        check(
            bool((pd.to_datetime(hz["target_time"]) ==
                  (hz.index + pd.Timedelta(hours=shift))).all()),
            f"h={h}: target_time aligned",
        )
        check(not hz[FEATURE_COLS].isna().any().any(), f"h={h}: no NaNs in model features")
        check(not (set(FEATURE_COLS) & FORBIDDEN_FEATURES),
              f"h={h}: no forbidden/leaky features")

    print("\n4. Baseline alignment (h=1)")
    hz = build_horizon(base, "arakan", 1)
    obs = base["load_kw"]
    check(np.allclose(hz["seasonal_naive_24"], obs.shift(24).reindex(hz.index), equal_nan=True),
          "h=1: daily seasonal naive aligned")
    check(np.allclose(hz["seasonal_naive_168"], obs.shift(168).reindex(hz.index), equal_nan=True),
          "h=1: weekly seasonal naive aligned")
    check(np.allclose(hz["persistence"],
                      base["load_kw"].ffill().shift(1).reindex(hz.index), equal_nan=True),
          "h=1: persistence aligned")

    print("\n5. Split coverage")
    tt = pd.to_datetime(hz["target_time"]).astype("datetime64[ns]")
    tr = tt.between(pd.Timestamp(TRAIN_START), pd.Timestamp(TRAIN_END))
    va = tt.between(pd.Timestamp(VAL_START), pd.Timestamp(VAL_END))
    te = tt.between(pd.Timestamp(TEST_START), pd.Timestamp(TEST_END))
    check((tr & va).sum() == 0 and (tr & te).sum() == 0 and (va & te).sum() == 0,
          "train/val/test target windows do not overlap")
    check(tr.sum() > 0 and va.sum() > 0 and te.sum() > 0, "all splits non-empty")

    print("\n6. Zambian holiday calendar")
    h24 = zambian_holidays(2024)
    h25 = zambian_holidays(2025)
    for d in [
        pd.Timestamp("2024-03-08"), pd.Timestamp("2024-03-30"),
        pd.Timestamp("2024-04-29"), pd.Timestamp("2024-07-01"),
        pd.Timestamp("2024-08-05"), pd.Timestamp("2024-10-24"),
        pd.Timestamp("2025-05-26"), pd.Timestamp("2025-07-07"),
        pd.Timestamp("2025-08-04"), pd.Timestamp("2025-10-24"),
    ]:
        check(d.date() in (h24 if d.year == 2024 else h25), f"holiday present: {d.date()}")

    print("\n7. Stable seeds")
    check(stable_site_seed("kohima") == stable_site_seed("kohima"),
          "site seed is stable within a process")
    check(len({stable_site_seed(s) for s in SITES}) == len(SITES),
          "site seeds are distinct")

    print("\n8. Configuration sanity")
    for site, cfg in SITE_CONFIGS.items():
        check(cfg["headcount"] > 0 and cfg["floor_area_m2"] > 0,
              f"{site}: headcount/floor area present")
        check(cfg["hvac_w_m2_c"] > 0 and cfg["lighting_w_m2"] > 0,
              f"{site}: per-site HVAC/lighting sizing present")
        check(cfg["maintenance_p_hour"] > 0.005,
              f"{site}: maintenance rate in realistic 1-2/month band")

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} contract(s)")
        for msg in failures:
            print(f"  - {msg}")
        return 1
    print("ALL DATA CONTRACTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
