from pathlib import Path
import base64

from fastapi.testclient import TestClient

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
