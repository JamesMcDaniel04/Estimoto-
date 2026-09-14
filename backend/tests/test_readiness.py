"""The readiness probe must track the migration head, or a deploy that
migrates the database takes the service offline behind a failing health check."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from estimoto_plus.app import EXPECTED_SCHEMA_REVISION


def test_ready_revision_matches_alembic_head():
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert heads == [EXPECTED_SCHEMA_REVISION]
