import json
from pathlib import Path

import core.llm as llm_mod
import core.providers as prov_mod
import pytest
import requests
from core.llm import LLMClient
from core.providers import (
    normalize_openai_base,
)


@pytest.fixture
def isolated_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(prov_mod, "WORKSPACES_DIR", str(ws_dir))
    monkeypatch.setattr(prov_mod, "PROVIDERS_FILE", str(ws_dir / ".providers.json"))
    # also patch workspace_service for consistency
    import services.workspace_service as ws_mod
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(ws_dir))
    return ws_dir


def test_normalize_openai_base():
    assert normalize_openai_base("http://localhost:1234") == "http://localhost:1234/v1"
    assert normalize_openai_base("http://localhost:1234/v1") == "http://localhost:1234/v1"
    assert normalize_openai_base("http://localhost:1234/v1/chat/completions") == "http://localhost:1234/v1"
    assert normalize_openai_base("http://host/openai/v1") == "http://host/openai/v1"
    assert normalize_openai_base("http://host/v1beta") == "http://host/v1beta"


def test_autodetect_simultaneous(isolated_providers: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_get(url, *a, **k):
        if "11434" in url and url.endswith("/api/tags"):
            return type("R", (), {"status_code": 200, "json": lambda self: {"models": [{"name": "qwen"}]}})()
        if "1234" in url and url.endswith("/v1/models"):
            return type("R", (), {"status_code": 200, "json": lambda self: {"data": [{"id": "qwen"}]}})()
        if "8080" in url and url.endswith("/v1/models"):
            return type("R", (), {"status_code": 200, "json": lambda self: {"data": [{"id": "qwen"}]}})()
        return type("R", (), {"status_code": 404, "json": lambda self: {}})()

    monkeypatch.setattr("requests.get", fake_get)

    # set env to control ports
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8080")

    models, status, _default = prov_mod.discover_models()
    ids = [m["id"] for m in models]
    assert "ollama::qwen" in ids
    assert "lmstudio::qwen" in ids
    assert any(i.startswith("llamacpp") and i.endswith("::qwen") for i in ids)
    # providers_status contains all three
    names = [s["name"] for s in status]
    assert "Ollama" in names
    assert "LM Studio" in names
    assert "llama.cpp" in names


def test_false_positive_8080(isolated_providers: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_get(url, *a, **k):
        if "8080" in url:
            # HTML response
            r = type("R", (), {"status_code": 200})()
            r.text = "<html>not llm</html>"
            r.json = lambda: {"foo": "bar"}
            return r
        return type("R", (), {"status_code": 404, "json": lambda self: {}})()

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8080")

    models, _status, _default = prov_mod.discover_models()
    llamacpp_models = [m for m in models if m["provider_id"].startswith("llamacpp")]
    assert llamacpp_models == []


def test_streaming_openai_compatible(monkeypatch: pytest.MonkeyPatch):

    lines = [
        'data: {"choices":[{"delta":{"content":"hi"}}]}',
        'data: {"choices":[{"delta":{"content":""}}]}',
        'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}',
        'data: [DONE]',
    ]

    class FakeResponse:
        status_code = 200

        def iter_lines(self):
            for ln in lines:
                yield ln.encode()

    captured = {}

    def fake_post(url, *a, **k):
        captured["url"] = url
        captured["headers"] = k.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    # configure provider
    monkeypatch.setattr(prov_mod.provider_store, "get", lambda pid: {
        "id": pid, "provider_type": "openai_compatible",
        "base_url": "http://localhost:1234", "api_key": "secret-key-1234",
    })

    client = LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "resolve_model", lambda _ws: "prov::model")
    monkeypatch.setattr(client, "build_messages", lambda _ws, _q, history=None: [{"role": "user", "content": "p"}])

    events = list(client.generate_stream("ws", "q"))
    assert any('"response": "hi"' in e for e in events)
    assert captured["headers"].get("Authorization") == "Bearer secret-key-1234"
    assert "secret-key-1234" not in "".join(events)


def test_streaming_anthropic(monkeypatch: pytest.MonkeyPatch):

    lines = [
        'data: {"type":"content_block_delta","delta":{"text":"hello"}}',
        'data: {"type":"message_stop"}',
    ]

    class FakeResponse:
        status_code = 200

        def iter_lines(self):
            for ln in lines:
                yield ln.encode()

    captured = {}

    def fake_post(url, *a, **k):
        captured["url"] = url
        captured["headers"] = k.get("headers", {})
        captured["json"] = k.get("json", {})
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    monkeypatch.setattr(prov_mod.provider_store, "get", lambda pid: {
        "id": pid, "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com", "api_key": "sk-ant-1234",
    })

    client = LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "resolve_model", lambda _ws: "prov::claude")
    monkeypatch.setattr(client, "build_messages", lambda _ws, _q, history=None: [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ])

    events = list(client.generate_stream("ws", "q"))
    assert any('"response": "hello"' in e for e in events)
    assert captured["headers"].get("x-api-key") == "sk-ant-1234"
    assert captured["headers"].get("anthropic-version") == "2023-06-01"
    assert captured["json"].get("system") == "sys"
    assert "sk-ant-1234" not in "".join(events)


def test_provider_crud_and_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(prov_mod, "WORKSPACES_DIR", str(ws_dir))
    monkeypatch.setattr(prov_mod, "PROVIDERS_FILE", str(ws_dir / ".providers.json"))
    import services.workspace_service as ws_mod
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(ws_dir))

    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    # create provider with api key
    r = client.post("/model/providers", json={
        "name": "OpenAI",
        "provider_type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-super-secret-9999",
        "models": ["gpt-4o-mini"],
        "enabled": True,
    })
    assert r.status_code == 200
    pid = r.json()["provider"]["id"]

    # GET providers must not expose key
    r2 = client.get("/model/providers")
    assert r2.status_code == 200
    prov = r2.json()["providers"][0]
    assert prov["has_api_key"] is True
    assert "sk-super-secret-9999" not in json.dumps(r2.json())
    assert prov.get("api_key_masked") is not None

    # GET /model must not expose key
    r3 = client.get("/model")
    assert "sk-super-secret-9999" not in json.dumps(r3.json())

    # health must not expose key
    r4 = client.get("/health")
    assert "sk-super-secret-9999" not in json.dumps(r4.json())

    # update without key preserves
    r5 = client.put(f"/model/providers/{pid}", json={"name": "OpenAI Renamed"})
    assert r5.status_code == 200
    # verify preserved via store
    raw = prov_mod.provider_store.get(pid)
    assert raw["api_key"] == "sk-super-secret-9999"

    # update with clear_api_key
    r6 = client.put(f"/model/providers/{pid}", json={"clear_api_key": True})
    assert r6.status_code == 200
    raw2 = prov_mod.provider_store.get(pid)
    assert raw2["api_key"] is None

    # test connection endpoint
    r7 = client.post("/model/providers/test", json={
        "provider_type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "models": ["gpt-4o"],
    })
    assert r7.status_code == 200
    assert "ok" in r7.json()

    # delete
    r8 = client.delete(f"/model/providers/{pid}")
    assert r8.status_code == 200
    assert prov_mod.provider_store.get(pid) is None


def test_legacy_model_resolution(monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"model": "qwen2.5-coder:7b"})
    monkeypatch.setattr(llm_mod, "workspace_service", ws_mod.workspace_service)

    client = LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "get_models_config", lambda: {"default": "ollama::qwen2.5-coder:7b", "models": []})
    # no global; workspace model legacy (no ::) -> resolve returns it
    client.active_model_id = None
    assert client.resolve_model("ws") == "qwen2.5-coder:7b"
