"""Private image ownership, paid-provider boundaries and durable concurrency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.models import RateBucket, Vehicle, VehicleImageCache, VehicleImageProviderState, now
from estimoto_plus import vehicle_images as vi


def raster(color="red", fmt="JPEG", *, metadata=False):
    image = Image.new("RGB", (80, 40), color)
    output = BytesIO()
    kwargs = {}
    if metadata and fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010E] = "PRIVATE LOCATION AND CUSTOMER NAME"
        exif[0x0112] = 6
        kwargs["exif"] = exif
    if metadata and fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("secret", "PRIVATE LOCATION AND CUSTOMER NAME")
        kwargs["pnginfo"] = info
    image.save(output, format=fmt, **kwargs)
    return output.getvalue()


def h(who="alice"):
    return {"Authorization": f"Bearer {who}"}


def make_vehicle(client, who="alice", model="Tacoma"):
    result = client.post("/v1/vehicles", headers=h(who), json={"year": 2021, "make": "Toyota", "model": model})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def upload(client, vehicle_id, data=None, who="alice"):
    return client.post(f"/v1/vehicles/{vehicle_id}/image", headers=h(who),
                       files={"file": ("untrusted-name.svg", data or raster(), "application/octet-stream")})


@pytest.fixture(params=["sqlite", "postgresql"])
def garage(request, tmp_path, monkeypatch):
    admin = schema = None
    if request.param == "postgresql":
        supplied = os.getenv("PLUS_TEST_POSTGRES_URL")
        if not supplied:
            pytest.skip("PLUS_TEST_POSTGRES_URL required for real concurrency proof")
        url = make_url(supplied)
        if url.host not in {None, "localhost", "127.0.0.1"} or "test" not in (url.database or ""):
            pytest.fail("Use a local disposable test database")
        admin = create_engine(url)
        schema = "plus_images_test_" + uuid4().hex
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        database_url = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    else:
        database_url = f"sqlite:///{tmp_path / 'images.db'}"
    settings = Settings(database_url=database_url, environment="test", worker_enabled=False,
                        carsxe_api_key="FAKE-NEVER-LIVE", photo_dir=str(tmp_path / "photos"))
    calls = []
    def stock(_settings, make, model, year):
        calls.append((make, model, year))
        return vi.StockResult(vi.canonical_image(raster("blue")))
    monkeypatch.setattr(vi, "fetch_carsxe", stock)
    app = create_app(settings, auth_verifier=lambda token: {
        "id": token, "email": token + "@example.test", "email_confirmed_at": "ok"} if token in {"alice", "bob"} else None)
    try:
        with TestClient(app) as client:
            yield client, calls
    finally:
        app.state.engine.dispose()
        if admin:
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_ownership_no_url_input_and_upload_metadata(garage):
    client, calls = garage
    vid = make_vehicle(client)
    path = f"/v1/vehicles/{vid}/image"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=h("bob")).status_code == 404
    assert upload(client, vid, who="bob").status_code == 404
    assert client.delete(path, headers=h("bob")).status_code == 404
    assert client.post(path, headers=h(), json={"url": "http://169.254.169.254"}).status_code == 422
    assert calls == []
    result = upload(client, vid, raster(metadata=True))
    assert result.status_code == 200, result.text
    assert result.json()["source"] == "upload"
    fetched = client.get(path, headers=h())
    assert fetched.status_code == 200 and fetched.headers["x-vehicle-image-source"] == "upload"
    assert fetched.headers["cache-control"] == "private, no-store"
    assert fetched.headers["content-type"] == "image/webp"
    assert result.json()["image_version"] == hashlib.sha256(fetched.content).hexdigest()
    with Image.open(BytesIO(fetched.content)) as image:
        assert image.size == (40, 80)  # camera orientation is applied before EXIF removal
        assert not image.getexif() and "exif" not in image.info and "xmp" not in image.info
    assert b"PRIVATE LOCATION" not in fetched.content
    v = client.get("/v1/bootstrap", headers=h()).json()["vehicles"][0]
    assert v["image_version"] == result.json()["image_version"]
    assert "image_storage_name" not in v and calls == []


def test_private_replay_replacement_delete_and_vehicle_cleanup(garage):
    client, calls = garage
    vid = make_vehicle(client)
    path = f"/v1/vehicles/{vid}/image"
    first = upload(client, vid, raster("red")).json()
    assert upload(client, vid, raster("red")).json() == first
    files = list((Path(client.app.state.settings.photo_dir) / "vehicle-images").iterdir())
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.sum(RateBucket.count)).where(RateBucket.action == "vehicle_photo_upload")) == 1
    assert upload(client, vid, raster("green")).json() != first
    assert not files[0].exists()
    assert client.delete(path, headers=h()).status_code == 204
    assert client.delete(path, headers=h()).status_code == 204
    assert list(files[0].parent.iterdir()) == []
    fallback = client.get(path, headers=h())
    assert fallback.status_code == 200 and fallback.headers["x-vehicle-image-source"] == "carsxe"
    assert len(calls) == 1
    upload(client, vid)
    assert client.delete(f"/v1/vehicles/{vid}", headers=h()).status_code == 204
    assert list(files[0].parent.iterdir()) == []
    assert client.get(path, headers=h()).status_code == 404


def test_positive_negative_and_failed_provider_cache(garage, monkeypatch):
    client, calls = garage
    alice, bob = make_vehicle(client), make_vehicle(client, "bob")
    for vid, who in ((alice, "alice"), (bob, "bob"), (alice, "alice")):
        assert client.get(f"/v1/vehicles/{vid}/image", headers=h(who)).status_code == 200
    assert calls == [("Toyota", "Tacoma", 2021)]  # global stock cache, never upload data
    monkeypatch.setattr(vi, "fetch_carsxe", lambda *args: (calls.append(args[1:]) or vi.StockResult(backoff=timedelta(minutes=5))))
    missing = make_vehicle(client, model="Unavailable")
    for _ in range(3):
        result = client.get(f"/v1/vehicles/{missing}/image", headers=h())
        assert result.status_code == 204 and int(result.headers["retry-after"]) > 0
    other = make_vehicle(client, model="Other")
    assert client.get(f"/v1/vehicles/{other}/image", headers=h()).status_code == 204
    assert len(calls) == 2  # upstream backoff covers distinct identities as well


def test_concurrent_miss_one_paid_call_and_upload_wins(garage, monkeypatch):
    client, _ = garage
    alice, bob = make_vehicle(client), make_vehicle(client, "bob")
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(*args):
        calls.append(args[1:])
        entered.set()
        assert release.wait(10)
        return vi.StockResult(vi.canonical_image(raster("blue")))
    monkeypatch.setattr(vi, "fetch_carsxe", slow)
    with ThreadPoolExecutor(max_workers=5) as pool:
        first = pool.submit(client.get, f"/v1/vehicles/{alice}/image", headers=h())
        assert entered.wait(5)
        try:
            pending = list(pool.map(lambda _: client.get(f"/v1/vehicles/{bob}/image", headers=h("bob")), range(3)))
            assert all(r.status_code == 204 for r in pending)
            result = upload(client, alice, raster("red"))
            assert result.status_code == 200, result.text
        finally:
            release.set()
        final = first.result(timeout=5)
    assert len(calls) == 1
    assert final.status_code == 200 and final.headers["x-vehicle-image-source"] == "upload"


def test_vehicle_identity_changes_during_fetch_never_return_old_stock(garage, monkeypatch):
    client, _ = garage
    vid = make_vehicle(client)
    def stock(*_):
        assert client.put(f"/v1/vehicles/{vid}", headers=h(), json={"model": "Corolla"}).status_code == 200
        return vi.StockResult(vi.canonical_image(raster()))
    monkeypatch.setattr(vi, "fetch_carsxe", stock)
    assert client.get(f"/v1/vehicles/{vid}/image", headers=h()).status_code == 204


def test_upload_byte_pixel_animation_and_format_limits(garage, monkeypatch):
    client, _ = garage
    vid = make_vehicle(client)
    for data in (b"<svg></svg>", b"\xff\xd8\xffinvalid"):
        assert upload(client, vid, data).status_code == 422
    assert client.post(f"/v1/vehicles/{vid}/image", headers={**h(), "Content-Length": str(12 * 1024 * 1024)}, content=b"x").status_code == 413
    monkeypatch.setattr(vi, "MAX_PIXELS", 10)
    assert upload(client, vid).status_code == 422
    monkeypatch.setattr(vi, "MAX_PIXELS", 40_000_000)
    output = BytesIO()
    Image.new("RGB", (10, 10), "red").save(output, format="WEBP", save_all=True,
                                          append_images=[Image.new("RGB", (10, 10), "blue")], duration=50, loop=0)
    assert upload(client, vid, output.getvalue()).status_code == 422
    assert upload(client, vid, raster(fmt="PNG", metadata=True)).status_code == 200


def test_durable_customer_global_and_storage_quotas(garage, monkeypatch):
    client, calls = garage
    monkeypatch.setattr(vi, "MAX_LOOKUPS_PER_HOUR", 1)
    one, two = make_vehicle(client), make_vehicle(client, model="Corolla")
    assert client.get(f"/v1/vehicles/{one}/image", headers=h()).status_code == 200
    assert client.get(f"/v1/vehicles/{two}/image", headers=h()).status_code == 429
    assert client.get(f"/v1/vehicles/{one}/image", headers=h()).status_code == 200
    monkeypatch.setattr(vi, "MAX_LOOKUPS_PER_DAY", 1)
    bob = make_vehicle(client, "bob", model="Supra")
    assert client.get(f"/v1/vehicles/{bob}/image", headers=h("bob")).status_code == 204
    assert len(calls) == 1
    monkeypatch.setattr(vi, "MAX_UPLOADS_PER_HOUR", 1)
    assert upload(client, one).status_code == 200
    assert upload(client, one).status_code == 200  # replay exempt
    assert upload(client, two).status_code == 429
    monkeypatch.setattr(vi, "MAX_CUSTOMER_BYTES", 1)
    assert upload(client, bob, who="bob").status_code == 413


def test_expired_lease_recovers_and_cache_is_bounded(garage, monkeypatch):
    client, calls = garage
    vid = make_vehicle(client)
    with client.app.state.session_factory() as db:
        db.add(VehicleImageCache(cache_key=vi.cache_key("Toyota", "Tacoma", 2021), retry_at=now()-timedelta(days=1),
                                lease_token="interrupted", lease_until=now()-timedelta(seconds=1)))
        db.commit()
    assert client.get(f"/v1/vehicles/{vid}/image", headers=h()).status_code == 200
    assert len(calls) == 1
    monkeypatch.setattr(vi, "MAX_CACHE_ENTRIES", 1)
    second = make_vehicle(client, model="Corolla")
    assert client.get(f"/v1/vehicles/{second}/image", headers=h()).status_code == 200
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(VehicleImageCache)) == 1


def test_parallel_identical_uploads_converge_and_missing_file_fails_closed(garage):
    client, calls = garage
    vid = make_vehicle(client)
    payload = raster()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: upload(client, vid, payload), range(2)))
    assert all(result.status_code == 200 for result in results)
    assert results[0].json() == results[1].json()
    files = list((Path(client.app.state.settings.photo_dir) / "vehicle-images").iterdir())
    assert len(files) == 1
    files[0].unlink()
    assert client.get(f"/v1/vehicles/{vid}/image", headers=h()).status_code == 503
    assert calls == []
    assert upload(client, vid, payload).status_code == 200  # repair missing object on exact retry
    assert client.get(f"/v1/vehicles/{vid}/image", headers=h()).headers["x-vehicle-image-source"] == "upload"
    current_file = next(files[0].parent.iterdir())
    current_file.write_bytes(b"corrupt")
    assert client.get(f"/v1/vehicles/{vid}/image", headers=h()).status_code == 503
    assert upload(client, vid, payload).status_code == 200
    assert not current_file.exists()
    assert client.get(f"/v1/vehicles/{vid}/image", headers=h()).status_code == 200


def test_chunked_vehicle_upload_is_bounded_before_spooling(garage):
    client, _ = garage
    vid = make_vehicle(client)
    def chunks():
        yield b'--vehicle-boundary\r\nContent-Disposition: form-data; name="file"; filename="car.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        for _ in range(12):
            yield b"x" * (1024 * 1024)
        yield b"\r\n--vehicle-boundary--\r\n"
    response = client.post(f"/v1/vehicles/{vid}/image", headers={**h(), "Content-Type": "multipart/form-data; boundary=vehicle-boundary"}, content=chunks())
    assert response.status_code == 413


def test_invalid_decode_attempts_have_durable_quota(garage, monkeypatch):
    client, _ = garage
    vid = make_vehicle(client)
    monkeypatch.setattr(vi, "MAX_UPLOAD_ATTEMPTS_PER_HOUR", 2)
    assert upload(client, vid, b"not an image").status_code == 422
    assert upload(client, vid, b"not an image").status_code == 422
    assert upload(client, vid, b"not an image").status_code == 429


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe"])
def test_provider_urls_cannot_reach_private_or_rebinding_targets(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    monkeypatch.setattr(vi, "_PinnedHTTPSConnection", lambda *_: pytest.fail("Private address reached socket"))
    with pytest.raises(ValueError):
        vi._fetch_https("https://untrusted.example/car.jpg", max_bytes=100, deadline=time.monotonic()+5)


def test_redirect_revalidates_and_tls_connects_to_pinned_address(monkeypatch):
    resolved, connections = [], []
    def dns(host, *_a, **_k):
        resolved.append(host)
        address = "8.8.8.8" if host == "public.example" else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    class Redirect:
        status = 302
        def getheader(self, name):
            return "https://private.example/metadata"
    class Connection:
        def __init__(self, host, address, timeout):
            connections.append((host, address))
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Redirect()
        def close(self): pass
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(vi, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(ValueError):
        vi._fetch_https("https://public.example/car.jpg", max_bytes=100, deadline=time.monotonic()+5, redirects=3)
    assert resolved == ["public.example", "private.example"]
    assert connections == [("public.example", "8.8.8.8")]


def test_tls_verifies_hostname_without_second_dns_resolution(monkeypatch):
    seen = []
    class Socket:
        def close(self): pass
    class Context:
        def wrap_socket(self, sock, server_hostname):
            seen.append(("tls", server_hostname))
            return sock
    def connect(address, timeout):
        seen.append(("tcp", address))
        return Socket()
    monkeypatch.setattr(socket, "create_connection", connect)
    connection = vi._PinnedHTTPSConnection("public.example", "8.8.8.8", 5)
    connection._context = Context()
    connection.connect()
    assert seen == [("tcp", ("8.8.8.8", 443)), ("tls", "public.example")]


def test_provider_key_never_logged_or_returned_and_params_match_saved_vehicle(monkeypatch, caplog):
    calls = []
    def https(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return 200, json.dumps({"images": [{"link": "https://public.example/2021-Toyota-Tacoma.png"}]}).encode()
        return 200, raster(fmt="PNG")
    monkeypatch.setattr(vi, "_fetch_https", https)
    secret = "super-secret-CarsXE-key"
    result = vi.fetch_carsxe(Settings(carsxe_api_key=secret), "Toyota", "Tacoma", 2021)
    assert result.data and calls[1] == "https://public.example/2021-Toyota-Tacoma.png"
    assert "make=Toyota" in calls[0] and "model=Tacoma" in calls[0] and "year=2021" in calls[0]
    assert "license=ModifyCommercially" in calls[0]
    assert secret not in repr(result) and secret not in repr(Settings(carsxe_api_key=secret))
    def fail(url, **kwargs):
        raise OSError("URL contains " + secret)
    monkeypatch.setattr(vi, "_fetch_https", fail)
    assert vi.fetch_carsxe(Settings(carsxe_api_key=secret), "Toyota", "Tacoma", 2021).backoff
    assert secret not in caplog.text


def test_hash_does_not_truncate_or_confuse_component_boundaries():
    assert vi.cache_key("a" * 100, "b" * 99 + "x", 2021) != vi.cache_key("a" * 100, "b" * 99 + "y", 2021)
    assert vi.cache_key("a|b", "c", 2021) != vi.cache_key("a", "b|c", 2021)
    assert vi.cache_key(" Toyota  ", "TACOMA", 2021) == vi.cache_key("toyota", "Tacoma", 2021)


def test_wrong_make_year_and_opaque_comparison_images_are_rejected(monkeypatch):
    images = [
        {"link": "https://dealer.example/bmw-x5.jpg", "contextLink": "https://dealer.example/2022-audi-q5-versus-bmw-x5"},
        {"link": "https://dealer.example/2026-Audi-Q5.png"},
        {"link": "https://audi.example/opaque.png", "contextLink": "https://audi.example/2022-audi-q5"},
        {"link": "https://dealer.example/2022-Audi-Q5-front.png"}]
    calls = []
    def https(url, **kwargs):
        calls.append(url)
        return (200, json.dumps({"images": images}).encode()) if len(calls) == 1 else (200, raster())
    monkeypatch.setattr(vi, "_fetch_https", https)
    assert vi.fetch_carsxe(Settings(carsxe_api_key="fake"), "Audi", "Q5", 2022).data
    assert calls[1:] == ["https://dealer.example/2022-Audi-Q5-front.png"]
    assert not vi._source_matches("https://dealer.example/2021-Toyota-Tacoma.png?year=2022", "Toyota", "Tacoma", 2022)
