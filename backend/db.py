from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

SCHEMA_VERSION = "1"


class Base(DeclarativeBase):
    pass


class Database:
    """Owns the SQLite engine so tests and restore can use isolated databases."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get(
            "REACTION_LIBRARY_DATABASE_URL", "sqlite:///reaction_library.sqlite3"
        )
        self.engine = self._make_engine(self.database_url)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    @staticmethod
    def _make_engine(url: str) -> Engine:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
                cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        return engine

    @property
    def file_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix) or self.database_url == "sqlite:///:memory:":
            raise ValueError("backup and restore require a file-backed SQLite database")
        return Path(self.database_url.removeprefix(prefix)).resolve()

    def create_all(self) -> None:
        from backend.models import SchemaMetadata

        Base.metadata.create_all(self.engine)
        with self.session_factory() as session:
            row = session.get(SchemaMetadata, "schema_version")
            if row is None:
                session.add(SchemaMetadata(key="schema_version", value=SCHEMA_VERSION))
                session.commit()

    def session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()

    def backup_to(self, target: Path) -> None:
        """Use SQLite's backup API for a transactionally consistent snapshot."""
        source = sqlite3.connect(self.file_path)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
