from pathlib import Path
import base64
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend.db import SCHEMA_REVISION, SchemaContractError
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
