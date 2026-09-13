from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import create_engine, pool
from estimoto_plus.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
