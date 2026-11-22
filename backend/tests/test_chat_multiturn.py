import json
from pathlib import Path

import pytest
from core.llm import LLMClient


def test_build_messages_structure_and_truncation(monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [], "files": []})

    client = LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "resolve_model", lambda _ws: "m")
    monkeypatch.setattr("core.rag.rag_service.search", lambda _ws, q, top_k=5: [])

    long_history = [{"role": "user", "content": "x" * 5000} for _ in range(5)]
    long_history.append({"role": "assistant", "content": "y" * 5000})

    messages = client.build_messages("ws", "short follow-up", history=long_history)
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    # history should be trimmed, not exceed window
    total = sum(len(m["content"]) for m in messages)
    assert total < 13000


def test_build_messages_rag_followup_query(monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [], "files": []})

    client = LLMClient(base_url="http://localhost:11434")
    captured = {}

    def fake_search(_ws, q, top_k=5):
        captured["q"] = q
        return []

    monkeypatch.setattr("core.rag.rag_service.search", fake_search)

    history = [{"role": "user", "content": "What is foo?"}]
    client.build_messages("ws", "and bar?", history=history)
    assert "What is foo?" in captured["q"]
    assert "and bar?" in captured["q"]


def test_generate_stream_ndjson_message_content(monkeypatch: pytest.MonkeyPatch):
    import requests

    lines = [
        json.dumps({"message": {"content": "hi"}, "done": False}),
        json.dumps({"message": {"content": "!"}, "done": True}),
    ]

    class FakeResponse:
        status_code = 200

        def iter_lines(self):
            for ln in lines:
                yield ln.encode()

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())

    client = LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "resolve_model", lambda _ws: "m")
    monkeypatch.setattr(client, "build_messages", lambda _ws, _q, history=None: [{"role": "user", "content": "p"}])

    events = list(client.generate_stream("ws", "q"))
    assert any('"response": "hi"' in e for e in events)
    assert any('"response": "!"' in e for e in events)
    assert any('"done": true' in e for e in events)


def test_chat_history_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(ws_dir))
    ws_mod.workspace_service = ws_mod.WorkspaceService()

    import api.workspace_routes as wr_mod

    monkeypatch.setattr(wr_mod, "workspace_service", ws_mod.workspace_service)

    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    # create workspace
    r = client.post("/workspace/create", json={"name": "chat"})
    ws = r.json()

    # initially empty
    h = client.get(f"/chat/history?workspace_id={ws['id']}")
    assert h.status_code == 200
    assert h.json()["messages"] == []

    # append via service to simulate
    ws_mod.workspace_service.append_chat_turn(ws["id"], "hello", "hi there")
    h2 = client.get(f"/chat/history?workspace_id={ws['id']}")
    assert len(h2.json()["messages"]) == 2

    # clear
    d = client.delete(f"/chat/history?workspace_id={ws['id']}")
    assert d.status_code == 200
    h3 = client.get(f"/chat/history?workspace_id={ws['id']}")
    assert h3.json()["messages"] == []
