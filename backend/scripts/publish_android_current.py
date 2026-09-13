"""Point the permanent Plus Android URL at a verified GitHub release APK.

Upload the signed APK to the matching GitHub release first. This script checks
the local package/signature and the public bytes, then replaces only the tiny
Supabase current.json pointer. It never uploads an APK or sends an email.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

from estimoto_plus.android_download import (
    BUCKET, CERTIFICATE_SHA256, public_object_url, validate_manifest,
)


MAX_APK_BYTES = 200_000_000


def _android_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    root = Path.home() / "Library/Android/sdk/build-tools"
    choices = sorted(root.glob(f"*/{name}"), key=lambda p: tuple(int(x) for x in re.findall(r"\d+", p.parent.name)))
    if not choices:
        raise RuntimeError(f"{name} is required to verify the release APK")
    return str(choices[-1])


def inspect_apk(apk: Path) -> dict:
    if not apk.is_file() or not 1_000_000 <= apk.stat().st_size <= MAX_APK_BYTES:
        raise ValueError("APK is missing or outside release size limits")
    badge = subprocess.run([_android_tool("aapt2"), "dump", "badging", str(apk)],
                           check=True, text=True, capture_output=True).stdout
    match = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badge)
    if not match:
        raise ValueError("APK package/version could not be verified")
    package, code, version = match.groups()
    signing = subprocess.run([_android_tool("apksigner"), "verify", "--print-certs", str(apk)],
                             check=True, text=True, capture_output=True).stdout
    cert = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})", signing)
    if package != "io.estimoto.plus" or cert is None or cert.group(1) != CERTIFICATE_SHA256:
        raise ValueError("Wrong app identity or release signing certificate")
    with apk.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    manifest = {
        "package": package, "version_name": version, "version_code": int(code),
        "sha256": digest, "byte_size": apk.stat().st_size,
        "certificate_sha256": cert.group(1),
        "asset_url": (
            "https://github.com/JamesMcDaniel04/Estimoto-/releases/download/"
            f"v{version}-beta.{code}/estimoto-plus-{version}-{code}.apk"
        ),
    }
    return validate_manifest(manifest)


def verify_remote_apk(client: httpx.Client, manifest: dict) -> None:
    digest = hashlib.sha256()
    size = 0
    with client.stream("GET", manifest["asset_url"], follow_redirects=True) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_APK_BYTES:
                raise ValueError("Public APK exceeds release size limit")
            digest.update(chunk)
    if size != manifest["byte_size"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("Public GitHub APK differs from the signed local APK")


def publish_pointer(client: httpx.Client, supabase_url: str, key: str, manifest: dict) -> str:
    validate_manifest(manifest)
    url = public_object_url(supabase_url, "current.json")
    response = client.get(url, params={"cacheNonce": uuid4().hex}, headers={"Cache-Control": "no-cache"})
    if response.status_code == 200:
        old = validate_manifest(response.json())
        if old == manifest:
            return "already-current"
        if manifest["version_code"] <= old["version_code"]:
            raise ValueError("Release versionCode must increase")
    elif response.status_code != 404 and not (
        response.status_code == 400 and response.json().get("code") == "NoSuchKey"
    ):
        raise RuntimeError(f"Current pointer read failed ({response.status_code})")

    upload_url = f"{supabase_url.rstrip('/')}/storage/v1/object/{BUCKET}/current.json"
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    response = client.post(upload_url, content=body, headers={
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json", "cache-control": "0", "x-upsert": "true",
    })
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Current pointer write failed ({response.status_code})")
    for _ in range(13):
        response = client.get(url, params={"cacheNonce": uuid4().hex}, headers={"Cache-Control": "no-cache"})
        if response.status_code == 200 and validate_manifest(response.json()) == manifest:
            return "published"
        time.sleep(5)
    raise RuntimeError("Current pointer write was not visible after verification window")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".config/estimoto-plus/service-env.json")
    parser.add_argument("--keys-file", type=Path, default=Path.home() / ".config/estimoto-plus/supabase-keys.json")
    args = parser.parse_args()
    manifest = inspect_apk(args.apk)
    environment = json.loads(args.env_file.read_text())
    supabase_url = environment["SUPABASE_URL"].rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", supabase_url):
        raise ValueError("SUPABASE_URL must be the fixed Plus project origin")
    keys = json.loads(args.keys_file.read_text())
    key = next(item["api_key"] for item in keys if item.get("type") == "legacy" and item.get("name") == "service_role")
    with httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False) as client:
        bucket = client.get(f"{supabase_url}/storage/v1/bucket/{BUCKET}",
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
        if bucket.status_code != 200 or bucket.json().get("public") is not True:
            raise RuntimeError("Dedicated public Android release pointer bucket is unavailable")
        verify_remote_apk(client, manifest)
        result = publish_pointer(client, supabase_url, key, manifest)
    print(json.dumps({"status": result, "version_code": manifest["version_code"],
                      "sha256": manifest["sha256"], "asset_url": manifest["asset_url"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
