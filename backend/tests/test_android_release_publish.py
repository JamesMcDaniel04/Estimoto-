import hashlib
import json
from pathlib import Path

import pytest

from scripts.publish_android_release import (
    asset_names, checksum_text, check_existing_assets, release_lock,
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
