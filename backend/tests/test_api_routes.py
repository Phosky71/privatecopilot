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

    def fake_stream(_ws, _q, history=None):
        yield "data: {\"response\": \"hi\", \"done\": false}\n\n"
        yield "data: {\"response\": \"\", \"done\": true}\n\n"

    monkeypatch.setattr(llm_mod.llm_client, "generate_stream", fake_stream)

    res = client.post("/chat/stream", json={"workspace_id": ws["id"], "query": "hello"})
    assert res.status_code == 200
    assert "hi" in res.text


def test_open_workspace(client: TestClient, tmp_path: Path):
    folder = tmp_path / "myproj"
    folder.mkdir()

    r = client.post("/workspace/open", json={"folder_path": str(folder)})
    assert r.status_code == 200
    ws = r.json()
    assert ws["name"] == "myproj"
    assert ws["folders"] == [str(folder.resolve())]

    # Reuse same resolved path
    r2 = client.post("/workspace/open", json={"folder_path": str(folder / "." )})
    assert r2.status_code == 200
    assert r2.json()["id"] == ws["id"]

    # Custom name
    folder2 = tmp_path / "other"
    folder2.mkdir()
    r3 = client.post("/workspace/open", json={"folder_path": str(folder2), "name": "Custom"})
    assert r3.status_code == 200
    assert r3.json()["name"] == "Custom"

    # Nonexistent
    r4 = client.post("/workspace/open", json={"folder_path": str(tmp_path / "nope")})
    assert r4.status_code == 400

    # File instead of folder
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    r5 = client.post("/workspace/open", json={"folder_path": str(f)})
    assert r5.status_code == 400


def test_git_status_uninitialized(client: TestClient, tmp_path: Path):
    folder = tmp_path / "repo"
    folder.mkdir()
    r = client.post("/workspace/create", json={"name": "t"})
    ws = r.json()
    client.post("/workspace/add-folder", json={"workspace_id": ws["id"], "folder_path": str(folder)})

    res = client.get(f"/git/status?workspace_id={ws['id']}")
    assert res.status_code == 200
    data = res.json()
    assert data["initialized"] is False
    assert data["branch"] is None
    assert not (folder / ".git").exists()


def test_git_config(client: TestClient):
    r = client.get("/git/config")
    assert r.status_code == 200
    assert r.json()["git_init_policy"] == "ask"

    for policy in ("auto", "never", "ask"):
        r2 = client.post("/git/config", json={"git_init_policy": policy})
        assert r2.status_code == 200
        assert r2.json()["git_init_policy"] == policy

    r3 = client.get("/git/config")
    assert r3.json()["git_init_policy"] == "ask"

    r4 = client.post("/git/config", json={"git_init_policy": "invalid"})
    assert r4.status_code == 422


def test_git_apply_uninitialized_policies(client: TestClient, tmp_path: Path):
    folder = tmp_path / "repo"
    folder.mkdir()
    target = folder / "a.txt"
    target.write_text("hello\n", encoding="utf-8")

    def setup_workspace():
        r = client.post("/workspace/create", json={"name": "t"})
        ws = r.json()
        client.post("/workspace/add-folder", json={"workspace_id": ws["id"], "folder_path": str(folder)})
        return ws

    # ask + no confirm -> 409 GIT_INIT_REQUIRED, no .git, file unchanged
    client.post("/git/config", json={"git_init_policy": "ask"})
    ws = setup_workspace()
    res = client.post("/git/apply", json={
        "workspace_id": ws["id"],
        "file_path": "a.txt",
        "original": "hello",
        "replacement": "hi",
        "confirm_git_init": False,
    })
    assert res.status_code == 409
    assert res.json().get("code") == "GIT_INIT_REQUIRED"
    assert not (folder / ".git").exists()
    assert target.read_text(encoding="utf-8") == "hello\n"

    # ask + confirm -> init + apply
    ws2 = setup_workspace()
    res2 = client.post("/git/apply", json={
        "workspace_id": ws2["id"],
        "file_path": "a.txt",
        "original": "hello",
        "replacement": "hi",
        "confirm_git_init": True,
    })
    assert res2.status_code == 200
    assert (folder / ".git").exists()

    # auto -> init + apply without confirm (fresh folder)
    folder2 = tmp_path / "repo2"
    folder2.mkdir()
    (folder2 / "a.txt").write_text("hello\n", encoding="utf-8")
    client.post("/git/config", json={"git_init_policy": "auto"})
    ws3 = client.post("/workspace/create", json={"name": "t3"}).json()
    client.post("/workspace/add-folder", json={"workspace_id": ws3["id"], "folder_path": str(folder2)})
    res3 = client.post("/git/apply", json={
        "workspace_id": ws3["id"],
        "file_path": "a.txt",
        "original": "hello",
        "replacement": "hi",
    })
    assert res3.status_code == 200
    assert (folder2 / ".git").exists()

    # never -> reject, no .git, file unchanged (fresh folder)
    folder3 = tmp_path / "repo3"
    folder3.mkdir()
    (folder3 / "a.txt").write_text("hello\n", encoding="utf-8")
    client.post("/git/config", json={"git_init_policy": "never"})
    ws4 = client.post("/workspace/create", json={"name": "t4"}).json()
    client.post("/workspace/add-folder", json={"workspace_id": ws4["id"], "folder_path": str(folder3)})
    res4 = client.post("/git/apply", json={
        "workspace_id": ws4["id"],
        "file_path": "a.txt",
        "original": "hello",
        "replacement": "hi",
        "confirm_git_init": True,
    })
    assert res4.status_code == 400
    assert not (folder3 / ".git").exists()
    assert (folder3 / "a.txt").read_text(encoding="utf-8") == "hello\n"

    # reset policy
    client.post("/git/config", json={"git_init_policy": "ask"})


def test_git_apply_existing_repo_any_policy(client: TestClient, tmp_path: Path):
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "a.txt").write_text("hello\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init"], cwd=folder, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=folder, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "init"], cwd=folder, check=True, capture_output=True)

    for policy in ("ask", "auto", "never"):
        client.post("/git/config", json={"git_init_policy": policy})
        r = client.post("/workspace/create", json={"name": f"t-{policy}"})
        ws = r.json()
        client.post("/workspace/add-folder", json={"workspace_id": ws["id"], "folder_path": str(folder)})
        res = client.post("/git/apply", json={
            "workspace_id": ws["id"],
            "file_path": "a.txt",
            "original": "hello",
            "replacement": "hi",
        })
        assert res.status_code == 200
        assert (folder / "a.txt").read_text(encoding="utf-8") == "hi\n"
        # restore file for next iteration
        (folder / "a.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=folder, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "reset"], cwd=folder, check=True, capture_output=True)

    client.post("/git/config", json={"git_init_policy": "ask"})
