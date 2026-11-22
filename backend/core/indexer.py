import json
import os
import threading
from collections.abc import Callable

from core.embeddings import embedding_service
from core.logging_config import logger
from db.chroma_manager import chroma_manager
from services.file_scanner import FileScanner
from services.workspace_service import workspace_service


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


class Indexer:
    def __init__(self):
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._progress: dict[str, dict] = {}

    def _default_progress(self, workspace_id: str) -> dict:
        return {
            "workspace_id": workspace_id,
            "status": "idle",
            "phase": "idle",
            "total_files": 0,
            "processed_files": 0,
            "indexed_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "removed_files": 0,
            "current_file": None,
            "percent": 0.0,
            "error": None,
        }

    def _get_metadata_path(self, workspace_id: str) -> str:
        ws_dir = workspace_service._get_workspace_dir(workspace_id)
        return os.path.join(ws_dir, "index_metadata.json")

    def _load_metadata(self, workspace_id: str) -> dict[str, float]:
        path = self._get_metadata_path(workspace_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_metadata(self, workspace_id: str, metadata: dict[str, float]):
        path = self._get_metadata_path(workspace_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)

    def get_progress(self, workspace_id: str) -> dict:
        with self._lock:
            if workspace_id not in self._progress:
                self._progress[workspace_id] = self._default_progress(workspace_id)
            return dict(self._progress[workspace_id])

    def _set_progress(self, workspace_id: str, **updates):
        with self._condition:
            if workspace_id not in self._progress:
                self._progress[workspace_id] = self._default_progress(workspace_id)
            self._progress[workspace_id].update(updates)
            p = self._progress[workspace_id]
            total = p.get("total_files", 0)
            processed = p.get("processed_files", 0)
            if total > 0:
                p["percent"] = round((processed / total) * 100.0, 2)
            else:
                p["percent"] = 0.0
            self._condition.notify_all()

    def start_indexing_job(self, workspace_id: str) -> dict:
        workspace_service.get_workspace(workspace_id)
        with self._condition:
            if workspace_id not in self._progress:
                self._progress[workspace_id] = self._default_progress(workspace_id)
            if self._progress[workspace_id].get("status") == "running":
                return dict(self._progress[workspace_id])
            self._progress[workspace_id] = self._default_progress(workspace_id)
            self._progress[workspace_id]["status"] = "running"
            self._progress[workspace_id]["phase"] = "scanning"
            self._condition.notify_all()

        def worker():
            try:
                self.index_workspace(workspace_id, progress_callback=self._progress_callback(workspace_id))
            except Exception as e:  # noqa: BLE001
                with self._condition:
                    if workspace_id in self._progress:
                        self._progress[workspace_id]["status"] = "error"
                        self._progress[workspace_id]["phase"] = "error"
                        self._progress[workspace_id]["error"] = str(e)
                    self._condition.notify_all()

        import threading as _t

        thread = _t.Thread(target=worker, daemon=True)
        thread.start()
        return self.get_progress(workspace_id)

    def _progress_callback(self, workspace_id: str):
        def cb(**updates):
            self._set_progress(workspace_id, **updates)

        return cb

    def iter_progress(self, workspace_id: str):
        while True:
            snap = self.get_progress(workspace_id)
            yield snap
            status = snap.get("status")
            if status in ("completed", "error"):
                break
            if status == "idle":
                break
            with self._condition:
                self._condition.wait(timeout=0.5)

    def index_workspace(self, workspace_id: str, progress_callback: Callable | None = None):
        with self._lock:
            return self._index_workspace(workspace_id, progress_callback=progress_callback)

    def _index_workspace(self, workspace_id: str, progress_callback: Callable | None = None):
        if progress_callback is None:
            progress_callback = lambda **kw: None

        workspace = workspace_service.get_workspace(workspace_id)
        folders = workspace.get("folders", [])
        files = workspace.get("files", [])

        collection = chroma_manager.get_collection(workspace_id)
        metadata_cache = self._load_metadata(workspace_id)
        new_metadata_cache: dict[str, float] = {}

        progress_callback(status="running", phase="scanning", total_files=0, processed_files=0,
                         indexed_files=0, skipped_files=0, failed_files=0, removed_files=0,
                         current_file=None, error=None)

        all_file_paths = set()

        for folder in folders:
            if not os.path.exists(folder):
                continue
            all_file_paths.update(FileScanner.scan_directory(folder))

        for file in files:
            if os.path.exists(file):
                all_file_paths.add(file)

        total = len(all_file_paths)
        progress_callback(phase="cleaning", total_files=total)

        # Clean up orphaned chunks for files no longer in the workspace.
        removed_paths = set(metadata_cache.keys()) - all_file_paths
        removed_count = 0
        for removed_path in removed_paths:
            try:
                collection.delete(where={"source": removed_path})
                logger.info("Removed orphaned chunks for %s", removed_path)
                removed_count += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to remove orphaned chunks for %s: %s", removed_path, e)

        progress_callback(phase="indexing", removed_files=removed_count)

        processed = 0
        indexed = 0
        skipped = 0
        failed = 0

        for file_path in all_file_paths:
            progress_callback(current_file=file_path, processed_files=processed)
            try:
                mtime = os.path.getmtime(file_path)
            except OSError as e:
                logger.warning("Could not stat %s: %s", file_path, e)
                failed += 1
                processed += 1
                progress_callback(processed_files=processed, failed_files=failed)
                continue

            # Incremental check
            if file_path in metadata_cache and metadata_cache[file_path] == mtime:
                new_metadata_cache[file_path] = mtime
                skipped += 1
                processed += 1
                progress_callback(processed_files=processed, skipped_files=skipped)
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError) as e:
                logger.warning("Skipping unreadable file %s: %s", file_path, e)
                failed += 1
                processed += 1
                progress_callback(processed_files=processed, failed_files=failed)
                continue

            chunks = chunk_text(content)
            if not chunks:
                new_metadata_cache[file_path] = mtime
                skipped += 1
                processed += 1
                progress_callback(processed_files=processed, skipped_files=skipped)
                continue

            ids = [f"{file_path}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": file_path, "chunk": i} for i in range(len(chunks))]

            try:
                embeddings = embedding_service.embed_texts(chunks)
            except Exception as e:  # noqa: BLE001
                logger.warning("Embedding failed for %s: %s", file_path, e)
                failed += 1
                processed += 1
                progress_callback(processed_files=processed, failed_files=failed)
                continue

            try:
                collection.delete(where={"source": file_path})
                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=chunks,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to store chunks for %s: %s", file_path, e)
                failed += 1
                processed += 1
                progress_callback(processed_files=processed, failed_files=failed)
                continue

            new_metadata_cache[file_path] = mtime
            indexed += 1
            processed += 1
            progress_callback(processed_files=processed, indexed_files=indexed)

        self._save_metadata(workspace_id, new_metadata_cache)

        progress_callback(status="completed", phase="completed", current_file=None,
                         processed_files=total, total_files=total,
                         indexed_files=indexed, skipped_files=skipped, failed_files=failed,
                         removed_files=removed_count, percent=100.0)
        return {"status": "success", "indexed_files": len(new_metadata_cache)}


indexer = Indexer()
