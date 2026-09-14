from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4

from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from estimoto_plus.graph_models import KnowledgeRecord, KnowledgeReceipt
from test_api import clients, create_vehicle, h
from test_knowledge import add


def image():
    stream = BytesIO()
    Image.new("RGB", (32, 32), "white").save(stream, format="PNG")
    return stream.getvalue()


def pdf(*, script=False):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if script:
        writer.add_js("app.alert('should never execute')")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def upload(client, rid, key=None, who="alice", data=None, mime="image/png", filename="receipt.png"):
    return client.post(f"/v1/knowledge/records/{rid}/receipts",
        headers={**h(who), "Idempotency-Key": key or str(uuid4())},
        files={"file": (filename, image() if data is None else data, mime)})


def test_receipt_roundtrip_private_exact_replay_and_tombstone(clients):
    client, _ = clients
    vehicle = create_vehicle(client)
    rid = add(client, vehicle, service_type="repair", cost_cents=129999).json()["id"]
    key = str(uuid4())
    first = upload(client, rid, key)
    assert first.status_code == 201, first.text
    receipt = first.json()
    assert set(receipt) == {"id", "filename", "content_type", "byte_size", "created_at"}
    assert upload(client, rid, key).json() == receipt
    assert upload(client, rid, key, filename="different.png").status_code == 409
    assert upload(client, rid, who="bob").status_code == 404
    path = f"/v1/knowledge/records/{rid}/receipts/{receipt['id']}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=h("bob")).status_code == 404
    assert client.delete(path, headers=h("bob")).status_code == 404
    response = client.get(path, headers=h("alice"))
    assert response.content == image()
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in response.headers["content-security-policy"]
    record = client.get("/v1/knowledge", headers=h("alice")).json()["records"][0]
    assert record["cost_cents"] == 129999 and record["currency"] == "USD"
    assert record["receipts"] == [receipt]
    assert "receipt.png" not in client.get("/v1/knowledge/graph", headers=h("alice")).text
    assert client.delete(path, headers=h("alice")).status_code == 204
    assert client.get(path, headers=h("alice")).status_code == 404
    assert upload(client, rid, key).status_code == 410
    assert not list((Path(client.app.state.settings.photo_dir)/"receipts").iterdir())


def test_full_record_delete_removes_files_and_derived_links(clients):
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()["id"]
    key = str(uuid4())
    receipt = upload(client, rid, key).json()
    assert client.delete(f"/v1/knowledge/records/{rid}", headers=h("alice")).status_code == 204
    assert client.get(f"/v1/knowledge/records/{rid}/receipts/{receipt['id']}", headers=h("alice")).status_code == 404
    assert upload(client, rid, key).status_code == 404
    assert not list((Path(client.app.state.settings.photo_dir)/"receipts").iterdir())
    with client.app.state.session_factory() as db:
        tombstone = db.get(KnowledgeReceipt, receipt["id"])
        assert tombstone.status == "deleted" and tombstone.record_id is None and tombstone.storage_name is None
        assert tombstone.filename == "" and tombstone.byte_size == 0


def test_receipt_validation_limits_pdf_and_field_contract(clients):
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()["id"]
    assert upload(client, rid, data=pdf(), mime="application/pdf", filename="receipt.pdf").status_code == 201
    assert upload(client, rid, data=pdf(script=True), mime="application/pdf").status_code == 415
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject, NumberObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    action = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert('unsafe')")})
    annotation = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([NumberObject(v) for v in (0, 0, 100, 100)]), NameObject("/A"): action})
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    annotated = BytesIO()
    writer.write(annotated)
    assert upload(client, rid, data=annotated.getvalue(), mime="application/pdf").status_code == 415
    assert upload(client, rid, data=b"%PDF-1.4\ninvalid", mime="application/pdf").status_code == 415
    assert upload(client, rid, data=b"<svg></svg>", mime="image/svg+xml").status_code == 415
    assert upload(client, rid, data=image(), mime="image/jpeg").status_code == 415
    assert upload(client, rid, key="not-uuid").status_code == 422
    assert upload(client, rid, data=b"x"*(10*1024*1024+1)).status_code == 413
    assert upload(client, rid, data=b"x"*(12*1024*1024)).status_code == 413
    for _ in range(9):
        assert upload(client, rid).status_code == 201
    assert upload(client, rid).status_code == 422
    # A completed retry does not consume another attachment slot.
    assert len(client.get("/v1/knowledge", headers=h("alice")).json()["records"][0]["receipts"]) == 10


def test_concurrent_same_operation_writes_one_attachment(clients):
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()["id"]
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: upload(client, rid, key), range(4)))
    assert all(r.status_code in (201, 503) for r in responses), [r.text for r in responses]
    # Decode capacity is deliberately bounded. Retry the same immutable key
    # after an explicit busy response; this must still return the one receipt.
    responses = [upload(client, rid, key) if r.status_code == 503 else r for r in responses]
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(list((Path(client.app.state.settings.photo_dir)/"receipts").iterdir())) == 1


def test_lost_commit_ack_preserves_private_bytes_for_exact_retry(clients, monkeypatch):
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()["id"]
    original = Session.commit
    did_fail = False

    def uncertain_commit(db):
        nonlocal did_fail
        trigger = not did_fail and any(isinstance(row, KnowledgeReceipt) and row.status == "saved" for row in db.dirty)
        original(db)
        if trigger:
            did_fail = True
            raise OSError("simulated successful commit with lost acknowledgement")

    monkeypatch.setattr(Session, "commit", uncertain_commit)
    key = str(uuid4())
    import pytest
    with pytest.raises(OSError):
        upload(client, rid, key)
    assert did_fail
    retried = upload(client, rid, key)
    assert retried.status_code == 201, retried.text
    assert client.get(f"/v1/knowledge/records/{rid}/receipts/{retried.json()['id']}", headers=h("alice")).content == image()


def test_legacy_history_replay_preserves_hash_and_integer_costs(clients):
    client, _ = clients
    vehicle = create_vehicle(client)
    response = add(client, vehicle)
    with client.app.state.session_factory() as db:
        record = db.get(KnowledgeRecord, response.json()["id"])
        payload = {key: getattr(record, key) for key in ("vehicle_id", "service_type", "service_date", "mileage", "shop_name", "parts_source", "parts_description", "notes")}
        assert record.payload_hash == hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    assert add(client, vehicle, cost_cents=None).json()["id"] == response.json()["id"]
    assert add(client, vehicle, key="bad-cost", cost_cents=12.34).status_code == 422
    assert add(client, vehicle, key="negative-cost", cost_cents=-1).status_code == 422
    assert add(client, vehicle, key="mods", service_type="modification", cost_cents=250000).status_code == 201


def test_worker_erases_abandoned_staging_and_retries_failed_file_delete(clients, monkeypatch):
    from datetime import timedelta
    from estimoto_plus.models import now
    from estimoto_plus.receipts import reconcile_receipts
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()["id"]
    key = str(uuid4())
    receipt = upload(client, rid, key).json()
    with client.app.state.session_factory() as db:
        row = db.get(KnowledgeReceipt, receipt["id"])
        row.status = "staging"
        row.created_at = now() - timedelta(days=2)
        target = Path(client.app.state.settings.photo_dir)/"receipts"/row.storage_name
        target.with_suffix(".pending").write_bytes(b"partial")
        db.commit()
    original_unlink = Path.unlink
    def failed_unlink(path, *args, **kwargs):
        if path == target:
            raise OSError("simulated unavailable disk")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", failed_unlink)
    reconcile_receipts(client.app.state.session_factory, client.app.state.settings)
    assert client.get("/v1/knowledge", headers=h("alice")).json()["records"][0]["receipts"] == []
    with client.app.state.session_factory() as db:
        assert db.get(KnowledgeReceipt, receipt["id"]).status == "deleted"
        assert db.get(KnowledgeReceipt, receipt["id"]).cleanup_retry_at is not None
        db.get(KnowledgeReceipt, receipt["id"]).cleanup_retry_at = now() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(Path, "unlink", original_unlink)
    reconcile_receipts(client.app.state.session_factory, client.app.state.settings)
    assert not target.exists() and not target.with_suffix(".pending").exists()
    assert upload(client, rid, key).status_code == 410


def _linked_pdf(action):
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    annotation = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([NumberObject(v) for v in (0, 0, 100, 100)]), NameObject("/A"): action})
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_receipt_pdf_web_links_are_accepted_and_active_links_rejected(clients):
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject
    client, _ = clients
    rid = add(client, create_vehicle(client)).json()["id"]
    def uri(target):
        return DictionaryObject({NameObject("/Type"): NameObject("/Action"), NameObject("/S"): NameObject("/URI"),
                                 NameObject("/URI"): TextStringObject(target)})
    # Receipts exported from shop software and email carry plain web links.
    assert upload(client, rid, data=_linked_pdf(uri("https://services.example.com/invoice/1")),
                  mime="application/pdf", filename="shop-receipt.pdf").status_code == 201
    assert upload(client, rid, data=_linked_pdf(uri("mailto:service@example.com")),
                  mime="application/pdf", filename="mail.pdf").status_code == 201
    # Anything that could run or open something else stays rejected.
    assert upload(client, rid, data=_linked_pdf(uri("javascript:alert(1)")), mime="application/pdf").status_code == 415
    assert upload(client, rid, data=_linked_pdf(uri("file:///etc/passwd")), mime="application/pdf").status_code == 415
    launch = DictionaryObject({NameObject("/S"): NameObject("/Launch"), NameObject("/F"): TextStringObject("calc.exe")})
    assert upload(client, rid, data=_linked_pdf(launch), mime="application/pdf").status_code == 415
    chained = uri("https://example.com")
    chained[NameObject("/Next")] = launch
    assert upload(client, rid, data=_linked_pdf(chained), mime="application/pdf").status_code == 415
