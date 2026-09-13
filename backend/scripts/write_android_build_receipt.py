"""Record the clean source and exact Android artifacts immediately after a live build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def make_receipt(source_sha: str, apk: Path, aab: Path) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("Source SHA must be a full git commit hash")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    if head != source_sha:
        raise ValueError("Source commit changed while Android artifacts were building")
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                      capture_output=True, text=True, check=True).stdout:
        raise ValueError("Source changed while Android artifacts were building")
    if not apk.is_file() or not aab.is_file():
        raise ValueError("Both signed Android artifacts must exist before receipt creation")
    return {"schema": 1, "source_sha": source_sha,
            "apk_sha256": file_hash(apk), "aab_sha256": file_hash(aab)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--apk", type=Path, default=ROOT / "app/build/app/outputs/flutter-apk/app-release.apk")
    parser.add_argument("--aab", type=Path, default=ROOT / "app/build/app/outputs/bundle/release/app-release.aab")
    parser.add_argument("--output", type=Path, default=ROOT / "app/build/android-build-receipt.json")
    args = parser.parse_args()
    receipt = make_receipt(args.source_sha, args.apk, args.aab)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=args.output.parent, delete=False) as target:
        temporary = Path(target.name)
        try:
            json.dump(receipt, target, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fchmod(target.fileno(), 0o600)
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Android build receipt recorded for {args.source_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
