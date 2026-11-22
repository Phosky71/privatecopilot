from pathlib import Path

import core.indexer as indexer_mod
import pytest
from core.indexer import Indexer


def test_progress_callback_phases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print('hi')", encoding="utf-8")
    (src / "b.py").write_text("print('bye')", encoding="utf-8")

    import services.workspace_service as ws_mod

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setattr(ws_mod.workspace_service, "_get_workspace_dir", lambda _ws: str(ws_dir))
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [str(src)], "files": []})
    monkeypatch.setattr(indexer_mod, "workspace_service", ws_mod.workspace_service)

    # mock embeddings
    class FakeEmb:
        def embed_texts(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(indexer_mod, "embedding_service", FakeEmb())

    events = []

    def cb(**kw):
        events.append(dict(kw))

    idx = Indexer()
    idx.index_workspace("ws", progress_callback=cb)

    phases = [e.get("phase") for e in events if "phase" in e]
    assert "scanning" in phases
    assert "indexing" in phases
    assert "completed" in phases
    last = events[-1]
    assert last.get("status") == "completed"
    assert last.get("percent") == 100.0
    assert last.get("indexed_files") == 2


def test_index_start_dedup_and_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print('hi')", encoding="utf-8")

    import services.workspace_service as ws_mod

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setattr(ws_mod.workspace_service, "_get_workspace_dir", lambda _ws: str(ws_dir))
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [str(src)], "files": []})
    monkeypatch.setattr(indexer_mod, "workspace_service", ws_mod.workspace_service)

    class FakeEmb:
        def embed_texts(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(indexer_mod, "embedding_service", FakeEmb())

    import api.index_routes as ir_mod

    # patch workspace service in api modules
    import api.workspace_routes as wr_mod
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(wr_mod, "workspace_service", ws_mod.workspace_service)
    fresh_indexer = indexer_mod.Indexer()
    monkeypatch.setattr(indexer_mod, "indexer", fresh_indexer)
    monkeypatch.setattr(ir_mod, "indexer", fresh_indexer)

    client = TestClient(app)

    r = client.post("/workspace/create", json={"name": "idx"})
    ws = r.json()
    client.post("/workspace/add-folder", json={"workspace_id": ws["id"], "folder_path": str(src)})

    # start
    s1 = client.post("/index/start", json={"workspace_id": ws["id"]})
    assert s1.status_code == 202

    # dedup: second start returns running state
    s2 = client.post("/index/start", json={"workspace_id": ws["id"]})
    assert s2.status_code == 202

    # status
    st = client.get(f"/index/status?workspace_id={ws['id']}")
    assert st.status_code == 200
    assert st.json()["workspace_id"] == ws["id"]

    # stream
    import time
    time.sleep(1)
    stream = client.get(f"/index/stream?workspace_id={ws['id']}")
    assert stream.status_code == 200
    assert "data:" in stream.text