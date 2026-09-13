import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.publish_android_release import (
    asset_names, checksum_text, check_existing_assets, release_lock,
    verify_aab, verify_build_receipt, release_target, check_release_source,
)


def test_release_assets_and_checksums_are_bound_to_apk_version(tmp_path):
    names = asset_names("0.1.0", 6)
    assert names == ("estimoto-plus-0.1.0-6.apk", "estimoto-plus-0.1.0-6.aab", "SHA256SUMS")
    apk, aab = tmp_path / "app.apk", tmp_path / "app.aab"
    apk.write_bytes(b"signed apk")
    aab.write_bytes(b"signed aab")
    sums = checksum_text(apk, aab, names)
    assert sums == (
        f"{hashlib.sha256(b'signed apk').hexdigest()}  {names[0]}\n"
        f"{hashlib.sha256(b'signed aab').hexdigest()}  {names[1]}\n"
    )


def test_existing_asset_mismatch_blocks_upload_instead_of_clobber():
    expected = {"app.apk": (10, "a" * 64), "app.aab": (20, "b" * 64)}
    matching = [{"name": "app.apk", "size": 10, "digest": "sha256:" + "a" * 64}]
    assert check_existing_assets(matching, expected) == ["app.aab"]
    with pytest.raises(ValueError, match="mismatches"):
        check_existing_assets([{"name": "app.apk", "size": 10, "digest": "sha256:" + "c" * 64}], expected)
    with pytest.raises(ValueError, match="mismatches"):
        check_existing_assets([{"name": "app.apk", "size": 11, "digest": "sha256:" + "a" * 64}], expected)


def test_local_publisher_lock_blocks_overlapping_release(tmp_path):
    lock = tmp_path / "release.lock"
    with release_lock(lock):
        with pytest.raises(RuntimeError, match="already running"):
            with release_lock(lock):
                pass
    with release_lock(lock):
        assert lock.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("aab_package,aab_code,aab_version", [
    ("io.estimoto.other", "6", "0.1.0"),
    ("io.estimoto.plus", "5", "0.1.0"),
    ("io.estimoto.plus", "6", "0.0.9"),
])
def test_signed_aab_manifest_must_match_signed_apk_before_release(
    monkeypatch, tmp_path, aab_package, aab_code, aab_version,
):
    import zipfile
    import scripts.publish_android_release as release

    aab = tmp_path / "same-key-but-wrong-version.aab"
    with zipfile.ZipFile(aab, "w") as archive:
        archive.writestr("base/manifest/AndroidManifest.xml", b"x" * 1_000_001)
    values = iter([aab_package, aab_code, aab_version])

    def fake_run(command, **_kwargs):
        if command[0] == "jarsigner":
            return SimpleNamespace(stdout="jar verified")
        if command[0] == "keytool":
            pairs = ":".join(release.CERTIFICATE_SHA256[i:i + 2] for i in range(0, 64, 2))
            return SimpleNamespace(stdout=f"SHA256: {pairs}")
        if command[0] == "java":
            return SimpleNamespace(stdout=next(values))
        raise AssertionError(f"unexpected command: {command[0]}")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    monkeypatch.setattr(release, "bundletool_jar", lambda: tmp_path / "bundletool.jar")
    with pytest.raises(ValueError, match="AAB manifest differs from signed APK"):
        verify_aab(aab, {"package": "io.estimoto.plus", "version_code": 6, "version_name": "0.1.0"})


def test_build_receipt_binds_both_artifact_hashes_and_release_target(tmp_path):
    apk, aab, receipt = (tmp_path / name for name in ("app.apk", "app.aab", "receipt.json"))
    apk.write_bytes(b"new signed apk")
    aab.write_bytes(b"old signed aab")
    source_sha = "a" * 40
    receipt.write_text(json.dumps({
        "schema": 1, "source_sha": source_sha,
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "aab_sha256": hashlib.sha256(b"new signed aab").hexdigest(),
    }))
    with pytest.raises(ValueError, match="AAB hash differs from clean-build receipt"):
        verify_build_receipt(receipt, apk, aab)
    receipt.write_text(json.dumps({
        "schema": 1, "source_sha": source_sha,
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "aab_sha256": hashlib.sha256(aab.read_bytes()).hexdigest(),
    }))
    assert verify_build_receipt(receipt, apk, aab) == source_sha
    assert release_target(source_sha, current_head="b" * 40) == source_sha


def test_existing_release_tag_cannot_represent_different_source():
    with pytest.raises(ValueError, match="different source commit"):
        check_release_source({"target_commitish": "b" * 40}, "a" * 40)
    check_release_source({"target_commitish": "a" * 40}, "a" * 40)


def test_build_receipt_refuses_source_change_before_recording_hashes(monkeypatch, tmp_path):
    from scripts import write_android_build_receipt as writer

    apk, aab = tmp_path / "app.apk", tmp_path / "app.aab"
    apk.write_bytes(b"apk")
    aab.write_bytes(b"aab")
    monkeypatch.setattr(writer.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="b" * 40))
    with pytest.raises(ValueError, match="Source commit changed"):
        writer.make_receipt("a" * 40, apk, aab)
