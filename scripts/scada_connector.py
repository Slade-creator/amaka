"""AMAKA SCADA connector — OPC UA client → AMAKA ingest API.

Runs on a small machine inside the site network (next to the SCADA / BMS
server). It reads the site's active-power tag over OPC UA and forwards the
readings to AMAKA exactly like a meter kit: it enrols once with the one-time
code (or QR) an analyst issues in the app, then posts batches to /api/ingest
with its device token. Readings are buffered on disk while the link to AMAKA is
down and re-sent in order afterwards (the server drops duplicates).

Why OPC UA: it is the standard vendor-neutral interface that modern SCADA and
building-management systems expose for reading live values. A Modbus TCP or
historian-export source would replace only ``read_kw()`` below — enrolment,
buffering, quality flags and forecasting stay the same.

Read-only by design: the connector only reads values; it never writes to the
SCADA system. Use a dedicated read-only OPC UA user on the plant side.

Examples (prototype root, API running, simulator from scripts/scada_opcua_sim.py):

    # first run: enrol with the code from the app
    python scripts/scada_connector.py --server http://127.0.0.1:8000 \
        --opcua opc.tcp://127.0.0.1:4840/amaka/ --node "ns=2;s=kohima.ActivePower_kW" \
        --code K7Q4-M2XP --device-id scada-kohima --interval 10

    # later runs resume from the saved token
    python scripts/scada_connector.py --opcua opc.tcp://127.0.0.1:4840/amaka/ \
        --node "ns=2;s=kohima.ActivePower_kW" --device-id scada-kohima

    # production-style endpoint: signed + encrypted session with a client cert
    python scripts/scada_connector.py ... --security "Basic256Sha256,SignAndEncrypt,client.der,client.pem" \
        --opcua-user amaka_reader --opcua-password-env AMAKA_OPCUA_PASSWORD
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from asyncua import Client, ua

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device_sim import Gateway  # noqa: E402  (enrolment + store-and-forward)

HARDWARE = "AMAKA SCADA connector | OPC UA client"


class Connector(Gateway):
    """A Gateway whose readings come from an OPC UA tag instead of a meter."""

    def enroll(self, code: str, interval: int) -> None:
        r = requests.post(f"{self.server}/api/devices/enroll", timeout=10, json={
            "code": code, "device_id": self.device_id, "interval_s": interval,
            "hardware": HARDWARE,
        })
        if r.status_code != 201:
            sys.exit(f"Enrolment failed (HTTP {r.status_code}): {r.text}")
        body = r.json()
        self.token, self.interval, self.site = body["device_token"], body["interval_s"], body["site"]
        self.save()
        print(f"Enrolled {self.device_id} -> {self.site['label']} ({self.site['id']}). "
              f"Token saved to {self.state_path}")


async def read_kw(client: Client, node_id: str, quality_id: str | None) -> tuple[float | None, str]:
    """One reading. Returns (kW or None, status text)."""
    dv = await client.get_node(node_id).read_data_value()
    if not dv.StatusCode.is_good():
        return None, f"bad OPC UA status {dv.StatusCode.name}"
    if quality_id:
        q = await client.get_node(quality_id).read_value()
        if isinstance(q, str) and q.upper() != "GOOD":
            # Still forward it: AMAKA's quality rules flag stuck meters itself,
            # and the analyst needs to see the fault, not a silent gap.
            return float(dv.Value.Value), f"SCADA quality {q}"
    return float(dv.Value.Value), "ok"


async def run(args: argparse.Namespace, gw: Connector) -> None:
    client = Client(args.opcua, timeout=10)
    if args.security:
        await client.set_security_string(args.security)
    if args.opcua_user:
        client.set_user(args.opcua_user)
        pw = os.environ.get(args.opcua_password_env or "", "")
        if not pw:
            sys.exit(f"Set the OPC UA password in ${args.opcua_password_env}")
        client.set_password(pw)

    batch: list[dict] = []
    last_send = time.monotonic()
    while True:
        try:
            async with client:
                print(f"Connected to {args.opcua}; reading {args.node} every {gw.interval} s")
                while True:
                    kw, status = await read_kw(client, args.node, args.quality_node)
                    ts = datetime.now(timezone.utc)
                    if kw is not None and kw >= 0:
                        batch.append({"ts": ts.isoformat().replace("+00:00", "Z"), "kw": round(kw, 2)})
                    if time.monotonic() - last_send >= args.send_every or len(batch) >= 500:
                        result = gw.send(batch, link_up=True) if batch else "nothing to send"
                        print(f"{ts.astimezone():%H:%M:%S}  {kw if kw is not None else '—':>10} kW  "
                              f"{status} | {result}")
                        batch, last_send = [], time.monotonic()
                    await asyncio.sleep(gw.interval)
        except (OSError, asyncio.TimeoutError, ua.UaError) as exc:
            # SCADA link down: keep what we have, retry the OPC UA session.
            if batch:
                gw.buffer(batch)
                batch = []
            print(f"OPC UA link error ({exc.__class__.__name__}: {exc}); retrying in 10 s")
            await asyncio.sleep(10)
        if args.duration and time.monotonic() - args.started > args.duration:
            return


def main() -> int:
    ap = argparse.ArgumentParser(description="AMAKA SCADA connector (OPC UA → AMAKA)")
    ap.add_argument("--server", default="http://127.0.0.1:8000", help="AMAKA API origin")
    ap.add_argument("--opcua", required=True, help="OPC UA endpoint, e.g. opc.tcp://host:4840/")
    ap.add_argument("--node", required=True, help='active-power node id, e.g. "ns=2;s=kohima.ActivePower_kW"')
    ap.add_argument("--quality-node", help="optional quality/status tag to log")
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--code", help="one-time enrolment code (first run only)")
    ap.add_argument("--interval", type=int, default=10, help="seconds between reads")
    ap.add_argument("--send-every", type=int, default=30, help="seconds between uploads")
    ap.add_argument("--security", help='asyncua security string, e.g. "Basic256Sha256,SignAndEncrypt,cert.der,key.pem"')
    ap.add_argument("--opcua-user")
    ap.add_argument("--opcua-password-env", default="AMAKA_OPCUA_PASSWORD")
    ap.add_argument("--duration", type=int, default=0, help="stop after N seconds (0 = forever)")
    args = ap.parse_args()
    args.started = time.monotonic()

    gw = Connector(args.server, args.device_id)
    if not gw.load():
        if not args.code:
            sys.exit("First run needs --code (issue one in the app: More → Data sources → Add meter kit).")
        gw.enroll(args.code, args.interval)
    if args.quality_node is None and ";s=" in args.node and args.node.endswith(".ActivePower_kW"):
        args.quality_node = args.node.replace(".ActivePower_kW", ".Quality")
    print(f"Connector {args.device_id} -> {gw.site['label']}")

    async def bounded() -> None:
        if args.duration:
            try:
                await asyncio.wait_for(run(args, gw), timeout=args.duration)
            except asyncio.TimeoutError:
                pass
        else:
            await run(args, gw)

    try:
        asyncio.run(bounded())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
