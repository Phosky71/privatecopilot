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


def test_health(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: type("R", (), {"status_code": 200})())
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "ollama" in data
    assert "dependencies" in data

    def raise_conn(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", raise_conn)
    res2 = client.get("/health")
    assert res2.status_code == 200
    assert res2.json()["ollama"] is False


def test_model_and_persistence(client: TestClient):
    client.post("/workspace/create", json={"name": "m"})

    r2 = client.post("/model/set", json={"model_id": "mymodel"})
    assert r2.status_code == 200

    r3 = client.get("/model/current")
    assert r3.status_code == 200

    # state persists in tmp workspaces dir
    import services.workspace_service as ws_mod

    state = ws_mod.workspace_service.get_app_state()
    assert state.get("active_model_id") == "mymodel"


def test_fs_list(client: TestClient, tmp_path: Path):
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a.txt").write_text("hi", encoding="utf-8")

    res = client.get(f"/fs/list?path={d}")
    assert res.status_code == 200
    assert any(item["name"] == "a.txt" for item in res.json()["items"])

    res2 = client.get("/fs/list?path=/nonexistent/path/xyz")
    assert res2.status_code == 404


def test_chat_stream(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    # Create workspace with a folder
    r = client.post("/workspace/create", json={"name": "c"})
    ws = r.json()
    import tempfile

    d = Path(tempfile.mkdtemp())
    client.post("/workspace/add-folder", json={"workspace_id": ws["id"], "folder_path": str(d)})

    # Mock llm_client.generate_stream
    import core.llm as llm_mod

    def fake_stream(_ws, _q):
        yield "data: {\"response\": \"hi\", \"done\": false}\n\n"
        yield "data: {\"response\": \"\", \"done\": true}\n\n"

    monkeypatch.setattr(llm_mod.llm_client, "generate_stream", fake_stream)

    res = client.post("/chat/stream", json={"workspace_id": ws["id"], "query": "hello"})
    assert res.status_code == 200
    assert "hi" in res.text
