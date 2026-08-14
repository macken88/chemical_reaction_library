from pathlib import Path
import base64
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from backend.db import Database, SCHEMA_REVISION, SchemaContractError
from backend.main import create_app


def payload(**extra: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "mapped ethane",
        "reaction_smiles": "[CH3:1][CH3:2]>>[CH3:1][CH3:2]",
        "components": [
            {"role": "REACTANT", "structure": "[CH3:1][CH3:2]"},
            {"role": "PRODUCT", "structure": "[CH3:1][CH3:2]"},
        ],
        "reagents_text": "ethyl reagent",
        "process_text": "ambient",
        "notes": "library note",
        "tags": ["alkane", "example"],
    }
    data.update(extra)
    return data


def test_crud_validate_search_revalidate_and_ai_copy(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    with TestClient(app) as client:
        parsed = client.post("/api/reactions/parse", json={"content": "CC>>CC"})
        assert parsed.status_code == 200
        created = client.post("/api/reactions", json=payload())
        assert created.status_code == 201, created.text
        reaction_id = created.json()["id"]
        duplicate = client.post("/api/reactions/validate", json=payload())
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate_reaction_ids"] == [reaction_id]
        listed = client.get("/api/reactions")
        assert listed.json()["total"] == 1
        searched = client.post("/api/reactions/search", json={"tag": "alkane", "reagent": "ethyl"})
        assert searched.json()["total"] == 1
        substructure = client.post("/api/search/substructure", json={"structure": "CC", "target": "REACTANT"})
        assert substructure.json()["total"] == 1
        updated = client.put(f"/api/reactions/{reaction_id}", json=payload(name="edited", tags=["edited"]))
        assert updated.status_code == 200
        assert updated.json()["name"] == "edited"
        assert client.post(f"/api/reactions/{reaction_id}/revalidate").status_code == 200
        assert client.post("/api/reactions/revalidate-all").json()["total"] == 1
        assert "Coverage: FULL" in client.get(f"/api/reactions/{reaction_id}/ai-copy").json()["text"]
        assert client.delete(f"/api/reactions/{reaction_id}").status_code == 204
        assert client.get("/api/reactions").json()["total"] == 0


def test_backup_restore_requires_confirmation_and_restores_whole_database(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    with TestClient(app) as client:
        assert client.post("/api/reactions", json=payload()).status_code == 201
        backup = client.post("/api/backup")
        assert backup.status_code == 200
        token = backup.json()["backup_token"]
        downloaded = client.get(f"/api/backup/{token}")
        assert downloaded.status_code == 200
        encoded_backup = base64.b64encode(downloaded.content).decode()
        assert client.post("/api/reactions", json=payload(name="later")).status_code == 201
        rejected = client.post("/api/restore", json={"backup_token": token, "confirmation_token": "wrong"})
        assert rejected.status_code == 422
        restored = client.post("/api/restore", json={"backup_base64": encoded_backup, "confirmation_token": "RESTORE_LIBRARY"})
        assert restored.status_code == 200, restored.text
        assert client.get("/api/reactions").json()["total"] == 1


def test_restore_rejects_metadata_only_database_without_changing_current_data(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    malformed = tmp_path / "metadata-only.sqlite3"
    connection = sqlite3.connect(malformed)
    connection.execute("CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO schema_metadata VALUES ('schema_revision', ?)", (SCHEMA_REVISION,))
    connection.commit()
    connection.close()
    with TestClient(app) as client:
        assert client.post("/api/reactions", json=payload()).status_code == 201
        encoded = base64.b64encode(malformed.read_bytes()).decode()
        response = client.post("/api/restore", json={"backup_base64": encoded, "confirmation_token": "RESTORE_LIBRARY"})
        assert response.status_code == 422
        assert client.get("/api/reactions").json()["total"] == 1


def test_component_search_is_canonical_exact_and_requires_both_sides(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    with TestClient(app) as client:
        first = payload(reagents_text="", components=[
            {"role": "REACTANT", "structure": "[CH3:1][CH3:2]", "display_name": "special display reagent"},
            {"role": "PRODUCT", "structure": "[CH3:1][CH3:2]"},
        ])
        second = payload(name="alcohol", reaction_smiles="[CH3:1][CH3:2]>>[CH3:1][OH:2]", components=[
            {"role": "REACTANT", "structure": "[CH3:1][CH3:2]"},
            {"role": "PRODUCT", "structure": "[CH3:1][OH:2]"},
        ])
        assert client.post("/api/reactions", json=first).status_code == 201
        assert client.post("/api/reactions", json=second).status_code == 201
        by_display_name = client.post("/api/reactions/search", json={"reagent": "special display"})
        assert by_display_name.json()["total"] == 1
        exact_and = client.post("/api/reactions/search", json={"reactant": "C(C)", "product": "CO"})
        assert exact_and.status_code == 200
        assert exact_and.json()["total"] == 1
        impossible_and = client.post("/api/reactions/search", json={"reactant": "CC", "product": "CC"})
        assert impossible_and.json()["total"] == 1


def test_startup_rejects_partial_or_unknown_schema_revision(tmp_path: Path) -> None:
    partial = tmp_path / "partial.sqlite3"
    connection = sqlite3.connect(partial)
    connection.execute("CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO schema_metadata VALUES ('schema_revision', 'future')")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError):
        create_app(f"sqlite:///{partial}")
    future = tmp_path / "future.sqlite3"
    create_app(f"sqlite:///{future}").state.database.dispose()
    connection = sqlite3.connect(future)
    connection.execute("UPDATE schema_metadata SET value = 'future' WHERE key = 'schema_revision'")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="unsupported schema revision"):
        create_app(f"sqlite:///{future}")


def test_restore_engine_health_failure_rolls_back_original_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "library.sqlite3"
    app = create_app(f"sqlite:///{path}")
    with TestClient(app) as client:
        assert client.post("/api/reactions", json=payload(name="original")).status_code == 201
    database = app.state.database
    candidate, rollback = tmp_path / "candidate.sqlite3", tmp_path / "rollback.sqlite3"
    database.backup_to(candidate)
    connection = sqlite3.connect(candidate)
    connection.execute("UPDATE reactions SET name = 'candidate'")
    connection.commit()
    connection.close()
    original_health_check = database.health_check
    calls = 0

    def fail_once() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SchemaContractError("simulated post-replace health failure")
        return original_health_check()

    monkeypatch.setattr(database, "health_check", fail_once)
    with pytest.raises(SchemaContractError, match="previous database was restored"):
        database.replace_with(candidate, rollback)
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT name FROM reactions").fetchone()[0] == "original"
    connection.close()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("UPDATE components SET role = 'BOGUS'", "invalid required domain"),
        ("UPDATE validation_results SET warnings_json = '{broken'", "invalid JSON"),
    ],
)
def test_restore_rejects_invalid_domain_values_before_replacement(tmp_path: Path, mutation: str, expected: str) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    with TestClient(app) as client:
        assert client.post("/api/reactions", json=payload(name="original")).status_code == 201
        backup = client.post("/api/backup").json()
        raw = client.get(f"/api/backup/{backup['backup_token']}").content
        candidate = tmp_path / "invalid-domain.sqlite3"
        candidate.write_bytes(raw)
        connection = sqlite3.connect(candidate)
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(mutation)
        connection.commit()
        connection.close()
        response = client.post("/api/restore", json={"backup_base64": base64.b64encode(candidate.read_bytes()).decode(), "confirmation_token": "RESTORE_LIBRARY"})
        assert response.status_code == 422
        assert expected in response.json()["detail"]
        assert client.get("/api/reactions").json()["items"][0]["name"] == "original"


def test_limited_ai_copy_includes_editor_data_and_reason(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    with TestClient(app) as client:
        created = client.post("/api/reactions", json={
            "name": "opaque",
            "editor_structure_data": "Ketcher SRU payload",
            "components": [
                {"role": "REACTANT", "structure": "editor-only-polymer"},
                {"role": "PRODUCT", "structure": "editor-only-polymer"},
            ],
        })
        assert created.status_code == 201
        copied = client.get(f"/api/reactions/{created.json()['id']}/ai-copy").json()["text"]
        assert "Reaction SMILES unavailable" in copied
        assert "Ketcher SRU payload" in copied


def test_parallel_gets_finish_and_restore_waits_for_active_session(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    app = create_app(f"sqlite:///{path}")
    with TestClient(app) as client:
        assert client.post("/api/reactions", json=payload()).status_code == 201
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=20) as pool:
            responses = list(pool.map(lambda _: client.get("/api/reactions").status_code, range(40)))
        assert responses == [200] * 40
        assert time.monotonic() - started < 5
    database = app.state.database
    candidate, rollback = tmp_path / "candidate.sqlite3", tmp_path / "rollback.sqlite3"
    database.backup_to(candidate)
    session_generator = database.session()
    next(session_generator)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(database.replace_with, candidate, rollback)
        time.sleep(0.1)
        assert not future.done()
        session_generator.close()
        assert future.result(timeout=5) == SCHEMA_REVISION


def test_known_legacy_v1_database_is_snapshotted_and_migrated(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    current = create_app(f"sqlite:///{source}")
    current.state.database.dispose()
    connection = sqlite3.connect(source)
    connection.execute("DELETE FROM schema_metadata WHERE key = 'schema_revision'")
    connection.execute("INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '1')")
    connection.commit()
    connection.close()
    migrated = create_app(f"sqlite:///{source}")
    assert migrated.state.database.health_check() == SCHEMA_REVISION
    assert (tmp_path / "source.sqlite3.legacy-v1-pre-migration.sqlite3").is_file()


def test_default_root_path_migrates_known_legacy_v1_at_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert Database().database_url == "sqlite:///reaction_library.sqlite3"
    root_path = tmp_path / "reaction_library.sqlite3"
    seeded = create_app(f"sqlite:///{root_path}")
    seeded.state.database.dispose()
    connection = sqlite3.connect(root_path)
    connection.execute("DELETE FROM schema_metadata WHERE key = 'schema_revision'")
    connection.execute("INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '1')")
    connection.commit()
    connection.close()
    app = create_app(initialize=False)
    with TestClient(app) as client:
        assert client.get("/api/schema-version").json()["schema_version"] == SCHEMA_REVISION
    assert (tmp_path / "reaction_library.sqlite3.legacy-v1-pre-migration.sqlite3").is_file()


def test_large_backup_upload_restore_round_trip(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'library.sqlite3'}")
    with TestClient(app) as client:
        assert client.post("/api/reactions", json=payload(notes="x" * (13 * 1024 * 1024))).status_code == 201
        backup = client.post("/api/backup").json()
        raw = client.get(f"/api/backup/{backup['backup_token']}").content
        assert len(raw) > 12 * 1024 * 1024
        assert client.post("/api/reactions", json=payload(name="later")).status_code == 201
        restored = client.post(
            "/api/restore/upload",
            data={"confirmation_token": "RESTORE_LIBRARY"},
            files={"backup_file": ("library.sqlite3", raw, "application/vnd.sqlite3")},
        )
        assert restored.status_code == 200, restored.text
        assert client.get("/api/reactions").json()["total"] == 1
