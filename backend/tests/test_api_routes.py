from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import db.chroma_manager as cm_mod
    import services.workspace_service as ws_mod

    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(ws_dir))
    monkeypatch.setattr(cm_mod, "WORKSPACES_DIR", str(ws_dir))

    new_ws = ws_mod.WorkspaceService()
    monkeypatch.setattr(ws_mod, "workspace_service", new_ws)
    import api.workspace_routes as wr_mod
    monkeypatch.setattr(wr_mod, "workspace_service", new_ws)
    return TestClient(app)


def test_cors_default_origin(client: TestClient):
    res = client.get("/", headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_workspace_crud(client: TestClient):
    r = client.post("/workspace/create", json={"name": "test"})
    assert r.status_code == 200
    ws = r.json()
    assert ws["name"] == "test"
    assert "id" in ws

    r2 = client.get("/workspace")
    assert r2.status_code == 200
    assert any(w["id"] == ws["id"] for w in r2.json())

    r3 = client.post("/workspace/switch", json={"workspace_id": ws["id"]})
    assert r3.status_code == 200

    r4 = client.delete(f"/workspace/{ws['id']}")
    assert r4.status_code == 200


def test_git_apply_path_traversal(client: TestClient, tmp_path: Path):
    r = client.post("/workspace/create", json={"name": "t"})
    ws = r.json()
    folder = tmp_path / "repo"
    folder.mkdir()
    client.post("/workspace/add-folder", json={"workspace_id": ws["id"], "folder_path": str(folder)})

    res = client.post(
        "/git/apply",
        json={
            "workspace_id": ws["id"],
            "file_path": "../evil.txt",
            "original": "",
            "replacement": "x",
        },
    )
    assert res.status_code in (400, 403)
