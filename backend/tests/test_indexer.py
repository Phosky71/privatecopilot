from pathlib import Path

import pytest
from core import indexer as indexer_module
from core.indexer import Indexer


class FakeCollection:
    def __init__(self):
        self.deleted = []
        self.added = []
        self.count_value = 0

    def count(self):
        return self.count_value

    def delete(self, where=None):
        self.deleted.append(where)

    def add(self, ids, embeddings, metadatas, documents):
        self.added.append((ids, embeddings, metadatas, documents))

    def query(self, query_embeddings, n_results):
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}


@pytest.fixture
def fake_collection(monkeypatch: pytest.MonkeyPatch):
    coll = FakeCollection()

    class FakeManager:
        def get_collection(self, workspace_id, collection_name="codebase"):
            return coll

    monkeypatch.setattr(indexer_module, "chroma_manager", FakeManager())
    return coll


@pytest.fixture
def fake_embeddings(monkeypatch: pytest.MonkeyPatch):
    class FakeEmb:
        def embed_texts(self, texts):
            return [[0.1] * 3 for _ in texts]

        def embed_text(self, text):
            return [0.1] * 3

    monkeypatch.setattr(indexer_module, "embedding_service", FakeEmb())


@pytest.fixture
def fake_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    import core.indexer as indexer_mod

    def get_workspace(workspace_id):
        return {"id": workspace_id, "folders": [str(tmp_path / "src")], "files": []}

    monkeypatch.setattr(indexer_mod.workspace_service, "get_workspace", get_workspace)
    monkeypatch.setattr(indexer_mod.workspace_service, "_get_workspace_dir", lambda _ws: str(ws_dir))
    (tmp_path / "src").mkdir()
    return ws_dir


def test_incremental_by_mtime(tmp_path: Path, fake_collection, fake_embeddings, fake_workspace):
    src = tmp_path / "src"
    f = src / "a.py"
    f.write_text("print('hi')", encoding="utf-8")

    indexer = Indexer()
    r1 = indexer.index_workspace("ws")
    assert r1["indexed_files"] == 1
    assert len(fake_collection.added) == 1

    # Second run: mtime unchanged -> no new add
    fake_collection.added.clear()
    r2 = indexer.index_workspace("ws")
    assert r2["indexed_files"] == 1
    assert len(fake_collection.added) == 0


def test_unreadable_file_skipped(tmp_path: Path, fake_collection, fake_embeddings, fake_workspace):
    src = tmp_path / "src"
    bad = src / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00")  # invalid utf-8
    good = src / "good.txt"
    good.write_text("hello", encoding="utf-8")

    indexer = Indexer()
    r = indexer.index_workspace("ws")
    # good indexed, bad skipped
    assert r["indexed_files"] == 1
    # bad not in metadata cache
    meta_path = fake_workspace / "index_metadata.json"
    import json

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert str(good) in meta
    assert str(bad) not in meta


def test_orphan_chunks_removed(tmp_path: Path, fake_collection, fake_embeddings, fake_workspace):
    src = tmp_path / "src"
    f = src / "a.py"
    f.write_text("print('hi')", encoding="utf-8")

    # Pre-populate metadata cache with an extra removed file.
    import json

    ws_dir = fake_workspace
    meta_path = ws_dir / "index_metadata.json"
    meta_path.write_text(json.dumps({str(src / "removed.py"): 123.0}), encoding="utf-8")

    indexer = Indexer()
    indexer.index_workspace("ws")
    # collection.delete should have been called for removed.py
    assert any(d == {"source": str(src / "removed.py")} for d in fake_collection.deleted)


def test_failed_add_not_saved(tmp_path: Path, fake_collection, fake_embeddings, fake_workspace, monkeypatch):
    src = tmp_path / "src"
    f = src / "a.py"
    f.write_text("print('hi')", encoding="utf-8")

    # Make collection.add raise
    def boom(*a, **k):
        raise RuntimeError("boom")

    fake_collection.add = boom

    indexer = Indexer()
    r = indexer.index_workspace("ws")
    assert r["indexed_files"] == 0
    meta_path = fake_workspace / "index_metadata.json"
    if meta_path.exists():
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert str(f) not in meta
