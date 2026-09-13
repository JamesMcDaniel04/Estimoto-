"""Publish all Plus Android assets, then advance the permanent download link."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import httpx

from estimoto_plus.android_download import CERTIFICATE_SHA256
from scripts.publish_android_current import inspect_apk


ROOT = Path(__file__).resolve().parents[2]
REPO = "JamesMcDaniel04/Estimoto-"
API = "https://api.github.com/repos/JamesMcDaniel04/Estimoto-"
PLUS_API = "https://estimoto-plus-api.fly.dev"


def asset_names(version: str, code: int) -> tuple[str, str, str]:
    stem = f"estimoto-plus-{version}-{code}"
    return f"{stem}.apk", f"{stem}.aab", "SHA256SUMS"


def digest_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checksum_text(apk: Path, aab: Path, names: tuple[str, str, str]) -> str:
    return f"{digest_file(apk)}  {names[0]}\n{digest_file(aab)}  {names[1]}\n"


def check_existing_assets(assets: list[dict], expected: dict[str, tuple[int, str]]) -> list[str]:
    seen: set[str] = set()
    for asset in assets:
        name = asset.get("name")
        if name not in expected:
            continue
        if name in seen:
            raise ValueError(f"Existing release has duplicate asset {name}")
        seen.add(name)
        size, digest = expected[name]
        if asset.get("size") != size or asset.get("digest") != f"sha256:{digest}":
            raise ValueError(f"Existing release asset {name} mismatches signed local artifact; refusing overwrite")
    return [name for name in expected if name not in seen]


@contextmanager
def release_lock(path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Android release publisher is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def verify_aab(aab: Path) -> None:
    if not aab.is_file() or not 1_000_000 <= aab.stat().st_size <= 200_000_000:
        raise ValueError("AAB is missing or outside release size limits")
    with zipfile.ZipFile(aab) as archive:
        if "base/manifest/AndroidManifest.xml" not in archive.namelist():
            raise ValueError("AAB has no base Android manifest")
    subprocess.run(["jarsigner", "-verify", "-strict", str(aab)],
                   check=True, capture_output=True, text=True)
    cert = subprocess.run(["keytool", "-printcert", "-jarfile", str(aab)],
                          check=True, capture_output=True, text=True).stdout
    found = re.search(r"SHA256:\s*([0-9A-Fa-f:]{95})", cert)
    if found is None or found.group(1).replace(":", "").lower() != CERTIFICATE_SHA256:
        raise ValueError("AAB is not signed by the Plus release certificate")


def verify_source_version(manifest: dict) -> None:
    pubspec = (ROOT / "app/pubspec.yaml").read_text()
    match = re.search(r"^version:\s*([^\s+]+)\+(\d+)\s*$", pubspec, re.MULTILINE)
    if not match or (match.group(1), int(match.group(2))) != (
        manifest["version_name"], manifest["version_code"]
    ):
        raise ValueError("Signed APK version differs from current app/pubspec.yaml")


def get_release(client: httpx.Client, tag: str) -> dict | None:
    response = client.get(f"{API}/releases/tags/{tag}", headers={"Accept": "application/vnd.github+json"})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    release = response.json()
    if release.get("tag_name") != tag or release.get("draft") or not release.get("prerelease"):
        raise ValueError("Existing release has unexpected tag or publication state")
    return release


def verify_public_asset(client: httpx.Client, tag: str, name: str, expected: tuple[int, str]) -> None:
    size_expected, digest_expected = expected
    size, digest = 0, hashlib.sha256()
    url = f"https://github.com/{REPO}/releases/download/{tag}/{name}"
    with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > 200_000_000:
                raise ValueError(f"Public asset {name} exceeds release size limit")
            digest.update(chunk)
    if size != size_expected or digest.hexdigest() != digest_expected:
        raise ValueError(f"Public asset {name} does not match the local signed release")


def run_gh(args: list[str]) -> None:
    completed = subprocess.run(["gh", *args], capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(f"GitHub release command failed ({completed.returncode}); current pointer unchanged")


def publish(args) -> None:
    with release_lock(Path.home() / ".config/estimoto-plus/android-publish.lock"):
        if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout:
            raise ValueError("Commit the source before publishing Android artifacts")
        manifest = inspect_apk(args.apk)
        verify_aab(args.aab)
        verify_source_version(manifest)
        if not args.notes.is_file() or not 1 <= args.notes.stat().st_size <= 32_000:
            raise ValueError("A nonempty release notes file is required")
        names = asset_names(manifest["version_name"], manifest["version_code"])
        sums = checksum_text(args.apk, args.aab, names)
        if args.sums is not None and args.sums.read_text() != sums:
            raise ValueError("Provided SHA256SUMS does not match both signed artifacts")
        tag = f"v{manifest['version_name']}-beta.{manifest['version_code']}"
        with tempfile.TemporaryDirectory(prefix="estimoto-plus-android-release-") as temp:
            directory = Path(temp)
            staged = {names[0]: directory / names[0], names[1]: directory / names[1], names[2]: directory / names[2]}
            shutil.copyfile(args.apk, staged[names[0]])
            shutil.copyfile(args.aab, staged[names[1]])
            staged[names[2]].write_text(sums)
            expected = {name: (path.stat().st_size, digest_file(path)) for name, path in staged.items()}
            with httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False) as client:
                release = get_release(client, tag)
                missing = check_existing_assets(release.get("assets", []) if release else [], expected)
                if args.dry_run:
                    print(json.dumps({"status": "dry-run", "tag": tag, "missing_assets": missing,
                                      "apk_sha256": manifest["sha256"]}))
                    return
                if release is None:
                    source_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                capture_output=True, text=True, check=True).stdout.strip()
                    run_gh(["release", "create", tag, *(str(staged[name]) for name in names),
                            "-R", REPO, "--title", f"Estimoto + {manifest['version_name']} ({manifest['version_code']})",
                            "--notes-file", str(args.notes), "--prerelease", "--target", source_sha])
                elif missing:
                    run_gh(["release", "upload", tag, *(str(staged[name]) for name in missing), "-R", REPO])
                release = get_release(client, tag)
                if release is None or check_existing_assets(release.get("assets", []), expected):
                    raise RuntimeError("Published GitHub release is incomplete; current pointer unchanged")
                for name in names:
                    verify_public_asset(client, tag, name, expected[name])
        subprocess.run([sys.executable, str(ROOT / "backend/scripts/publish_android_current.py"),
                        "--apk", str(args.apk)], cwd=ROOT / "backend",
                       env={**os.environ, "PYTHONPATH": str(ROOT / "backend")}, check=True)
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            for attempt in range(13):
                current = client.get(f"{PLUS_API}/android/current")
                download = client.get(f"{PLUS_API}/android/download")
                if (current.status_code == 200 and download.status_code == 307
                    and current.json().get("sha256") == manifest["sha256"]
                    and current.json().get("version_code") == manifest["version_code"]
                    and download.headers.get("location") == manifest["asset_url"]):
                    print(json.dumps({"status": "current", "tag": tag,
                                      "apk_sha256": manifest["sha256"], "stable_url": f"{PLUS_API}/android/download"}))
                    return
                if attempt < 12:
                    time.sleep(5)
        raise RuntimeError("Remote pointer changed, but stable Plus API has not verified the new release")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, default=ROOT / "app/build/app/outputs/flutter-apk/app-release.apk")
    parser.add_argument("--aab", type=Path, default=ROOT / "app/build/app/outputs/bundle/release/app-release.aab")
    parser.add_argument("--sums", type=Path, help="Optional existing SHA256SUMS; must match exactly")
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Verify local and existing release assets without mutation")
    args = parser.parse_args()
    args.apk, args.aab, args.notes = args.apk.resolve(), args.aab.resolve(), args.notes.resolve()
    publish(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
