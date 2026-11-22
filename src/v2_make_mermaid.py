"""
Render Mermaid diagrams to PNG using mermaid.ink (no local Chromium needed).

Usage:
    python src/v2_make_mermaid.py
"""
from __future__ import annotations

import base64
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "diagrams"
OUT = ROOT / "docs" / "figures"

MAP = {
    "pipeline.mmd": "fig_3_2_data_prep.png",
    "context.mmd": "fig_3_3_grid_logic.png",
    "telemetry.mmd": "fig_3_4_telemetry.png",
    "hybrid.mmd": "fig_3_5_hybrid_model.png",
    "timeline.mmd": "fig_3_6_timeline.png",
}


def render(code: str) -> bytes:
    encoded = base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii")
    url = f"https://mermaid.ink/img/{encoded}?type=png&bgColor=white"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"mermaid.ink returned {r.headers.get('content-type')}: {r.text[:200]}")
    return r.content


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, out_name in MAP.items():
        code = (SRC / name).read_text(encoding="utf-8")
        print(f"rendering {name} ...", flush=True)
        try:
            data = render(code)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue
        path = OUT / out_name
        path.write_bytes(data)
        print(f"  -> {path.name} ({len(data)} bytes)", flush=True)


if __name__ == "__main__":
    main()
