from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# This is a schema *revision*, not a user supplied version label.  A database
# without this exact revision is never silently treated as current.
SCHEMA_REVISION = "2026-08-14.2"
SCHEMA_VERSION = SCHEMA_REVISION  # compatibility name used by the HTTP contract

REQUIRED_SCHEMA: dict[str, set[str]] = {
    "reactions": {"id", "name", "reaction_smiles", "editor_structure_data", "validation_mode", "reagents_text", "process_text", "notes", "warning_reason", "created_at", "updated_at"},
    "components": {"id", "reaction_id", "role", "coefficient", "structure", "canonical_smiles", "display_name"},
    "validation_results": {"id", "reaction_id", "validation_mode", "representation_status", "structure_status", "element_balance_status", "charge_balance_status", "mapping_status", "bond_change_summary", "element_difference_json", "warnings_json", "validator_version", "validated_at"},
    "tags": {"id", "name"},
    "reaction_tags": {"reaction_id", "tag_id"},
    "schema_metadata": {"key", "value"},
}
REQUIRED_FOREIGN_KEYS: dict[str, set[tuple[str, str, str]]] = {
    "components": {("reaction_id", "reactions", "id")},
    "validation_results": {("reaction_id", "reactions", "id")},
    "reaction_tags": {("reaction_id", "reactions", "id"), ("tag_id", "tags", "id")},
}


class SchemaContractError(RuntimeError):
    pass


class Base(DeclarativeBase):
    pass


def validate_sqlite_schema(path: Path) -> str:
    """Verify that a candidate is a complete, current library database."""
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise SchemaContractError("SQLite integrity_check failed")
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise SchemaContractError("SQLite foreign_key_check failed")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing_tables = set(REQUIRED_SCHEMA) - tables
            if missing_tables:
                raise SchemaContractError("missing required tables: " + ", ".join(sorted(missing_tables)))
            unexpected_tables = tables - set(REQUIRED_SCHEMA) - {"sqlite_sequence"}
            if unexpected_tables:
                raise SchemaContractError("unexpected tables for current schema: " + ", ".join(sorted(unexpected_tables)))
            for table, required_columns in REQUIRED_SCHEMA.items():
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                missing_columns = required_columns - columns
                if missing_columns:
                    raise SchemaContractError(f"{table} is missing required columns: {', '.join(sorted(missing_columns))}")
                extra_columns = columns - required_columns
                if extra_columns:
                    raise SchemaContractError(f"{table} has columns outside the current schema contract: {', '.join(sorted(extra_columns))}")
            for table, expected_foreign_keys in REQUIRED_FOREIGN_KEYS.items():
                foreign_keys = {(row[3], row[2], row[4]) for row in connection.execute(f"PRAGMA foreign_key_list({table})")}
                if not expected_foreign_keys.issubset(foreign_keys):
                    raise SchemaContractError(f"{table} foreign-key contract is incomplete")
            revision = connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_revision'").fetchone()
            if revision is None:
                raise SchemaContractError("schema_revision is missing")
            if revision[0] != SCHEMA_REVISION:
                raise SchemaContractError(f"unsupported schema revision: {revision[0]}")
            # Exercise the core relationship tables rather than relying on DDL alone.
            connection.execute("SELECT id, reaction_smiles FROM reactions LIMIT 1").fetchall()
            connection.execute("SELECT reaction_id, role, canonical_smiles FROM components LIMIT 1").fetchall()
            connection.execute("SELECT reaction_id, validator_version FROM validation_results LIMIT 1").fetchall()
            connection.execute("SELECT reaction_id, tag_id FROM reaction_tags LIMIT 1").fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as exc:
        raise SchemaContractError(f"invalid SQLite database: {exc}") from exc
    return SCHEMA_REVISION


class Database:
    """Serializes library access and owns safe file-backed SQLite replacement."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get(
            "REACTION_LIBRARY_DATABASE_URL", "sqlite:///backend/data/reaction_library.sqlite3"
        )
        self._lock = threading.RLock()
        self.engine = self._make_engine(self.database_url)
        self.session_factory = self._make_session_factory()

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

    def _make_session_factory(self) -> sessionmaker[Session]:
        return sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    @property
    def file_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix) or self.database_url == "sqlite:///:memory:":
            raise ValueError("backup and restore require a file-backed SQLite database")
        return Path(self.database_url.removeprefix(prefix)).resolve()

    def create_all(self) -> None:
        """Initialize only a new database; reject partial, old, or future files."""
        from backend.models import SchemaMetadata

        with self._lock:
            if self.database_url == "sqlite:///:memory:":
                Base.metadata.create_all(self.engine)
                with self.session_factory() as session:
                    session.add(SchemaMetadata(key="schema_revision", value=SCHEMA_REVISION))
                    session.commit()
                return
            path = self.file_path
            if path.exists():
                validate_sqlite_schema(path)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            Base.metadata.create_all(self.engine)
            with self.session_factory() as session:
                session.add(SchemaMetadata(key="schema_revision", value=SCHEMA_REVISION))
                session.commit()
            validate_sqlite_schema(path)

    @contextmanager
    def maintenance(self) -> Iterator[None]:
        with self._lock:
            yield

    def session(self) -> Generator[Session, None, None]:
        # Every normal DB operation shares the same lock as backup/restore.  This
        # is deliberately conservative for a small single-user SQLite library.
        with self._lock:
            session = self.session_factory()
            try:
                yield session
            finally:
                session.close()

    def dispose(self) -> None:
        self.engine.dispose()

    def recreate_engine(self) -> None:
        self.dispose()
        self.engine = self._make_engine(self.database_url)
        self.session_factory = self._make_session_factory()

    def backup_to(self, target: Path) -> None:
        """Use SQLite's backup API for a transactionally consistent snapshot."""
        with self._lock:
            source = sqlite3.connect(self.file_path)
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()

    def health_check(self) -> str:
        with self._lock:
            return validate_sqlite_schema(self.file_path)

    def replace_with(self, candidate: Path, rollback_snapshot: Path) -> str:
        """Atomically install a prevalidated candidate, restoring on any failure."""
        with self._lock:
            validate_sqlite_schema(candidate)
            self.backup_to(rollback_snapshot)
            destination = self.file_path
            self.recreate_engine()
            try:
                os.replace(candidate, destination)
                self.recreate_engine()
                return self.health_check()
            except Exception as exc:
                try:
                    self.recreate_engine()
                    os.replace(rollback_snapshot, destination)
                    self.recreate_engine()
                    self.health_check()
                except Exception as rollback_exc:
                    raise SchemaContractError(f"restore failed and rollback failed: {rollback_exc}") from exc
                raise SchemaContractError(f"restore failed; previous database was restored: {exc}") from exc
