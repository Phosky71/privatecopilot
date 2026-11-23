from pathlib import Path

import db.chroma_manager as cm_mod
import pytest
from core import embeddings as emb_mod
from core import indexer as indexer_mod
from core import llm as llm_mod
from core import rag as rag_mod
from core.llm import LLMClient
from core.rag import RAGService


class FixedEmbeddings:
    def embed_text(self, text):
        return [0.1, 0.2, 0.3]

    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture
def isolated_chroma(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cm_mod, "WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setattr(emb_mod, "embedding_service", FixedEmbeddings())
    monkeypatch.setattr(indexer_mod, "embedding_service", FixedEmbeddings())
    monkeypatch.setattr(rag_mod, "embedding_service", FixedEmbeddings())
    cm_mod.chroma_manager.clients.clear()
    (tmp_path / "workspaces").mkdir()
    return tmp_path / "workspaces"


def test_rag_empty_collection(isolated_chroma: Path):
    ws = "ws1"
    (isolated_chroma / ws).mkdir()
    coll = cm_mod.chroma_manager.get_collection(ws)
    assert coll.count() == 0
    rag = RAGService()
    assert rag.search(ws, "query", top_k=5) == []


def test_rag_count_less_than_topk(isolated_chroma: Path):
    ws = "ws2"
    ws_dir = isolated_chroma / ws
    ws_dir.mkdir()
    src = isolated_chroma / "src"
    src.mkdir()
    f = src / "a.py"
    f.write_text("hello world", encoding="utf-8")

    import services.workspace_service as ws_mod

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(isolated_chroma))
    monkeypatch.setattr(ws_mod.workspace_service, "_get_workspace_dir", lambda _ws: str(ws_dir))
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [str(src)], "files": []})
    monkeypatch.setattr(indexer_mod, "workspace_service", ws_mod.workspace_service)

    idx = indexer_mod.Indexer()
    idx.index_workspace(ws)

    coll = cm_mod.chroma_manager.get_collection(ws)
    assert coll.count() == 1

    rag = RAGService()
    results = rag.search(ws, "hello", top_k=5)
    assert len(results) == 1


def test_indexer_rag_reindex_removes_obsolete(isolated_chroma: Path, monkeypatch: pytest.MonkeyPatch):
    ws = "ws3"
    ws_dir = isolated_chroma / ws
    ws_dir.mkdir()
    src = isolated_chroma / "src3"
    src.mkdir()
    f1 = src / "a.py"
    f1.write_text("hello world", encoding="utf-8")
    f2 = src / "b.py"
    f2.write_text("another file", encoding="utf-8")

    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(isolated_chroma))
    monkeypatch.setattr(ws_mod.workspace_service, "_get_workspace_dir", lambda _ws: str(ws_dir))
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [str(src)], "files": []})
    monkeypatch.setattr(indexer_mod, "workspace_service", ws_mod.workspace_service)

    idx = indexer_mod.Indexer()
    idx.index_workspace(ws)
    coll = cm_mod.chroma_manager.get_collection(ws)
    assert coll.count() >= 2

    # Remove one file and reindex
    f2.unlink()
    idx.index_workspace(ws)

    # Ensure no chunks with source f2 remain
    remaining = coll.get(where={"source": str(f2)})
    assert not remaining.get("ids")


def test_llm_ollama_base_url_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:11434")
    client = llm_mod.LLMClient()
    assert client.base_url == "http://example:11434"


def test_rag_get_collection_count(isolated_chroma: Path):
    ws = "ws-count"
    (isolated_chroma / ws).mkdir()
    coll = cm_mod.chroma_manager.get_collection(ws)
    assert rag_mod.rag_service.get_collection_count(ws) == 0
    coll.add(ids=["1"], embeddings=[[0.1, 0.2, 0.3]], documents=["x"], metadatas=[{"source": "a"}])
    assert rag_mod.rag_service.get_collection_count(ws) == 1


def test_build_messages_unindexed_warning(monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [], "files": []})
    monkeypatch.setattr(llm_mod, "workspace_service", ws_mod.workspace_service)
    monkeypatch.setattr("core.rag.rag_service.search", lambda _ws, q, top_k=5: [])
    monkeypatch.setattr("core.rag.rag_service.get_collection_count", lambda _ws: 0)

    client = LLMClient(base_url="http://localhost:11434")
    msgs = client.build_messages("ws", "colors?")
    user = msgs[-1]["content"]
    assert "[WORKSPACE NOT INDEXED" in user
    assert "strictly forbidden to invent" in msgs[0]["content"]


def test_build_messages_no_relevant_chunks(monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [], "files": []})
    monkeypatch.setattr(llm_mod, "workspace_service", ws_mod.workspace_service)
    monkeypatch.setattr("core.rag.rag_service.search", lambda _ws, q, top_k=5: [])
    monkeypatch.setattr("core.rag.rag_service.get_collection_count", lambda _ws: 5)

    client = LLMClient(base_url="http://localhost:11434")
    msgs = client.build_messages("ws", "colors?")
    user = msgs[-1]["content"]
    assert "[No relevant chunks found" in user


def test_llm_model_resolution_order(monkeypatch: pytest.MonkeyPatch):
    import services.workspace_service as ws_mod

    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {"model": "ws-model"})
    monkeypatch.setattr(llm_mod, "workspace_service", ws_mod.workspace_service)
    client = llm_mod.LLMClient(base_url="http://localhost:11434")
    client.active_model_id = "global-model"

    # workspace model wins
    assert client.resolve_model("ws") == "ws-model"

    # global wins when no workspace model
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {})
    monkeypatch.setattr(llm_mod, "workspace_service", ws_mod.workspace_service)
    assert client.resolve_model("ws") == "global-model"

    # default from Ollama
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {})
    monkeypatch.setattr(llm_mod, "workspace_service", ws_mod.workspace_service)
    client.active_model_id = None
    monkeypatch.setattr(client, "get_models_config", lambda: {"default": "default-model", "models": []})
    assert client.resolve_model("ws") == "default-model"


def test_llm_generate_stream_error(monkeypatch: pytest.MonkeyPatch):
    import requests

    class FakeResponse:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())

    client = llm_mod.LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "build_messages", lambda _ws, _q, history=None: [{"role": "user", "content": "prompt"}])
    monkeypatch.setattr(client, "resolve_model", lambda _ws: "m")

    events = list(client.generate_stream("ws", "q"))
    assert any("error" in e for e in events)
    assert any("done" in e and "true" in e for e in events)


def test_llm_generate_stream_connection_error(monkeypatch: pytest.MonkeyPatch):
    import requests

    def raise_conn(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "post", raise_conn)

    client = llm_mod.LLMClient(base_url="http://localhost:11434")
    monkeypatch.setattr(client, "build_messages", lambda _ws, _q, history=None: [{"role": "user", "content": "prompt"}])
    monkeypatch.setattr(client, "resolve_model", lambda _ws: "m")

    events = list(client.generate_stream("ws", "q"))
    assert any("error" in e for e in events)
    assert all("done" in e for e in events if "error" in e)
