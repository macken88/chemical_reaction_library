from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal, InvalidOperation
import json

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# This is a schema *revision*, not a user supplied version label.  A database
# without this exact revision is never silently treated as current.
SCHEMA_REVISION = "2026-08-14.3"
SCHEMA_VERSION = SCHEMA_REVISION  # compatibility name used by the HTTP contract
VALIDATION_MODES = {"FULL", "REPEAT_UNIT", "LOCAL", "LIMITED"}
CHECK_STATUSES = {"PASS", "WARNING", "FAIL", "NOT_EVALUABLE", "INFO"}
COMPONENT_ROLES = {"REACTANT", "PRODUCT", "CONDITION"}

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


def validate_sqlite_schema(path: Path, *, require_current_revision: bool = True) -> str:
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
            if require_current_revision:
                if revision is None:
                    raise SchemaContractError("schema_revision is missing")
                if revision[0] != SCHEMA_REVISION:
                    raise SchemaContractError(f"unsupported schema revision: {revision[0]}")
            # Exercise the core relationship tables rather than relying on DDL alone.
            connection.execute("SELECT id, reaction_smiles FROM reactions LIMIT 1").fetchall()
            connection.execute("SELECT reaction_id, role, canonical_smiles FROM components LIMIT 1").fetchall()
            connection.execute("SELECT reaction_id, validator_version FROM validation_results LIMIT 1").fetchall()
            connection.execute("SELECT reaction_id, tag_id FROM reaction_tags LIMIT 1").fetchall()
            for reaction_id, mode, reaction_smiles in connection.execute("SELECT id, validation_mode, reaction_smiles FROM reactions"):
                if mode not in VALIDATION_MODES:
                    raise SchemaContractError(f"reaction {reaction_id} has invalid validation_mode")
                if reaction_smiles is not None and not isinstance(reaction_smiles, str):
                    raise SchemaContractError(f"reaction {reaction_id} has an invalid reaction_smiles value")
            for component_id, role, coefficient, structure in connection.execute("SELECT id, role, coefficient, structure FROM components"):
                if role not in COMPONENT_ROLES or not isinstance(structure, str) or not structure:
                    raise SchemaContractError(f"component {component_id} has invalid required domain values")
                if coefficient != "n":
                    try:
                        numeric = Decimal(coefficient)
                        if not numeric.is_finite() or numeric <= 0:
                            raise InvalidOperation
                    except (InvalidOperation, TypeError, ValueError):
                        raise SchemaContractError(f"component {component_id} has invalid coefficient")
            for row in connection.execute("SELECT id, validation_mode, representation_status, structure_status, element_balance_status, charge_balance_status, mapping_status, element_difference_json, warnings_json, validator_version, validated_at FROM validation_results"):
                result_id, mode, *statuses, element_json, warning_json, validator_version, validated_at = row
                if mode not in VALIDATION_MODES or any(item not in CHECK_STATUSES for item in statuses):
                    raise SchemaContractError(f"validation result {result_id} has invalid enum values")
                if not validator_version or validated_at is None:
                    raise SchemaContractError(f"validation result {result_id} is missing required values")
                try:
                    if not isinstance(json.loads(element_json), dict) or not isinstance(json.loads(warning_json), list):
                        raise ValueError
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise SchemaContractError(f"validation result {result_id} has invalid JSON fields")
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as exc:
        raise SchemaContractError(f"invalid SQLite database: {exc}") from exc
    return SCHEMA_REVISION


def _sqlite_backup(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def migrate_legacy_schema_v1(path: Path) -> bool:
    """Migrate only the known schema_version=1 metadata contract transactionally."""
    try:
        validate_sqlite_schema(path, require_current_revision=False)
        connection = sqlite3.connect(path)
        try:
            legacy = connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
            revision = connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_revision'").fetchone()
        finally:
            connection.close()
    except SchemaContractError:
        raise
    if revision is not None:
        return False
    if legacy is None or legacy[0] != "1":
        raise SchemaContractError("database does not declare a supported legacy schema_version=1")
    snapshot = path.with_suffix(path.suffix + ".legacy-v1-pre-migration.sqlite3")
    _sqlite_backup(path, snapshot)
    try:
        connection = sqlite3.connect(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO schema_metadata (key, value) VALUES ('schema_revision', ?)", (SCHEMA_REVISION,))
            connection.commit()
        finally:
            connection.close()
        validate_sqlite_schema(path)
    except Exception as exc:
        try:
            os.replace(snapshot, path)
        except OSError as rollback_exc:
            raise SchemaContractError(f"legacy migration failed and rollback failed: {rollback_exc}") from exc
        raise SchemaContractError(f"legacy migration failed; snapshot restored: {exc}") from exc
    return True


class Database:
    """Serializes library access and owns safe file-backed SQLite replacement."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get("REACTION_LIBRARY_DATABASE_URL", "sqlite:///reaction_library.sqlite3")
        self._condition = threading.Condition(threading.Lock())
        self._maintenance_active = False
        self._active_sessions = 0
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

        with self.maintenance():
            if self.database_url == "sqlite:///:memory:":
                Base.metadata.create_all(self.engine)
                with self.session_factory() as session:
                    session.add(SchemaMetadata(key="schema_revision", value=SCHEMA_REVISION))
                    session.commit()
                return
            path = self.file_path
            if path.exists():
                try:
                    validate_sqlite_schema(path)
                except SchemaContractError as exc:
                    if "schema_revision is missing" not in str(exc):
                        raise
                    migrate_legacy_schema_v1(path)
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
        with self._condition:
            while self._maintenance_active:
                self._condition.wait()
            self._maintenance_active = True
            while self._active_sessions:
                self._condition.wait()
        try:
            yield
        finally:
            with self._condition:
                self._maintenance_active = False
                self._condition.notify_all()

    def session(self) -> Generator[Session, None, None]:
        with self._condition:
            while self._maintenance_active:
                self._condition.wait()
            self._active_sessions += 1
        try:
            session = self.session_factory()
        except Exception:
            with self._condition:
                self._active_sessions -= 1
                self._condition.notify_all()
            raise
        try:
            yield session
        finally:
            session.close()
            with self._condition:
                self._active_sessions -= 1
                self._condition.notify_all()

    def dispose(self) -> None:
        self.engine.dispose()

    def recreate_engine(self) -> None:
        self.dispose()
        self.engine = self._make_engine(self.database_url)
        self.session_factory = self._make_session_factory()

    def backup_to(self, target: Path) -> None:
        """Use SQLite's backup API for a transactionally consistent snapshot."""
        with self.maintenance():
            self._backup_to(target)

    def _backup_to(self, target: Path) -> None:
        """Caller must own maintenance mode."""
        source = sqlite3.connect(self.file_path)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    def health_check(self) -> str:
        return validate_sqlite_schema(self.file_path)

    def replace_with(self, candidate: Path, rollback_snapshot: Path) -> str:
        """Atomically install a prevalidated candidate, restoring on any failure."""
        with self.maintenance():
            try:
                validate_sqlite_schema(candidate)
            except SchemaContractError as exc:
                if "schema_revision is missing" not in str(exc):
                    raise
                migrate_legacy_schema_v1(candidate)
                validate_sqlite_schema(candidate)
            self._backup_to(rollback_snapshot)
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
