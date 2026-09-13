"""Private garage photos and bounded, representative CarsXE stock imagery.

The provider receives only year/make/model. Its returned URLs never reach the
client and are fetched with public DNS addresses pinned to the TLS connection.
Durable leases and quotas reserve provider calls before network I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
import hashlib
import http.client
from io import BytesIO
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import time
from urllib.parse import unquote, urlencode, urljoin, urlsplit
from uuid import UUID
import warnings

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .auth import current_customer, db_session
from .customer_routes import consume_rate, owned
from .models import Customer, Vehicle, VehicleImageCache, VehicleImageProviderState, now, uid

router = APIRouter(prefix="/v1/vehicles")
log = logging.getLogger(__name__)
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_CUSTOMER_BYTES = 20 * 1024 * 1024
MAX_UPLOADS_PER_HOUR = 20
MAX_UPLOAD_ATTEMPTS_PER_HOUR = 40
MAX_LOOKUPS_PER_HOUR = 10
MAX_LOOKUPS_PER_DAY = 200
MAX_CACHE_ENTRIES = 2000
MAX_CACHE_BYTES = 100 * 1024 * 1024
POSITIVE_TTL = timedelta(days=365)
NEGATIVE_TTL = timedelta(days=1)
LEASE_TTL = timedelta(seconds=120)
_decode_slots = threading.BoundedSemaphore(2)


class ImageBusy(Exception):
    pass


def canonical_image(data: bytes) -> bytes:
    """Decode the first static raster, apply orientation, discard all metadata."""
    if not _decode_slots.acquire(blocking=False):
        raise ImageBusy()
    try:
        return _canonical_image(data)
    finally:
        _decode_slots.release()


def _canonical_image(data: bytes) -> bytes:
    if not data or len(data) > MAX_INPUT_BYTES:
        raise ValueError("Image size")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(BytesIO(data)) as original:
                if (original.format not in {"JPEG", "PNG", "WEBP"} or
                        original.width * original.height > MAX_PIXELS or
                        max(original.size) > 16384 or getattr(original, "n_frames", 1) != 1):
                    raise ValueError("Image format or dimensions")
                original.load()
                oriented = ImageOps.exif_transpose(original)
                oriented.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
                # A fresh image explicitly excludes EXIF, XMP, ICC and PNG text.
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"
                pixels = oriented.convert(mode)
                clean = Image.new(mode, pixels.size)
                clean.paste(pixels)
                output = BytesIO()
                clean.save(output, format="WEBP", quality=85, method=4)
                result = output.getvalue()
                if len(result) > MAX_OUTPUT_BYTES:
                    raise ValueError("Image output size")
                return result
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise ValueError("Invalid image") from exc


def cache_key(make, model, year):
    identity = ["carsxe-representative-v2", " ".join(make.split()).casefold(),
                " ".join(model.split()).casefold(), int(year)]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global:
        return False
    if address.version == 6:
        # Reject alternate IPv4 routing forms, including NAT64 to metadata IPs.
        return not (address.ipv4_mapped or address.sixtofour or address.teredo or
                    address in ipaddress.ip_network("64:ff9b::/96") or
                    address in ipaddress.ip_network("64:ff9b:1::/48"))
    return True


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # DNS is resolved and validated exactly once. TLS still verifies the
        # original hostname; the socket cannot re-resolve it to a private IP.
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _fetch_https(url: str, *, max_bytes: int, deadline: float, redirects: int = 0):
    if len(url) > 4096 or any(ord(ch) < 33 for ch in url):
        raise ValueError("Invalid provider URL")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password or
            parts.port not in {None, 443} or parts.fragment):
        raise ValueError("Unsafe provider URL")
    host = parts.hostname.encode("idna").decode("ascii")
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise ValueError("Unsafe provider address")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Image lookup deadline")
    connection = _PinnedHTTPSConnection(host, addresses[0], min(8.0, remaining))
    try:
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        connection.request("GET", path, headers={"User-Agent": "EstimotoPlus/1.0", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            if redirects <= 0:
                raise ValueError("Provider redirect refused")
            location = response.getheader("Location")
            if not location:
                raise ValueError("Missing redirect location")
            target = urljoin(url, location)
            connection.close()
            return _fetch_https(target, max_bytes=max_bytes, deadline=deadline, redirects=redirects - 1)
        if response.status != 200:
            return response.status, b""
        length = response.getheader("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError("Provider response too large")
        content = bytearray()
        while len(content) <= max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Image lookup deadline")
            if connection.sock:
                connection.sock.settimeout(min(8.0, remaining))
            chunk = response.read1(min(65536, max_bytes + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > max_bytes:
            raise ValueError("Provider response too large")
        return response.status, bytes(content)
    finally:
        connection.close()


@dataclass
class StockResult:
    data: bytes | None = None
    backoff: timedelta | None = None


def _source_matches(url, make, model, year):
    """Require model/year evidence in the image source, not a comparison page.

    CarsXE's validate=true can still return another make from a comparison
    article or a newer generation. Fail closed for opaque URLs and unrelated
    years. This is a conservative relevance gate, not exact-car verification.
    """
    if not isinstance(url, str):
        return False
    try:
        source = unquote(urlsplit(url).path).casefold()
    except ValueError:
        return False
    normalized = re.sub(r"[^a-z0-9]", "", source)
    names = [re.sub(r"[^a-z0-9]", "", name.casefold()) for name in (make, model)]
    return (all(name and name in normalized for name in names) and
            re.search(r"(?<![0-9])" + str(year) + r"(?![0-9])", source) is not None)


def fetch_carsxe(settings, make, model, year):
    # stdlib HTTPS deliberately avoids httpx's URL-bearing INFO logs. Never
    # log exceptions or provider bodies: CarsXE requires a query credential.
    deadline = time.monotonic() + 25
    params = {"key": settings.carsxe_api_key, "make": make.strip(), "model": model.strip(),
              "year": str(year), "size": "Medium", "format": "json", "validate": "true",
              "license": "ModifyCommercially"}
    try:
        status, raw = _fetch_https("https://api.carsxe.com/images?" + urlencode(params),
                                  max_bytes=1024 * 1024, deadline=deadline)
        if status in {401, 402, 403, 429}:
            return StockResult(backoff=timedelta(hours=1))
        if status >= 500:
            return StockResult(backoff=timedelta(minutes=5))
        if status != 200:
            return StockResult()
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("success") is False:
            return StockResult()
        images = payload.get("images")
        if not isinstance(images, list) and isinstance(payload.get("data"), dict):
            images = payload["data"].get("images")
        if not isinstance(images, list):
            return StockResult()
        attempted = 0
        for item in images[:10]:
            if not isinstance(item, dict):
                continue
            url = item.get("link") or item.get("url") or item.get("image")
            if not _source_matches(url, make, model, year):
                continue
            attempted += 1
            try:
                status, image = _fetch_https(url, max_bytes=MAX_INPUT_BYTES, deadline=deadline, redirects=3)
                if status == 200:
                    return StockResult(canonical_image(image))
            except ImageBusy:
                return StockResult(backoff=timedelta(minutes=1))
            except (OSError, ValueError, TimeoutError, http.client.HTTPException):
                pass
            if attempted >= 3:
                break
        return StockResult()
    except (OSError, ValueError, TimeoutError, http.client.HTTPException):
        return StockResult(backoff=timedelta(minutes=5))


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _retry(value):
    return max(1, int((_aware(value) - now()).total_seconds()))


def _image_response(data, source):
    return Response(data, media_type="image/webp", headers={
        "X-Vehicle-Image-Source": source,
        "ETag": '"' + hashlib.sha256(data).hexdigest() + '"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def _empty(retry=86400):
    return Response(status_code=204, headers={"Retry-After": str(retry)})


def _upload_path(settings, name):
    if str(UUID(name)) != name:
        raise ValueError("Invalid stored image identifier")
    return Path(settings.photo_dir) / "vehicle-images" / name


def remove_upload_file(settings, name):
    try:
        _upload_path(settings, name).unlink(missing_ok=True)
    except OSError:
        # A deletion remains successful if the volume is temporarily unwritable.
        # The old opaque object has no route once its database reference is gone.
        log.warning("Private vehicle image cleanup failed")


def _valid_upload_data(settings, v):
    try:
        with _upload_path(settings, v.image_storage_name).open("rb") as stream:
            data = stream.read(MAX_OUTPUT_BYTES + 1)
    except (OSError, ValueError):
        return None
    if len(data) != v.image_byte_size or hashlib.sha256(data).hexdigest() != v.image_version:
        return None
    return data


def _uploaded_response(settings, v):
    if not v.image_storage_name:
        return None
    data = _valid_upload_data(settings, v)
    if data is None:
        raise HTTPException(503, "Your vehicle photo is temporarily unavailable.")
    return _image_response(data, "upload")


def _insert(db, model):
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(model)


def _trim_cache(db, keep_key, *, inserting=False):
    """Called under the global provider lock; active reservations are preserved."""
    count, size = db.execute(select(func.count(), func.coalesce(func.sum(func.length(VehicleImageCache.image_data)), 0))
                             .select_from(VehicleImageCache)).one()
    if count + int(inserting) <= MAX_CACHE_ENTRIES and size <= MAX_CACHE_BYTES:
        return
    rows = db.scalars(select(VehicleImageCache).where(VehicleImageCache.cache_key != keep_key,
                        or_(VehicleImageCache.lease_token.is_(None), VehicleImageCache.lease_until < now()))
                      .order_by(VehicleImageCache.retry_at)).all()
    for row in rows:
        if count + int(inserting) <= MAX_CACHE_ENTRIES and size <= MAX_CACHE_BYTES:
            break
        size -= len(row.image_data or b"")
        count -= 1
        db.delete(row)


@router.get("/{vehicle_id}/image")
def get_vehicle_image(vehicle_id: str, request: Request,
                      c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    settings = request.app.state.settings
    v = owned(db, Vehicle, vehicle_id, c)
    uploaded = _uploaded_response(settings, v)
    if uploaded is not None:
        return uploaded
    key = cache_key(v.make, v.model, v.year)
    cached = db.get(VehicleImageCache, key)
    if cached and _aware(cached.retry_at) > now():
        return _image_response(cached.image_data, "carsxe") if cached.image_data else _empty(_retry(cached.retry_at))
    if not settings.carsxe_api_key or c.demo or not v.make.strip() or not v.model.strip():
        return _empty()

    # All miss reservations use customer -> provider state lock order. No locks
    # are held during HTTPS. An interrupted process leaves a bounded lease.
    db.execute(update(Customer).where(Customer.id == c.id).values(id=Customer.id))
    db.execute(_insert(db, VehicleImageProviderState).values(id=1, day_bucket=0, count=0)
               .on_conflict_do_nothing(index_elements=[VehicleImageProviderState.id]))
    db.execute(update(VehicleImageProviderState).where(VehicleImageProviderState.id == 1)
               .values(id=VehicleImageProviderState.id))
    db.expire_all()
    v = owned(db, Vehicle, vehicle_id, c)
    uploaded = _uploaded_response(settings, v)
    if uploaded is not None:
        return uploaded
    key = cache_key(v.make, v.model, v.year)
    cached = db.get(VehicleImageCache, key)
    timestamp = now()
    if cached and _aware(cached.retry_at) > timestamp:
        return _image_response(cached.image_data, "carsxe") if cached.image_data else _empty(_retry(cached.retry_at))
    if cached and cached.lease_until and _aware(cached.lease_until) > timestamp:
        return _empty(_retry(cached.lease_until))
    state = db.get(VehicleImageProviderState, 1)
    if state.blocked_until and _aware(state.blocked_until) > timestamp:
        return _empty(_retry(state.blocked_until))
    day = int(timestamp.timestamp() // 86400)
    if state.day_bucket != day:
        state.day_bucket, state.count = day, 0
    if state.count >= MAX_LOOKUPS_PER_DAY:
        return _empty(86400 - int(timestamp.timestamp() % 86400))
    consume_rate(db, c.id, "vehicle_stock_image", MAX_LOOKUPS_PER_HOUR)
    state.count += 1
    lease = uid()
    if cached is None:
        _trim_cache(db, key, inserting=True)
        cached = VehicleImageCache(cache_key=key, retry_at=timestamp)
        db.add(cached)
    cached.lease_token, cached.lease_until = lease, timestamp + LEASE_TTL
    identity = (v.make, v.model, v.year)
    db.commit()

    result = fetch_carsxe(settings, *identity)
    db.execute(update(VehicleImageProviderState).where(VehicleImageProviderState.id == 1)
               .values(id=VehicleImageProviderState.id))
    db.expire_all()
    state = db.get(VehicleImageProviderState, 1)
    cached = db.get(VehicleImageCache, key)
    if cached and cached.lease_token == lease:
        cached.image_data = result.data
        cached.retry_at = now() + (POSITIVE_TTL if result.data else NEGATIVE_TTL)
        cached.lease_token = cached.lease_until = None
        if result.backoff:
            until = now() + result.backoff
            if not state.blocked_until or _aware(state.blocked_until) < until:
                state.blocked_until = until
        db.flush()
        _trim_cache(db, key)
    db.commit()
    db.expire_all()
    v = owned(db, Vehicle, vehicle_id, c)
    uploaded = _uploaded_response(settings, v)
    if uploaded is not None:
        return uploaded
    if cache_key(v.make, v.model, v.year) != key:
        return _empty(1)
    cached = db.get(VehicleImageCache, key)
    return _image_response(cached.image_data, "carsxe") if cached and cached.image_data else _empty()


def _save_upload(vehicle_id, data, settings, customer_id, session_factory):
    # Bound malformed-image decode attempts as well as durable uploads. A short
    # committed reservation precedes CPU work; ownership is checked again after.
    with session_factory() as db:
        db.execute(update(Customer).where(Customer.id == customer_id).values(id=Customer.id))
        customer = db.get(Customer, customer_id)
        if customer is None:
            raise HTTPException(404, "Not found.")
        owned(db, Vehicle, vehicle_id, customer)
        consume_rate(db, customer_id, "vehicle_image_attempt", MAX_UPLOAD_ATTEMPTS_PER_HOUR)
        db.commit()
    cleaned = canonical_image(data)
    digest = hashlib.sha256(cleaned).hexdigest()
    with session_factory() as db:
        db.execute(update(Customer).where(Customer.id == customer_id).values(id=Customer.id))
        customer = db.get(Customer, customer_id)
        if customer is None:
            raise HTTPException(404, "Not found.")
        v = owned(db, Vehicle, vehicle_id, customer)
        # Exact retries do not consume quota or create orphan objects.
        if v.image_version == digest and v.image_storage_name:
            if _valid_upload_data(settings, v) is not None:
                return {"source": "upload", "image_version": digest}
        total = sum(
            size or 0 for size in db.scalars(select(Vehicle.image_byte_size).where(Vehicle.customer_id == customer_id)).all())
        if total - (v.image_byte_size or 0) + len(cleaned) > MAX_CUSTOMER_BYTES:
            raise HTTPException(413, "Vehicle photo storage limit reached.")
        consume_rate(db, customer_id, "vehicle_photo_upload", MAX_UPLOADS_PER_HOUR)
        old_name = v.image_storage_name
        storage_name = uid()
        target = _upload_path(settings, storage_name)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(cleaned)
                stream.flush()
                os.fsync(stream.fileno())
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            v.image_storage_name, v.image_version, v.image_byte_size = storage_name, digest, len(cleaned)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        # A failed commit acknowledgement can be ambiguous. Keep the opaque
        # file in that case so a successful database commit never points at a
        # deleted upload. An identical retry converges on the stored digest.
        db.commit()
        if old_name:
            remove_upload_file(settings, old_name)
        return {"source": "upload", "image_version": digest}


@router.post("/{vehicle_id}/image")
async def upload_vehicle_image(vehicle_id: str, request: Request,
                               c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    owned(db, Vehicle, vehicle_id, c)
    async with request.form(max_files=1, max_fields=0, max_part_size=1024) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile) or len(form.multi_items()) != 1:
            raise HTTPException(422, "A vehicle photo is required.")
        data = await file.read(MAX_INPUT_BYTES + 1)
    customer_id = c.id
    db.rollback()  # release the read transaction before the thread's write lock
    try:
        return await run_in_threadpool(_save_upload, vehicle_id, data, request.app.state.settings,
                                      customer_id, request.app.state.session_factory)
    except ValueError:
        raise HTTPException(422, "Upload a valid static JPEG, PNG, or WebP under 10 MB and 40 megapixels.")
    except ImageBusy:
        raise HTTPException(503, "Photo processing is busy. Please try again shortly.", headers={"Retry-After": "5"})


@router.delete("/{vehicle_id}/image", status_code=204)
def delete_vehicle_image(vehicle_id: str, request: Request,
                         c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    db.execute(update(Customer).where(Customer.id == c.id).values(id=Customer.id))
    db.expire_all()
    v = owned(db, Vehicle, vehicle_id, c)
    old_name = v.image_storage_name
    v.image_storage_name = v.image_version = v.image_byte_size = None
    db.commit()
    if old_name:
        remove_upload_file(request.app.state.settings, old_name)
