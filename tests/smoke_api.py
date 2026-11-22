"""
End-to-end smoke test for the AMAKA prototype (v2 multi-horizon API).

Starts uvicorn on a free port, exercises every API endpoint across the
supported forecast horizons (1 / 24 / 48 by default, 6 covered indirectly),
checks the CSV and PDF exports, validation errors and the v2 fleet anchor,
then shuts the server down. No external services required.

Usage:
    python tests/smoke_api.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SITE = "arakan"
ANCHOR = "2025-10-04T18:00:00"
HORIZONS = [1, 24, 48]
ALL_HORIZONS = [1, 6, 24, 48]
BAD_HORIZONS = ["3", "49", "abc", "1.5"]

EXPECTED_SITE_IDS = {"arakan", "kohima", "makeni", "mikango",
                     "peter_zuze", "tug_argan"}

# v2 model inputs (FEATURE_COLS in src/v2_horizons.py).
V2_FEATURES = {
    "load_lag_1h", "load_lag_2h", "load_lag_24h", "load_lag_168h",
    "load_roll_mean_24h", "load_roll_std_24h",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "is_holiday", "is_weekend",
    "temperature_2m", "relative_humidity_2m", "precipitation", "cloud_cover",
    "shortwave_radiation", "wind_speed_10m",
    "readiness_code", "disruption_maintenance",
}
V1_ONLY_FEATURES = {"is_imputed", "disruption_fault_trip",
                    "disruption_comms_dropout"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for(base: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = requests.get(f"{base}/api/health", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException as exc:
            last = exc
        time.sleep(0.4)
    raise RuntimeError(f"server did not become ready: {last}")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def load_v2_config() -> dict:
    path = ROOT / "config" / "v2_sites.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    cfg_file = load_v2_config()
    anchors = cfg_file.get("fleet_anchor_by_horizon", {})

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    users_file = Path(tempfile.mkdtemp()) / "users.json"
    http = requests.Session()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        # Keep the smoke test offline and deterministic: the narrative endpoint
        # must exercise its rule-based path, never a live model call.
        # A throwaway accounts file seeded from config/users.seed.json keeps the
        # test independent of whatever accounts exist on this machine.
        env={**os.environ, "SENTINEL_LLM_PROVIDER": "off",
             "SENTINEL_USERS_FILE": str(users_file),
             "SENTINEL_DEMO_USERS": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for(base)
        print(f"AMAKA API smoke test @ {base}\n")

        # ------------------------------------------------------------------
        # Auth: data endpoints need a bearer token
        # ------------------------------------------------------------------
        check(requests.get(f"{base}/api/overview", timeout=5).status_code == 401,
              "overview without a token -> 401")
        bad = requests.post(f"{base}/api/auth/login", timeout=5,
                            json={"username": "analyst", "password": "wrong-password"})
        check(bad.status_code == 401, "login with a wrong password -> 401")
        seed = json.loads((ROOT / "config" / "users.seed.json").read_text())
        creds = {u["role"]: u for u in seed["users"]}
        login = requests.post(f"{base}/api/auth/login", timeout=5, json={
            "username": creds["analyst"]["username"],
            "password": creds["analyst"]["password"]})
        check(login.status_code == 200, "analyst login -> 200")
        token = login.json()["access_token"]
        me = requests.get(f"{base}/api/auth/me", timeout=5,
                          headers={"Authorization": f"Bearer {token}"}).json()
        check(me["user"]["role"] == "analyst", "/api/auth/me returns the analyst")
        cmd = requests.post(f"{base}/api/auth/login", timeout=5, json={
            "username": creds["commander"]["username"],
            "password": creds["commander"]["password"]}).json()["access_token"]
        check(requests.post(f"{base}/api/sites/{SITE}/narrative/ask", timeout=5,
                            headers={"Authorization": f"Bearer {cmd}"},
                            json={"question": "Why the peak?"}).status_code == 403,
              "commander cannot use the question box -> 403")
        http.headers["Authorization"] = f"Bearer {token}"


        # ------------------------------------------------------------------
        # Health / docs / root
        # ------------------------------------------------------------------
        health = http.get(f"{base}/api/health", timeout=5).json()
        check(health["status"] == "ok", "health is ok")
        check(health["sites"] == 6, "health reports 6 sites")
        check(health.get("version") == "v2", "health reports version v2")
        check(health.get("horizons") == ALL_HORIZONS,
              "health reports horizons [1, 6, 24, 48]")
        check(health.get("default_horizon") == 24,
              "health default_horizon is 24")

        check(http.get(f"{base}/docs", timeout=5).status_code == 200,
              "/docs is served")

        # ------------------------------------------------------------------
        # Overview: default + every horizon
        # ------------------------------------------------------------------
        ov_default = http.get(f"{base}/api/overview", timeout=10)
        check(ov_default.status_code == 200, "overview returns 200")
        ov_default = ov_default.json()
        check(ov_default.get("version") == "v2", "overview version is v2")
        check(ov_default.get("available_horizons") == ALL_HORIZONS,
              "overview lists available horizons")
        check(ov_default.get("default_horizon") == 24,
              "overview default_horizon is 24")
        check(ov_default.get("horizon") == 24,
              "overview echoes default horizon 24")
        check(isinstance(ov_default.get("fleet_anchor_by_horizon"), dict)
              and set(ov_default["fleet_anchor_by_horizon"]) ==
              {str(h) for h in ALL_HORIZONS},
              "overview carries fleet_anchor_by_horizon for all 4 horizons")
        check(ov_default.get("fleet_anchor")
              == ov_default["fleet_anchor_by_horizon"]["24"],
              "default fleet_anchor is the h=24 anchor")
        check(ov_default.get("fleet_anchor") == anchors.get("24"),
              "v2 anchor matches config/v2_sites.json (h=24)")
        check(len(ov_default["sites"]) == 6, "overview returns 6 sites")
        check(ov_default["model"]["name"].startswith("Hybrid"),
              "model metadata present")
        check("cost_assumptions" in ov_default, "cost assumptions present")
        ids = {s["id"] for s in ov_default["sites"]}
        check(ids == EXPECTED_SITE_IDS, "all expected site ids present")
        check(ov_default["model"].get("features") == 22,
              "model declares 22 v2 features")

        mapes: dict[int, float] = {}
        for h in HORIZONS + [6]:
            r = http.get(f"{base}/api/overview",
                             params={"horizon": h}, timeout=10)
            check(r.status_code == 200, f"overview?horizon={h} returns 200")
            ov = r.json()
            check(len(ov["sites"]) == 6,
                  f"overview h={h} returns 6 sites")
            check(ov["horizon"] == h, f"overview h={h} echoes horizon")
            check(ov["fleet_anchor"] == anchors.get(str(h)),
                  f"overview h={h} fleet_anchor matches config")
            check(set(ov["fleet_anchor_by_horizon"]) ==
                  {str(x) for x in ALL_HORIZONS},
                  f"overview h={h} keeps fleet_anchor_by_horizon")
            check(ov["available_horizons"] == ALL_HORIZONS
                  and ov["default_horizon"] == 24,
                  f"overview h={h} keeps available/default horizons")
            for s in ov["sites"]:
                nested = (s.get("horizons") or {}).get(str(h))
                check(nested is not None,
                      f"{s['id']} h={h} has nested horizons[{h}] block")
                check(s["horizon"] == h,
                      f"{s['id']} top-level horizon is {h}")
                for block in ("metrics", "load", "alerts", "cost"):
                    check(s.get(block) == nested.get(block),
                          f"{s['id']} h={h} top-level {block} mirrors "
                          f"horizons[{h}]")
                for key in ("metrics", "load", "alerts", "cost",
                            "selected_model", "demo_anchor"):
                    check(key in s, f"{s['id']} h={h} has {key}")
                check("threshold_kw" in s["load"]
                      and "hyb_mape" in s["metrics"],
                      f"{s['id']} h={h} metrics/load are populated")
                check(isinstance(s["metrics"].get("persistence_mae"), (int, float))
                      and s["metrics"]["persistence_mae"]
                      >= s["metrics"]["hyb_mae"],
                      f"{s['id']} h={h} persistence baseline is worse "
                      f"than hybrid MAE")
            ark = [s for s in ov["sites"] if s["id"] == SITE][0]
            mapes[h] = float(ark["metrics"]["hyb_mape"])

        check(abs(mapes[1] - mapes[24]) > 0.05,
              "arakan h=1 and h=24 MAPE differ (cached config not mutated)")

        # ------------------------------------------------------------------
        # Series (per horizon)
        # ------------------------------------------------------------------
        expected_rows = None
        for h in HORIZONS:
            r = http.get(f"{base}/api/sites/{SITE}/series",
                             params={"horizon": h}, timeout=15)
            check(r.status_code == 200, f"series h={h} returns 200")
            series = r.json()
            check(series.get("horizon") == h, f"series h={h} echoes horizon")
            check(len(series["rows"]) > 4000,
                  f"series h={h} returns the full test-period replay")
            if expected_rows is None:
                expected_rows = len(series["rows"])
                check(expected_rows == 4340,
                      "series row count matches the v2 replay (~4,340)")
            check(len(series["rows"]) == expected_rows,
                  f"series h={h} row count matches h=1")
            row = series["rows"][0]
            for key in ("timestamp", "actual_kw", "xgb_kw", "hybrid_kw",
                        "lower_kw", "upper_kw", "selected_model",
                        "readiness_code", "readiness_label",
                        "temperature_c", "is_holiday", "is_weekend"):
                check(key in row, f"series h={h} row has {key}")
            check(row["lower_kw"] <= row["hybrid_kw"] <= row["upper_kw"],
                  f"series h={h} forecast lies inside its interval")

        default_series = http.get(
            f"{base}/api/sites/{SITE}/series", timeout=15).json()
        check(default_series.get("horizon") == 24,
              "series without horizon defaults to h=24")

        window = http.get(
            f"{base}/api/sites/{SITE}/series",
            params={"horizon": 24, "from": "2025-10-01",
                    "to": "2025-10-07T23:00:00"},
            timeout=10,
        ).json()["rows"]
        check(100 < len(window) < 200, "date filtering returns a 7-day window")

        clamped = http.get(
            f"{base}/api/sites/{SITE}/series",
            params={"horizon": 1, "from": "2020-01-01", "to": "2020-01-05"},
            timeout=10,
        )
        check(clamped.status_code == 200,
              "series clamps out-of-range dates instead of failing")

        # ------------------------------------------------------------------
        # Explain (per horizon)
        # ------------------------------------------------------------------
        for h in HORIZONS:
            r = http.get(f"{base}/api/sites/{SITE}/explain",
                             params={"at": ANCHOR, "horizon": h}, timeout=10)
            check(r.status_code == 200, f"explain h={h} returns 200")
            explain = r.json()
            check(explain.get("horizon") == h, f"explain h={h} echoes horizon")
            check(len(explain["top"]) == 10, f"explain h={h} returns top-10")
            check(len(explain["all"]) == 22,
                  f"explain h={h} returns all 22 v2 features")
            feats = {row["feature"] for row in explain["all"]}
            check(feats == V2_FEATURES,
                  f"explain h={h} feature set matches v2 FEATURE_COLS")
            check(not (feats & V1_ONLY_FEATURES),
                  f"explain h={h} has no v1-only features")
            check("is_holiday" in feats and "is_weekend" in feats,
                  f"explain h={h} includes is_holiday / is_weekend")
            check(isinstance(explain["base_kw"], (int, float)),
                  f"explain h={h} returns base value")
            top = explain["top"][0]
            check({"feature", "label", "value", "contribution_kw",
                   "direction"} <= set(top),
                  f"explain h={h} rows are fully populated")
            check(all(row["label"] for row in explain["all"]),
                  f"explain h={h} every feature has a human label")

        # ------------------------------------------------------------------
        # Alerts (per horizon)
        # ------------------------------------------------------------------
        for h in HORIZONS:
            r = http.get(f"{base}/api/sites/{SITE}/alerts",
                             params={"at": ANCHOR, "hours": 24,
                                     "horizon": h}, timeout=10)
            check(r.status_code == 200, f"alerts h={h} returns 200")
            alerts = r.json()
            check(alerts.get("horizon") == h, f"alerts h={h} echoes horizon")
            check(isinstance(alerts["alerts"], list),
                  f"alerts h={h} returns a list")
            check(len(alerts["alerts"]) >= 1,
                  f"alerts h={h} finds at least one alert at the anchor")
            check(all(a["severity"] in {"critical", "warning", "info"}
                      for a in alerts["alerts"]),
                  f"alerts h={h} severities are valid")
            ids_a = [a["id"] for a in alerts["alerts"]]
            check(len(ids_a) == len(set(ids_a)),
                  f"alerts h={h} ids are unique (dedup by kind)")
            check(isinstance(alerts.get("threshold_kw"), (int, float))
                  and isinstance(alerts.get("band_kw"), (int, float)),
                  f"alerts h={h} reports its horizon threshold and band")

        wide = http.get(f"{base}/api/sites/{SITE}/alerts",
                            params={"hours": 24 * 120, "horizon": 24},
                            timeout=15).json()
        check(len(wide["alerts"]) >= 1,
              "wide alert window finds alerts (no anchor given)")

        # ------------------------------------------------------------------
        # Chart narrative (rules path; no model configured)
        # ------------------------------------------------------------------
        nar_params = {
            "at": ANCHOR, "horizon": 24, "from": "2025-10-01",
            "to": "2025-10-04T18:00:00", "role": "operator",
        }
        r = http.get(f"{base}/api/sites/{SITE}/narrative",
                         params={**nar_params, "mode": "fast"}, timeout=10)
        check(r.status_code == 200, "narrative fast returns 200")
        nar = r.json()
        check(nar.get("source") == "rules", "narrative fast is rule-based")
        check(nar.get("at") == ANCHOR, "narrative echoes the selected hour")
        check(nar.get("window", {}).get("from")
              == "2025-10-01T00:00:00",
              "narrative echoes the window start")
        check(len(nar.get("text", "")) > 80,
              "narrative text is substantial")
        check(nar.get("facts", {}).get("window", {}).get("hours", 0) > 0,
              "narrative ships its fact pack")
        check(nar["facts"]["selected_hour"]["timestamp"] == ANCHOR,
              "fact pack selected hour matches")

        for role in ("commander", "operator", "analyst"):
            rr = http.get(f"{base}/api/sites/{SITE}/narrative",
                              params={**nar_params, "role": role,
                                      "mode": "fast"}, timeout=10)
            check(rr.status_code == 200, f"narrative role={role} returns 200")
            check(len(rr.json().get("text", "")) > 80,
                  f"narrative role={role} has text")

        r = http.get(f"{base}/api/sites/{SITE}/narrative",
                         params={**nar_params, "mode": "auto"}, timeout=20)
        check(r.status_code == 200, "narrative auto falls back without a model")
        auto = r.json()
        check(auto.get("source") == "rules",
              "narrative auto uses rules when no model is configured")
        check(auto.get("fallback_reason") == "not_configured",
              "narrative reports not_configured")
        check(bool(auto.get("notice")), "narrative explains the fallback")

        r = http.post(f"{base}/api/sites/{SITE}/narrative/ask",
                          json={**nar_params,
                                "question": "How accurate was the forecast?"},
                          timeout=20)
        check(r.status_code == 200, "narrative ask returns 200")
        asked = r.json()
        check(asked.get("source") == "rules",
              "narrative ask uses rules without a model")
        check(len(asked.get("answer", "")) > 40,
              "narrative ask returns a grounded answer")
        check(asked.get("question") == "How accurate was the forecast?",
              "narrative ask echoes the question")

        r = http.get(f"{base}/api/sites/{SITE}/narrative",
                         params={**nar_params, "role": "nope"}, timeout=5)
        check(r.status_code == 200 and r.json().get("role") == "analyst",
              "narrative ignores the role param and uses the account role")
        r = http.get(f"{base}/api/sites/{SITE}/narrative",
                         params={**nar_params, "mode": "nope"}, timeout=5)
        check(r.status_code == 400, "narrative rejects an unknown mode")
        r = http.post(f"{base}/api/sites/{SITE}/narrative/ask",
                          json={**nar_params, "question": "x"}, timeout=5)
        check(r.status_code == 422, "narrative ask rejects a too-short question")

        # ------------------------------------------------------------------
        # Fleet map snapshot (per horizon)
        # ------------------------------------------------------------------
        for h in HORIZONS:
            r = http.get(f"{base}/api/fleet",
                             params={"at": ANCHOR, "horizon": h}, timeout=15)
            check(r.status_code == 200, f"fleet h={h} returns 200")
            fleet = r.json()
            check(fleet.get("horizon") == h, f"fleet h={h} echoes horizon")
            check(fleet["at"] == ANCHOR, f"fleet h={h} echoes the instant")
            check(len(fleet["sites"]) == 6, f"fleet h={h} returns 6 sites")
            fids = {s["id"] for s in fleet["sites"]}
            check(fids == EXPECTED_SITE_IDS,
                  f"fleet h={h} site ids complete")
            for s in fleet["sites"]:
                for key in ("id", "label", "location", "type", "lat", "lon",
                            "actual_kw", "hybrid_kw", "threshold_kw",
                            "headroom_kw", "readiness_code", "readiness_label",
                            "mape", "monthly_saving_zmw", "status"):
                    check(key in s, f"fleet h={h} row {s['id']} has {key}")
                check(s["status"] in {"critical", "warning", "nominal"},
                      f"fleet h={h} status for {s['id']} is valid")
                expected = ("critical" if s["hybrid_kw"] > s["threshold_kw"]
                            else "warning"
                            if s["hybrid_kw"] >= s["threshold_kw"] * 0.97
                            else "nominal")
                check(s["status"] == expected,
                      f"fleet h={h} status for {s['id']} matches thresholds")
                check(abs(s["headroom_kw"]
                          - (s["threshold_kw"] - s["hybrid_kw"])) < 0.05,
                      f"fleet h={h} headroom for {s['id']} = thr - hybrid")
                check(-180 <= s["lat"] <= 0 and 20 <= s["lon"] <= 40,
                      f"fleet h={h} coordinates for {s['id']} are in Zambia")

            totals = fleet["totals"]
            for key in ("load_kw", "peak_kw", "saving_zmw",
                        "sites_at_risk", "surge_sites"):
                check(key in totals, f"fleet h={h} totals has {key}")
            check(abs(totals["load_kw"]
                      - sum(s["actual_kw"] for s in fleet["sites"])) < 0.5,
                  f"fleet h={h} load_kw sums actual loads")
            check(abs(totals["peak_kw"]
                      - max(s["hybrid_kw"] for s in fleet["sites"])) < 0.05,
                  f"fleet h={h} peak_kw is the max hybrid forecast")
            check(totals["saving_zmw"]
                  == sum(s["monthly_saving_zmw"] for s in fleet["sites"]),
                  f"fleet h={h} saving_zmw sums site savings")
            check(totals["sites_at_risk"]
                  == sum(1 for s in fleet["sites"]
                         if s["status"] in ("critical", "warning")),
                  f"fleet h={h} sites_at_risk counts critical+warning")
            check(totals["surge_sites"]
                  == sum(1 for s in fleet["sites"]
                         if s["readiness_code"] <= 2),
                  f"fleet h={h} surge_sites counts readiness<=2")

        fleet_default = http.get(f"{base}/api/fleet", timeout=10).json()
        check(fleet_default.get("horizon") == 24,
              "fleet without horizon defaults to h=24")
        check(len(fleet_default["sites"]) == 6,
              "fleet without at returns all 6 sites")
        check(fleet_default["at"] is not None,
              "fleet default at resolves to the latest row")

        fleet_out = http.get(f"{base}/api/fleet",
                                 params={"at": "2020-01-01T00:00:00"},
                                 timeout=10)
        check(fleet_out.status_code == 200, "fleet clamps out-of-range at")
        check(len(fleet_out.json()["sites"]) == 6,
              "clamped fleet still returns 6 sites")

        fleet_bad = http.get(f"{base}/api/fleet",
                                 params={"at": "not-a-date"}, timeout=5)
        check(fleet_bad.status_code == 400, "fleet invalid date returns 400")

        # warm latency: second call must be quick (data is cached)
        t0 = time.perf_counter()
        http.get(f"{base}/api/fleet", params={"at": ANCHOR}, timeout=10)
        warm_ms = (time.perf_counter() - t0) * 1000
        check(warm_ms < 300, f"fleet warm response is fast ({warm_ms:.0f} ms)")

        # ------------------------------------------------------------------
        # CSV + PDF exports (per horizon)
        # ------------------------------------------------------------------
        for h in HORIZONS:
            csv = http.get(
                f"{base}/api/sites/{SITE}/report.csv",
                params={"horizon": h, "from": "2025-10-01",
                        "to": "2025-10-07T23:00:00"},
                timeout=15)
            check(csv.status_code == 200, f"CSV h={h} returns 200")
            cd = csv.headers.get("content-disposition", "")
            check(f"amaka_{SITE}_h{h}_report.csv" in cd,
                  f"CSV h={h} filename carries the horizon")
            check(csv.text.startswith("timestamp,actual_kw"),
                  f"CSV h={h} header is correct")
            check("selected_model" in csv.text.splitlines()[0],
                  f"CSV h={h} header includes selected_model")
            check(len(csv.text.strip().splitlines()) > 100,
                  f"CSV h={h} contains the window rows")

            pdf = http.get(
                f"{base}/api/sites/{SITE}/report.pdf",
                params={"horizon": h, "from": "2025-10-01",
                        "to": "2025-10-07T23:00:00"},
                timeout=40)
            check(pdf.status_code == 200, f"PDF h={h} returns 200")
            check(pdf.content.startswith(b"%PDF"),
                  f"PDF h={h} signature is valid")
            check(len(pdf.content) > 20_000,
                  f"PDF h={h} has non-trivial content (chart embedded)")
            pcd = pdf.headers.get("content-disposition", "")
            check(f"amaka_{SITE}_h{h}_report.pdf" in pcd,
                  f"PDF h={h} filename carries the horizon")

        # ------------------------------------------------------------------
        # Validation
        # ------------------------------------------------------------------
        for bh in BAD_HORIZONS:
            for path, params in (
                ("/api/overview", {}),
                (f"/api/sites/{SITE}/series", {}),
                (f"/api/sites/{SITE}/explain", {"at": ANCHOR}),
                (f"/api/sites/{SITE}/narrative", {"at": ANCHOR}),
                (f"/api/sites/{SITE}/alerts", {"at": ANCHOR}),
                ("/api/fleet", {"at": ANCHOR}),
                (f"/api/sites/{SITE}/report.csv", {}),
                (f"/api/sites/{SITE}/report.pdf", {}),
            ):
                r = http.get(f"{base}{path}",
                                 params={**params, "horizon": bh}, timeout=10)
                check(r.status_code == 400,
                      f"{path} rejects horizon={bh} with 400")
                check("detail" in r.json() and r.json()["detail"],
                      f"{path} explains the bad horizon")

        bad_site = http.get(f"{base}/api/sites/nope/series", timeout=5)
        check(bad_site.status_code == 404, "unknown site returns 404")
        bad_date = http.get(f"{base}/api/sites/{SITE}/series",
                                params={"from": "not-a-date"}, timeout=5)
        check(bad_date.status_code == 400, "invalid date returns 400")

        # ------------------------------------------------------------------
        # Mid- to Long-Term (7d, 14d, 30d, 60d, 90d) endpoints
        # ------------------------------------------------------------------
        mt_ov = http.get(f"{base}/api/midterm/overview", timeout=10)
        check(mt_ov.status_code == 200, "midterm overview returns 200")
        mt_ov_json = mt_ov.json()
        check(mt_ov_json.get("horizon_days") == 30,
              "midterm overview defaults to 30 days")
        check(mt_ov_json.get("available_horizons_days") == [7, 14, 30, 60, 90],
              "midterm overview lists [7, 14, 30, 60, 90]")
        check(len(mt_ov_json.get("sites", [])) == 6,
              "midterm overview returns 6 sites")

        for d in (7, 30, 90):
            mt_site = http.get(f"{base}/api/sites/{SITE}/midterm",
                                   params={"horizon_days": d}, timeout=10)
            check(mt_site.status_code == 200,
                  f"site midterm d={d} returns 200")
            mt_body = mt_site.json()
            check(mt_body.get("horizon_days") == d,
                  f"site midterm d={d} echoes horizon_days")
            check(len(mt_body.get("rows", [])) >= 180,
                  f"site midterm d={d} returns 2025 H2 daily replay rows")
            check("hybrid" in mt_body["metrics"]["daily_mean_kw"]
                  and "sarimax_harmonic" in mt_body["metrics"]["daily_mean_kw"],
                  f"site midterm d={d} includes hybrid & sarimax_harmonic metrics")

        bad_mt = http.get(f"{base}/api/sites/{SITE}/midterm",
                              params={"horizon_days": 45}, timeout=5)
        check(bad_mt.status_code == 400,
              "site midterm rejects unsupported horizon_days=45 with 400")

        print("\nALL CHECKS PASSED")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
