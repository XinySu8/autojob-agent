"""Engine / session management and schema migrations (Alembic)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """One per process. SQLite for local use and tests, PostgreSQL in Docker / production."""

    def __init__(self, url: str):
        self.url = url
        is_sqlite = url.startswith("sqlite")
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})
        if is_sqlite:
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        """Bring the schema to the latest revision. Safe to call on every start."""
        cfg = Config()
        cfg.set_main_option("script_location", str(resources.files("autojob") / "migrations"))
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Unit of work: commit on success, roll back on error."""
        s = self._sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")  # API server + CLI can use the file at the same time
    cur.close()
