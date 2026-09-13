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
BUNDLETOOL_VERSION = "1.18.3"
BUNDLETOOL_SHA256 = "a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29"
BUNDLETOOL_SIZE = 32_520_401


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


def check_release_source(release: dict, source_sha: str) -> None:
    if release.get("target_commitish") != source_sha:
        raise ValueError("Existing release tag represents a different source commit")


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


def bundletool_jar() -> Path:
    jar = Path(os.environ.get("BUNDLETOOL_JAR", str(
        Path.home() / f".cache/estimoto-plus/tools/bundletool-all-{BUNDLETOOL_VERSION}.jar"
    )))
    if not jar.is_file():
        if "BUNDLETOOL_JAR" in os.environ:
            raise ValueError("Configured bundletool JAR does not exist")
        jar.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        url = ("https://github.com/google/bundletool/releases/download/"
               f"{BUNDLETOOL_VERSION}/bundletool-all-{BUNDLETOOL_VERSION}.jar")
        with tempfile.NamedTemporaryFile(dir=jar.parent, delete=False) as target:
            temporary = Path(target.name)
            try:
                with httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > BUNDLETOOL_SIZE:
                                raise ValueError("bundletool download exceeds pinned size")
                            target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
                if size != BUNDLETOOL_SIZE or digest_file(temporary) != BUNDLETOOL_SHA256:
                    raise ValueError("bundletool download differs from pinned official release")
                os.replace(temporary, jar)
            finally:
                temporary.unlink(missing_ok=True)
    if jar.stat().st_size != BUNDLETOOL_SIZE or digest_file(jar) != BUNDLETOOL_SHA256:
        raise ValueError("bundletool JAR differs from pinned official release")
    return jar


def verify_aab(aab: Path, apk_manifest: dict) -> None:
    if not aab.is_file() or not 1_000_000 <= aab.stat().st_size <= 200_000_000:
        raise ValueError("AAB is missing or outside release size limits")
    with zipfile.ZipFile(aab) as archive:
        if "base/manifest/AndroidManifest.xml" not in archive.namelist():
            raise ValueError("AAB has no base Android manifest")
    # Android release keys are self-signed. -strict additionally demands a
    # public PKIX chain and a timestamp, so it rejects a valid release AAB.
    verification = subprocess.run(["jarsigner", "-verify", str(aab)],
                                  check=True, capture_output=True, text=True)
    verification_output = f"{verification.stdout}\n{verification.stderr}".lower()
    if "unsigned" in verification_output:
        raise ValueError("AAB contains unsigned entries")
    if "jar verified" not in verification_output:
        raise ValueError("AAB signature verification did not complete")
    cert = subprocess.run(["keytool", "-printcert", "-jarfile", str(aab)],
                          check=True, capture_output=True, text=True).stdout
    found = re.search(r"SHA256:\s*([0-9A-Fa-f:]{95})", cert)
    if found is None or found.group(1).replace(":", "").lower() != CERTIFICATE_SHA256:
        raise ValueError("AAB is not signed by the Plus release certificate")

    jar = bundletool_jar()
    values = []
    for xpath in ("/manifest/@package", "/manifest/@android:versionCode", "/manifest/@android:versionName"):
        output = subprocess.run(
            ["java", "-jar", str(jar), "dump", "manifest", f"--bundle={aab}", f"--xpath={xpath}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        values.append(output)
    package, code, version = values
    if (package != apk_manifest["package"] or not code.isdecimal()
        or int(code) != apk_manifest["version_code"] or version != apk_manifest["version_name"]):
        raise ValueError("AAB manifest differs from signed APK package/version")


def verify_build_receipt(receipt_path: Path, apk: Path, aab: Path) -> str:
    if not receipt_path.is_file() or receipt_path.stat().st_size > 4096:
        raise ValueError("Clean-build Android receipt is missing or invalid")
    try:
        receipt = json.loads(receipt_path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Clean-build Android receipt is invalid") from exc
    if not isinstance(receipt, dict) or set(receipt) != {"schema", "source_sha", "apk_sha256", "aab_sha256"}:
        raise ValueError("Clean-build Android receipt has unexpected fields")
    source_sha = receipt["source_sha"]
    if (receipt["schema"] != 1 or not isinstance(source_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None):
        raise ValueError("Clean-build Android receipt has invalid source commit")
    for name, path in (("APK", apk), ("AAB", aab)):
        if receipt[f"{name.lower()}_sha256"] != digest_file(path):
            raise ValueError(f"{name} hash differs from clean-build receipt")
    return source_sha


def release_target(source_sha: str, *, current_head: str) -> str:
    # A later docs commit must not change the source commit represented by the artifacts.
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("Invalid receipt source commit")
    return source_sha


def verify_source_version(manifest: dict, source_sha: str) -> None:
    commit = subprocess.run(["git", "cat-file", "-t", source_sha], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    if commit != "commit":
        raise ValueError("Build receipt source is not a git commit")
    pubspec = subprocess.run(["git", "show", f"{source_sha}:app/pubspec.yaml"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    match = re.search(r"^version:\s*([^\s+]+)\+(\d+)\s*$", pubspec, re.MULTILINE)
    if not match or (match.group(1), int(match.group(2))) != (
        manifest["version_name"], manifest["version_code"]
    ):
        raise ValueError("Signed APK version differs from build receipt source app/pubspec.yaml")


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
        verify_aab(args.aab, manifest)
        source_sha = verify_build_receipt(args.receipt, args.apk, args.aab)
        verify_source_version(manifest, source_sha)
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
                if release is not None:
                    check_release_source(release, source_sha)
                missing = check_existing_assets(release.get("assets", []) if release else [], expected)
                if args.dry_run:
                    print(json.dumps({"status": "dry-run", "tag": tag, "missing_assets": missing,
                                      "apk_sha256": manifest["sha256"]}))
                    return
                if release is None:
                    current_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                  capture_output=True, text=True, check=True).stdout.strip()
                    run_gh(["release", "create", tag, *(str(staged[name]) for name in names),
                            "-R", REPO, "--title", f"Estimoto + {manifest['version_name']} ({manifest['version_code']})",
                            "--notes-file", str(args.notes), "--prerelease", "--target",
                            release_target(source_sha, current_head=current_head)])
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
    parser.add_argument("--receipt", type=Path, default=ROOT / "app/build/android-build-receipt.json",
                        help="Clean-build receipt generated by scripts/build_live.sh mobile/all")
    parser.add_argument("--dry-run", action="store_true", help="Verify local and existing release assets without mutation")
    args = parser.parse_args()
    args.apk, args.aab, args.notes, args.receipt = (
        args.apk.resolve(), args.aab.resolve(), args.notes.resolve(), args.receipt.resolve()
    )
    publish(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
