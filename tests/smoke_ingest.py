"""
End-to-end test of live data ingestion (portable meter kits).

Starts the API on a free port with a throwaway accounts file and ingest
database, then walks the full plug-and-play path:

  analyst signs in → adds a field site → issues an enrolment code →
  the kit simulator (scripts/device_sim.py) enrols, back-fills history,
  streams through a simulated link outage and flushes its backlog →
  device health + hourly roll-up + quality flags → CSV upload →
  role checks → revoke.

Usage:
    python tests/smoke_ingest.py
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
SIM = ROOT / "scripts" / "device_sim.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for(base: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{base}/api/health", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.4)
    raise RuntimeError("server did not become ready")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def sim(base: str, workdir: Path, *args: str) -> str:
    out = subprocess.run([sys.executable, str(SIM), "--server", base, *args],
                         cwd=workdir, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise AssertionError(f"simulator failed: {out.stdout}\n{out.stderr}")
    return out.stdout


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env={**os.environ, "SENTINEL_LLM_PROVIDER": "off",
             "SENTINEL_USERS_FILE": str(tmp / "users.json"),
             "SENTINEL_INGEST_DB": str(tmp / "ingest.db"),
             "SENTINEL_DEMO_USERS": "1"},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        wait_for(base)
        print(f"Live ingestion smoke test @ {base}\n")
        seed = json.loads((ROOT / "config" / "users.seed.json").read_text())
        creds = {u["role"]: u for u in seed["users"]}

        def session(role: str) -> requests.Session:
            s = requests.Session()
            tok = requests.post(f"{base}/api/auth/login", timeout=5, json={
                "username": creds[role]["username"],
                "password": creds[role]["password"]}).json()["access_token"]
            s.headers["Authorization"] = f"Bearer {tok}"
            return s

        analyst, commander = session("analyst"), session("commander")

        # -- auth boundaries ---------------------------------------------------
        check(requests.get(f"{base}/api/devices", timeout=5).status_code == 401,
              "device list needs a sign-in")
        check(requests.post(f"{base}/api/ingest", timeout=5,
                            json={"readings": [{"ts": 0, "kw": 1}]}).status_code == 401,
              "ingest without a device token -> 401")
        check(commander.post(f"{base}/api/devices/enrolment", timeout=5,
                             json={"site_id": "arakan"}).status_code == 403,
              "commander cannot issue enrolment codes -> 403")

        # -- add a field site ------------------------------------------------------
        site = {"id": "kabwe_test", "label": "Kabwe Test Barracks", "location": "Kabwe",
                "type": "Army garrison", "lat": -14.45, "lon": 28.45, "threshold_kw": 2600}
        r = analyst.post(f"{base}/api/live/sites", json=site, timeout=5)
        check(r.status_code == 201 and r.json()["source"] == "field", "analyst adds a field site")
        check(analyst.post(f"{base}/api/live/sites", timeout=5,
                           json={**site, "id": "bad_coords", "lat": 28.4, "lon": -14.4}
                           ).status_code == 400, "swapped coordinates are rejected")
        ids = [s["id"] for s in analyst.get(f"{base}/api/live/sites", timeout=5).json()["sites"]]
        check("kabwe_test" in ids and "arakan" in ids, "site list has fleet and field sites")

        # -- enrolment -------------------------------------------------------------
        r = analyst.post(f"{base}/api/devices/enrolment", timeout=5,
                         json={"site_id": "kabwe_test", "label": "Main incomer"})
        check(r.status_code == 201, "analyst issues an enrolment code")
        code = r.json()["code"]
        check(len(code) == 9 and code[4] == "-", f"code is human-friendly ({code})")
        check(r.json()["qr_payload"].startswith("amaka://enroll?code="), "QR payload returned")

        # -- simulator: enrol + back-fill + stream through an outage -----------------
        out = sim(base, tmp, "--device-id", "kit-0001", "--code", code.lower().replace("-", ""),
                  "--interval", "5", "--base-kw", "1800", "--backfill-hours", "30",
                  "--duration", "21", "--outage-at", "4", "--outage-for", "9")
        check("Enrolled kit-0001" in out, "kit enrols with the one-time code")
        check("Back-filling" in out and "accepted" in out, "kit back-fills 30 h of history")
        check("OFFLINE | buffered" in out, "kit buffers readings during the outage")
        check("flushed backlog" in out, "kit flushes the backlog when the link returns")
        check(not (tmp / ".device_sim" / "kit-0001.buffer.jsonl").exists(), "buffer is empty afterwards")

        r = requests.post(f"{base}/api/devices/enroll", timeout=5,
                          json={"code": code, "device_id": "kit-0002"})
        check(r.status_code == 401, "an enrolment code works only once")

        # duplicates are ignored (store-and-forward re-sends)
        token = json.loads((tmp / ".device_sim" / "kit-0001.json").read_text())["token"]
        dev = requests.Session()
        dev.headers["Authorization"] = f"Bearer {token}"
        batch = [{"ts": "2026-01-01T10:00:00+02:00", "kw": 1500},
                 {"ts": "2026-01-01T10:00:00+02:00", "kw": 1500},
                 {"ts": "garbage", "kw": 1},
                 {"ts": "2026-01-01T10:01:00+02:00", "kw": -5}]
        res = dev.post(f"{base}/api/ingest", json={"readings": batch}, timeout=5).json()
        check(res["accepted"] == 1 and res["duplicates"] == 1 and res["rejected"] == 2,
              "ingest dedups and rejects bad rows with reasons")
        future = dev.post(f"{base}/api/ingest", timeout=5, json={"readings": [
            {"ts": time.time() + 3600, "kw": 10}]}).json()
        check(future["rejected"] == 1, "future timestamps are rejected (gateway clock check)")

        # -- device health -------------------------------------------------------------
        devs = analyst.get(f"{base}/api/devices", params={"site": "kabwe_test"}, timeout=5).json()["devices"]
        kit = next(d for d in devs if d["id"] == "kit-0001")
        check(kit["status"] == "online", "kit shows online")
        check(kit["readings_total"] > 30 * 3600 / 5 * 0.95, f"history stored ({kit['readings_total']} readings)")
        check(kit["last_kw"] and kit["last_kw"] > 0, "last reading is reported")

        # -- hourly roll-up -----------------------------------------------------------
        hr = analyst.get(f"{base}/api/live/sites/kabwe_test/hourly", params={"hours": 24}, timeout=10).json()
        rows = [x for x in hr["rows"] if x["mean_kw"] is not None]
        check(len(hr["rows"]) == 24, "hourly view returns 24 hours")
        check(hr["completeness_pct"] >= 90, f"completeness {hr['completeness_pct']}%")
        check(all(1000 < x["mean_kw"] < 4000 for x in rows), "hourly means are plausible")
        check(commander.get(f"{base}/api/live/sites/kabwe_test/hourly", timeout=5).status_code == 200,
              "every signed-in role can read live data")

        # -- fault injection: stuck meter ----------------------------------------------
        code2 = analyst.post(f"{base}/api/devices/enrolment", timeout=5,
                             json={"site_id": "arakan"}).json()["code"]
        sim(base, tmp, "--device-id", "kit-flat", "--code", code2, "--interval", "60",
            "--backfill-hours", "6", "--duration", "1", "--fault", "flatline")
        flat = analyst.get(f"{base}/api/live/sites/arakan/hourly", params={"hours": 6}, timeout=10).json()
        check(flat["flag_counts"]["flatline"] >= 4, f"stuck meter flagged as flatline ({flat['flag_counts']})")

        # -- CSV upload fallback ------------------------------------------------------
        csv = "Timestamp,Load_kW\n" + "\n".join(
            f"2025-11-0{d} {h:02d}:00,{1200 + h * 10}" for d in (1, 2) for h in range(24)) + "\nbad,row\n"
        r = analyst.post(f"{base}/api/live/sites/kohima/upload", data=csv.encode(),
                         headers={"Content-Type": "text/csv"}, timeout=10)
        check(r.status_code == 200 and r.json()["accepted"] == 48 and r.json()["rejected"] == 1,
              "CSV upload stores 48 hourly rows and rejects 1 bad row")
        check(commander.post(f"{base}/api/live/sites/kohima/upload", data=csv.encode(),
                             timeout=5).status_code == 403, "commander cannot upload CSV")
        bad = analyst.post(f"{base}/api/live/sites/kohima/upload", data=b"a,b\n1,2\n", timeout=5)
        check(bad.status_code == 400 and "timestamp column" in bad.json()["detail"],
              "CSV without the right columns explains what it needs")

        # -- revoke -----------------------------------------------------------------
        check(analyst.delete(f"{base}/api/devices/kit-0001", timeout=5).status_code == 200,
              "analyst revokes the kit")
        check(dev.post(f"{base}/api/ingest", timeout=5, json={"readings": [
            {"ts": time.time(), "kw": 10}]}).status_code == 401, "revoked kit is locked out")

        print("\nALL CHECKS PASSED")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
