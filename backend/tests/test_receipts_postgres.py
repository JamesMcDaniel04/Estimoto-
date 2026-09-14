"""Exercise the actual receipt transaction and migration on isolated PostgreSQL."""
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from estimoto_plus.app import create_app
from estimoto_plus.config import Settings
from test_receipts import (
    test_receipt_roundtrip_private_exact_replay_and_tombstone,
    test_full_record_delete_removes_files_and_derived_links,
    test_concurrent_same_operation_writes_one_attachment,
    test_lost_commit_ack_preserves_private_bytes_for_exact_retry,
    test_legacy_history_replay_preserves_hash_and_integer_costs,
)


@pytest.fixture
def clients(tmp_path, monkeypatch):
    supplied = os.getenv("PLUS_TEST_POSTGRES_URL")
    if not supplied:
        pytest.skip("PLUS_TEST_POSTGRES_URL is needed for PostgreSQL receipt proof")
    url = make_url(supplied)
    assert url.host in ("localhost", "127.0.0.1") and "test" in url.database
    database = "plus_receipt_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.begin() as db:
        db.execute(text(f'CREATE DATABASE "{database}"'))
    app = None
    try:
        scoped = url.set(database=database).render_as_string(hide_password=False)
        monkeypatch.setenv("DATABASE_URL", scoped)
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        proof = create_engine(scoped)
        with proof.connect() as db:
            assert db.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(:table)"),
                             {"table": "public.knowledge_receipts"}) is True
            for role in ("anon", "authenticated"):
                if db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                    assert db.scalar(text("SELECT has_table_privilege(:role,:table,'SELECT')"),
                                     {"role": role, "table": "public.knowledge_receipts"}) is False
        proof.dispose()
        settings = Settings(database_url=scoped, environment="test", worker_enabled=False,
                            photo_dir=str(tmp_path / "photos"))
        identities = {who: {"id": f"{who}-id", "email": f"{who}@example.test", "email_confirmed_at": "confirmed"}
                      for who in ("alice", "bob")}
        app = create_app(settings, auth_verifier=identities.get)
        with TestClient(app) as client:
            yield client, []
    finally:
        if app:
            app.state.engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()
