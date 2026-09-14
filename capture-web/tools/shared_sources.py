"""Verify/copy exact original capture UI sources into a self-contained Plus build."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "dashboard/src/pages/intake/GuidedCamera.tsx": "src/shared/GuidedCamera.tsx",
    "dashboard/src/pages/intake/VehicleGuide.tsx": "src/shared/VehicleGuide.tsx",
    "dashboard/src/pages/intake/vehicleScene.ts": "src/shared/vehicleScene.ts",
    "dashboard/src/pages/intake/template.ts": "src/shared/template.ts",
    "dashboard/src/index.css": "src/shared/camera.css",
}
MARKER = b".customer-camera {"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derived(source: str, data: bytes) -> bytes:
    if source.endswith("index.css"):
        point = data.find(MARKER)
        if point < 0:
            raise ValueError("Original camera CSS marker is missing")
        return data[point:]
    return data


def git(source_root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source_root), *args], text=True).strip()


def sync(source_root: Path, destination: Path = ROOT) -> dict:
    source_root = source_root.resolve()
    if not (source_root / "dashboard/src/pages/intake/GuidedCamera.tsx").is_file():
        raise ValueError("Pass the original Estimoto repository root")
    if subprocess.call(["git", "-C", str(source_root), "diff", "--quiet", "HEAD", "--", *SOURCES],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        raise ValueError("Commit original capture sources before syncing")
    commit = git(source_root, "rev-parse", "HEAD")
    if len(commit) != 40:
        raise ValueError("Original source commit is invalid")
    entries = []
    for source, target in SOURCES.items():
        raw = (source_root / source).read_bytes()
        rendered = derived(source, raw)
        target_path = destination / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(rendered)
        entries.append({"source": source, "target": target, "source_sha256": sha(raw), "target_sha256": sha(rendered)})
    manifest = {"source_repository": "Estimoto", "source_commit": commit, "files": entries}
    (destination / "source-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify(destination: Path = ROOT) -> dict:
    manifest = json.loads((destination / "source-manifest.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("source_repository") != "Estimoto" or not isinstance(manifest.get("source_commit"), str) or len(manifest["source_commit"]) != 40:
        raise ValueError("Capture source manifest is invalid")
    rows = manifest.get("files")
    if not isinstance(rows, list) or {row.get("source") for row in rows if isinstance(row, dict)} != set(SOURCES):
        raise ValueError("Capture source manifest has missing or extra files")
    for row in rows:
        if row.get("target") != SOURCES[row["source"]] or not isinstance(row.get("target_sha256"), str):
            raise ValueError("Capture source manifest has invalid targets")
        target = destination / row["target"]
        if not target.is_file() or sha(target.read_bytes()) != row["target_sha256"]:
            raise ValueError(f"Vendored capture source differs: {row['target']}")
    return manifest


if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["sync"] and len(sys.argv) == 3:
            value = sync(Path(sys.argv[2]))
        elif sys.argv[1:] == ["verify"]:
            value = verify()
        else:
            raise ValueError("Usage: shared_sources.py sync ORIGINAL_REPO_ROOT | verify")
        print(f"Capture sources verified at original commit {value['source_commit']}")
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Capture source check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
