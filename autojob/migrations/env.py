"""Alembic environment. Used by ``Database.migrate()`` (connection passed in) and by
developers running ``alembic revision --autogenerate`` (DATABASE_URL env var)."""

import os

from alembic import context
from sqlalchemy import create_engine

from autojob.models import Base

target_metadata = Base.metadata


def run() -> None:
    conn = context.config.attributes.get("connection")
    if conn is not None:
        _migrate(conn)
        return
    with create_engine(os.environ["DATABASE_URL"]).connect() as conn:
        _migrate(conn)
        conn.commit()


def _migrate(conn) -> None:
    # render_as_batch: lets ALTER TABLE migrations work on SQLite too
    context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run()
