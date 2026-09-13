"""Optional real PostgreSQL concurrency proof in an isolated local schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from estimoto_plus.models import Customer


def test_parallel_first_signin_preserves_profile_without_read_writes(tmp_path):
    supplied = os.getenv("PLUS_TEST_POSTGRES_URL")
    if not supplied:
        pytest.skip("PLUS_TEST_POSTGRES_URL is needed for real PostgreSQL proof")
    url = make_url(supplied)
    if url.host not in (None, "localhost", "127.0.0.1") or not any(word in (url.database or "") for word in ("test", "launch")):
        pytest.fail("Use a local disposable test database")
    schema = "plus_auth_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    app = None
    try:
        scoped = url.update_query_dict({"options": f"-csearch_path={schema}"})
        settings = Settings(database_url=scoped.render_as_string(hide_password=False), environment="test",
                            photo_dir=str(tmp_path / "photos"), worker_enabled=False)
        app = create_app(settings, auth_verifier=lambda _: {
            "id": "one-authenticated-person", "email": "qa@example.test", "email_confirmed_at": "confirmed"})
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer fixture-only"}
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: client.get("/v1/knowledge", headers=headers), range(16)))
            assert [r.status_code for r in results] == [200] * 16
            assert client.put("/v1/profile", headers=headers, json={"name": "Saved profile", "postal_code": "80202"}).status_code == 200
            writes = []
            def track(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                    writes.append(statement)
            event.listen(app.state.engine, "before_cursor_execute", track)
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(pool.map(lambda _: client.get("/v1/bootstrap", headers=headers), range(16)))
                assert all(r.status_code == 200 and r.json()["profile"]["name"] == "Saved profile" for r in responses)
                assert writes == []
            finally:
                event.remove(app.state.engine, "before_cursor_execute", track)
            with app.state.session_factory() as db:
                assert db.scalar(select(func.count()).select_from(Customer)) == 1
    finally:
        if app:
            app.state.engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
