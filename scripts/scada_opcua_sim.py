"""Simulated site SCADA server (OPC UA) for AMAKA demos and tests.

Stands in for a real SCADA / building-management system so the connector
(scripts/scada_connector.py) can be shown end to end without plant access.

Address space (namespace "urn:amaka:scada-sim"):

    Objects/
      AMAKA_Sim/
        <site_id>/                      one folder per --site
          ActivePower_kW     Double    total site import, updated every second
          EnergyImport_kWh   Double    cumulative energy counter
          Voltage_V          Double    mean phase-to-phase voltage
          PowerFactor        Double
          Quality            String    "GOOD" | "BAD_STUCK" (with --fault flatline)

Node ids are strings, e.g. ``ns=2;s=kohima.ActivePower_kW`` — that is what you
give the connector. Load follows the same occupancy profile as the meter-kit
simulator (shifts, evening residential peak, quieter weekends).

Security: by default the endpoint offers None (demo on localhost). With
``--secure`` it offers only Basic256Sha256 Sign&Encrypt and needs a server
certificate/key (``--cert``/``--key``), which is how a real SCADA endpoint
should be configured.

Example:
    python scripts/scada_opcua_sim.py --site kohima --base-kw 2000 --site arakan --base-kw 1800
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

from asyncua import Server, ua

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device_sim import LoadModel  # noqa: E402  (same load profile as the kits)

NAMESPACE = "urn:amaka:scada-sim"


async def main() -> int:
    ap = argparse.ArgumentParser(description="AMAKA simulated SCADA server (OPC UA)")
    ap.add_argument("--endpoint", default="opc.tcp://127.0.0.1:4840/amaka/")
    ap.add_argument("--site", action="append", required=True, help="site id (repeatable)")
    ap.add_argument("--base-kw", action="append", type=float,
                    help="base load per --site (same order); default 1500")
    ap.add_argument("--fault", choices=["flatline"], help="make the first site's meter stick")
    ap.add_argument("--secure", action="store_true", help="Basic256Sha256 Sign&Encrypt only")
    ap.add_argument("--cert", type=Path, help="server certificate (DER/PEM) for --secure")
    ap.add_argument("--key", type=Path, help="server private key (PEM) for --secure")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    server = Server()
    await server.init()
    server.set_endpoint(args.endpoint)
    server.set_server_name("AMAKA Simulated Site SCADA")
    if args.secure:
        if not (args.cert and args.key):
            ap.error("--secure needs --cert and --key")
        await server.load_certificate(str(args.cert))
        await server.load_private_key(str(args.key))
        server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
    else:
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    idx = await server.register_namespace(NAMESPACE)

    root = await server.nodes.objects.add_folder(idx, "AMAKA_Sim")
    bases = args.base_kw or []
    points = []
    for i, site in enumerate(args.site):
        base = bases[i] if i < len(bases) else 1500.0
        folder = await root.add_folder(idx, site)
        nodes = {}
        for name, init in (("ActivePower_kW", 0.0), ("EnergyImport_kWh", 0.0),
                           ("Voltage_V", 400.0), ("PowerFactor", 0.94)):
            nodes[name] = await folder.add_variable(
                ua.NodeId(f"{site}.{name}", idx), name, ua.Variant(init, ua.VariantType.Double))
        nodes["Quality"] = await folder.add_variable(
            ua.NodeId(f"{site}.Quality", idx), "Quality", ua.Variant("GOOD", ua.VariantType.String))
        fault = args.fault if i == 0 else None
        model = LoadModel(base, base * 0.6, seed=zlib.crc32(site.encode()) & 0xFFFF, fault=fault)
        points.append((site, nodes, model, fault))
        print(f"  {site:<12} ns={idx};s={site}.ActivePower_kW   base {base:.0f} kW"
              + (f"  fault={fault}" if fault else ""))

    print(f"AMAKA SCADA sim on {args.endpoint} "
          f"({'Basic256Sha256 Sign&Encrypt' if args.secure else 'no security'}). Ctrl+C to stop.")
    async with server:
        energy = {site: 0.0 for site, *_ in points}
        while True:
            now = datetime.now(timezone.utc)
            for site, nodes, model, fault in points:
                kw = model.kw(now)
                energy[site] += kw / 3600.0
                await nodes["ActivePower_kW"].write_value(kw)
                await nodes["EnergyImport_kWh"].write_value(round(energy[site], 3))
                await nodes["Voltage_V"].write_value(round(400 * (1 + model.rng.gauss(0, 0.008)), 1))
                await nodes["PowerFactor"].write_value(round(min(1.0, 0.93 + model.rng.gauss(0, 0.01)), 3))
                await nodes["Quality"].write_value("BAD_STUCK" if fault else "GOOD")
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
