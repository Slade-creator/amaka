"""Build and deploy the AMAKA backend to AWS Lambda (zip + Mangum, no Docker).

    python deploy/deploy_backend.py            # build, upload, update function
    python deploy/deploy_backend.py --build-only

Needs: `aws login` done, Python with pip. Environment variables on the function
(JWT secret, allowed origins, /tmp paths) are left untouched.
Override defaults with AMAKA_REGION / AMAKA_FUNCTION / AMAKA_BUCKET.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGION = os.environ.get("AMAKA_REGION", "eu-north-1")
FUNCTION = os.environ.get("AMAKA_FUNCTION", "amaka-api")
BUCKET = os.environ.get("AMAKA_BUCKET", "amaka-deploy-866874944490-eu-north-1")
LIMIT_MB = 250

# Model binaries are not used by the dashboard endpoints; keep only the metrics file.
KEEP_IN_CONFIG_V2 = {"metrics_midterm.csv"}


def run(*cmd: str) -> str:
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def build(stage: Path) -> Path:
    pkg = stage / "pkg"
    pkg.mkdir()
    print("Installing Linux wheels...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "deploy" / "requirements-lambda.txt"),
         "--platform", "manylinux2014_x86_64", "--python-version", "3.13", "--implementation", "cp",
         "--only-binary=:all:", "--target", str(pkg)], check=True)
    for d in ("backend", "src"):
        shutil.copytree(ROOT / d, pkg / d)
    shutil.copytree(ROOT / "data" / "v2", pkg / "data" / "v2")
    shutil.copytree(ROOT / "data" / "raw", pkg / "data" / "raw")
    # config: json/csv only; no model binaries, no local accounts or secrets.
    cfg = pkg / "config"
    cfg.mkdir()
    for f in (ROOT / "config").iterdir():
        if f.is_file() and f.suffix in {".json", ".csv"} and f.name != "users.json":
            shutil.copy2(f, cfg / f.name)
    (cfg / "v2").mkdir()
    for name in KEEP_IN_CONFIG_V2:
        shutil.copy2(ROOT / "config" / "v2" / name, cfg / "v2" / name)
    for p in list(pkg.rglob("__pycache__")) + [p for p in pkg.rglob("*") if p.is_dir() and p.name in {"tests", "test", "sample_data"}]:
        shutil.rmtree(p, ignore_errors=True)
    size = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file()) / 1e6
    print(f"Unzipped size: {size:.0f} MB (limit {LIMIT_MB})")
    if size > LIMIT_MB:
        sys.exit("Package exceeds the Lambda size limit.")
    zpath = stage / "amaka.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in pkg.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(pkg))
    print(f"Zip: {zpath.stat().st_size / 1e6:.0f} MB")
    return zpath


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        zpath = build(Path(tmp))
        if "--build-only" in sys.argv:
            keep = ROOT / "amaka-lambda.zip"
            shutil.copy2(zpath, keep)
            print(f"Saved {keep}")
            return
        print("Uploading to S3...")
        run("aws", "s3", "cp", str(zpath), f"s3://{BUCKET}/amaka.zip", "--region", REGION, "--only-show-errors")
        print("Updating function...")
        run("aws", "lambda", "update-function-code", "--function-name", FUNCTION, "--region", REGION,
            "--s3-bucket", BUCKET, "--s3-key", "amaka.zip")
        run("aws", "lambda", "wait", "function-updated-v2", "--function-name", FUNCTION, "--region", REGION)
        url = run("aws", "lambda", "get-function-url-config", "--function-name", FUNCTION, "--region", REGION,
                  "--query", "FunctionUrl", "--output", "text")
        print(f"Deployed. {url}api/health")


if __name__ == "__main__":
    main()
