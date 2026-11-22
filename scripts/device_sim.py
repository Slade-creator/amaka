"""Portable meter kit simulator — stands in for real hardware in demos/tests.

A real kit is a clamp-on 3-phase energy meter (Modbus RS485) wired to a small
gateway (Raspberry Pi / ESP32) with 4G or Wi-Fi. This script behaves like the
gateway firmware:

  1. Enrols once with the one-time code an analyst issued (QR code in the app)
     and saves its device token, so later runs resume without a code.
  2. Optionally back-fills history (as if the kit had been logging offline).
  3. Streams one reading per interval, timestamped by the gateway clock.
  4. Store-and-forward: if the server is unreachable (or a simulated outage is
     running), readings go to a local buffer file and are re-sent in order once
     the link is back. The server ignores duplicates, so re-sending is safe.

Load model: base load + a double-hump weekday occupancy profile (morning and
afternoon shifts), lower at weekends, plus noise. Faults can be injected to
demonstrate the analyst's data-quality flags.

Examples (from the prototype root, with the API running):

    # first run: enrol with the code shown in the app, back-fill 2 days, stream
    python scripts/device_sim.py --server http://127.0.0.1:8000 --code K7Q4-M2XP \
        --device-id kit-0042 --base-kw 1400 --backfill-hours 48 --interval 10

    # later runs resume from the saved token
    python scripts/device_sim.py --device-id kit-0042 --interval 10

    # demo a 60 s link outage after 30 s, then the backlog upload
    python scripts/device_sim.py --device-id kit-0042 --interval 5 --outage-at 30 --outage-for 60

    # demo a stuck meter (flat line) for the data-quality view
    python scripts/device_sim.py --device-id kit-0042 --fault flatline
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

CAT = timezone(timedelta(hours=2))  # Zambia, no DST
STATE_DIR = Path(".device_sim")
BATCH = 500


# ---------------------------------------------------------------------------
# Load model
# ---------------------------------------------------------------------------

def occupancy(local: datetime) -> float:
    """0..1 activity: morning and afternoon shifts, quieter at weekends."""
    h = local.hour + local.minute / 60
    morning = math.exp(-((h - 9.5) ** 2) / 4.5)
    afternoon = math.exp(-((h - 15.0) ** 2) / 5.0)
    evening = 0.45 * math.exp(-((h - 19.5) ** 2) / 3.0)  # residential lighting / cooking
    level = max(morning, afternoon) + evening
    if local.weekday() >= 5:
        level *= 0.55
    return min(1.0, level)


class LoadModel:
    def __init__(self, base_kw: float, swing_kw: float, seed: int, fault: str | None):
        self.base = base_kw
        self.swing = swing_kw
        self.rng = random.Random(seed)
        self.fault = fault
        self._flat: float | None = None

    def kw(self, ts: datetime) -> float:
        local = ts.astimezone(CAT)
        value = self.base + self.swing * occupancy(local)
        value *= 1 + self.rng.gauss(0, 0.025)
        if self.fault == "flatline":
            if self._flat is None:
                self._flat = round(value, 1)
            return self._flat
        if self.fault == "zero":
            return 0.0
        if self.fault == "spike" and self.rng.random() < 0.05:
            value *= 6
        return round(max(0.0, value), 2)

    def reading(self, ts: datetime) -> dict:
        kw = self.kw(ts)
        return {
            "ts": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "kw": kw,
            "voltage_v": round(400 * (1 + self.rng.gauss(0, 0.01)), 1),
            "pf": round(min(1.0, 0.93 + self.rng.gauss(0, 0.015)), 3),
        }


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------

class Gateway:
    def __init__(self, server: str, device_id: str):
        self.server = server.rstrip("/")
        self.device_id = device_id
        STATE_DIR.mkdir(exist_ok=True)
        self.state_path = STATE_DIR / f"{device_id}.json"
        self.buffer_path = STATE_DIR / f"{device_id}.buffer.jsonl"
        self.token: str | None = None
        self.interval: int | None = None
        self.site: dict | None = None

    # -- state ----------------------------------------------------------------
    def load(self) -> bool:
        if not self.state_path.is_file():
            return False
        st = json.loads(self.state_path.read_text())
        self.token, self.interval, self.site = st["token"], st["interval_s"], st["site"]
        self.server = st.get("server", self.server)
        return True

    def save(self) -> None:
        self.state_path.write_text(json.dumps({
            "server": self.server, "device_id": self.device_id, "token": self.token,
            "interval_s": self.interval, "site": self.site,
        }, indent=2))

    # -- enrolment --------------------------------------------------------------
    def enroll(self, code: str, interval: int) -> None:
        r = requests.post(f"{self.server}/api/devices/enroll", timeout=10, json={
            "code": code, "device_id": self.device_id, "interval_s": interval,
            "hardware": "AMAKA kit sim | 3-phase CT meter (Modbus) + gateway",
        })
        if r.status_code != 201:
            sys.exit(f"Enrolment failed (HTTP {r.status_code}): {r.text}")
        body = r.json()
        self.token, self.interval, self.site = body["device_token"], body["interval_s"], body["site"]
        self.save()
        print(f"Enrolled {self.device_id} -> {self.site['label']} ({self.site['id']}). "
              f"Token saved to {self.state_path}")

    # -- buffer -----------------------------------------------------------------
    def buffered(self) -> list[dict]:
        if not self.buffer_path.is_file():
            return []
        return [json.loads(line) for line in self.buffer_path.read_text().splitlines() if line.strip()]

    def buffer(self, readings: list[dict]) -> None:
        with self.buffer_path.open("a") as f:
            for r in readings:
                f.write(json.dumps(r) + "\n")

    # -- upload -----------------------------------------------------------------
    def post(self, readings: list[dict]) -> dict:
        r = requests.post(f"{self.server}/api/ingest", timeout=15, json={"readings": readings},
                          headers={"Authorization": f"Bearer {self.token}"})
        if r.status_code == 401:
            sys.exit("Device token rejected (revoked?). Delete "
                     f"{self.state_path} and enrol again with a new code.")
        r.raise_for_status()
        return r.json()

    def send(self, readings: list[dict], link_up: bool) -> str:
        """Send backlog + new readings; on any failure keep them all buffered."""
        pending = self.buffered() + readings
        if not link_up:
            self.buffer(readings)
            return f"OFFLINE | buffered {len(pending)}"
        try:
            totals = {"accepted": 0, "duplicates": 0, "rejected": 0}
            for i in range(0, len(pending), BATCH):
                res = self.post(pending[i:i + BATCH])
                for k in totals:
                    totals[k] += res[k]
        except requests.RequestException as exc:
            self.buffer(readings)
            return f"link error ({exc.__class__.__name__}) | buffered {len(pending)}"
        self.buffer_path.unlink(missing_ok=True)
        flushed = len(pending) - len(readings)
        extra = f" | flushed backlog of {flushed}" if flushed else ""
        return (f"sent {len(pending)} | accepted {totals['accepted']}"
                f" | dup {totals['duplicates']} | rejected {totals['rejected']}{extra}")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="AMAKA portable meter kit simulator")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--device-id", required=True, help="stable kit id, e.g. kit-0042")
    ap.add_argument("--code", help="one-time enrolment code (first run only)")
    ap.add_argument("--interval", type=int, default=60, help="seconds between readings")
    ap.add_argument("--base-kw", type=float, default=1500.0)
    ap.add_argument("--swing-kw", type=float, default=None, help="occupancy swing (default 0.8 x base)")
    ap.add_argument("--backfill-hours", type=int, default=0, help="upload this much history first")
    ap.add_argument("--duration", type=int, default=0, help="stop after N seconds (0 = run until Ctrl+C)")
    ap.add_argument("--outage-at", type=int, default=None, help="simulate a link outage after N s")
    ap.add_argument("--outage-for", type=int, default=60)
    ap.add_argument("--fault", choices=["flatline", "zero", "spike"])
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    gw = Gateway(args.server, args.device_id)
    if not gw.load():
        if not args.code:
            sys.exit(f"No saved token for {args.device_id}. Pass --code with an enrolment code "
                     "from the app (Data sources -> Add meter kit).")
        gw.enroll(args.code, args.interval)
    elif args.code:
        print(f"{args.device_id} is already enrolled; ignoring --code (delete {gw.state_path} to re-enrol).")

    interval = gw.interval or args.interval
    model = LoadModel(args.base_kw, args.swing_kw if args.swing_kw is not None else 0.8 * args.base_kw,
                      args.seed, args.fault)
    print(f"Kit {gw.device_id} at {gw.site['label']} | one reading every {interval} s"
          + (f" | fault={args.fault}" if args.fault else ""))

    if args.backfill_hours > 0:
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=args.backfill_hours)
        n = int((now - start).total_seconds() // interval)
        history = [model.reading(start + timedelta(seconds=i * interval)) for i in range(n)]
        print(f"Back-filling {len(history)} readings ({args.backfill_hours} h)... ", end="", flush=True)
        print(gw.send(history, link_up=True))

    t0 = time.monotonic()
    try:
        while True:
            elapsed = time.monotonic() - t0
            if args.duration and elapsed >= args.duration:
                break
            outage = (args.outage_at is not None
                      and args.outage_at <= elapsed < args.outage_at + args.outage_for)
            reading = model.reading(datetime.now(timezone.utc))
            status = gw.send([reading], link_up=not outage)
            local = datetime.now(CAT).strftime("%H:%M:%S")
            print(f"{local}  {reading['kw']:>9,.1f} kW  {status}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        left = len(gw.buffered())
        print(f"\nStopped. {left} readings still buffered." if left else "\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
