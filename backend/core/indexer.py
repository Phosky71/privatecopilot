import json
import os

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
        pass

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

    def index_workspace(self, workspace_id: str):
        workspace = workspace_service.get_workspace(workspace_id)
        folders = workspace.get("folders", [])
        files = workspace.get("files", [])

        collection = chroma_manager.get_collection(workspace_id)
        metadata_cache = self._load_metadata(workspace_id)
        new_metadata_cache: dict[str, float] = {}

        all_file_paths = set()

        for folder in folders:
            if not os.path.exists(folder):
                continue
            all_file_paths.update(FileScanner.scan_directory(folder))

        for file in files:
            if os.path.exists(file):
                all_file_paths.add(file)

        # Clean up orphaned chunks for files no longer in the workspace.
        removed_paths = set(metadata_cache.keys()) - all_file_paths
        for removed_path in removed_paths:
            try:
                collection.delete(where={"source": removed_path})
                logger.info("Removed orphaned chunks for %s", removed_path)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to remove orphaned chunks for %s: %s", removed_path, e)

        for file_path in all_file_paths:
            try:
                mtime = os.path.getmtime(file_path)
            except OSError as e:
                logger.warning("Could not stat %s: %s", file_path, e)
                continue

            # Incremental check
            if file_path in metadata_cache and metadata_cache[file_path] == mtime:
                new_metadata_cache[file_path] = mtime
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError) as e:
                logger.warning("Skipping unreadable file %s: %s", file_path, e)
                continue

            chunks = chunk_text(content)
            if not chunks:
                new_metadata_cache[file_path] = mtime
                continue

            ids = [f"{file_path}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": file_path, "chunk": i} for i in range(len(chunks))]

            try:
                embeddings = embedding_service.embed_texts(chunks)
            except Exception as e:  # noqa: BLE001
                logger.warning("Embedding failed for %s: %s", file_path, e)
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
                continue

            new_metadata_cache[file_path] = mtime

        self._save_metadata(workspace_id, new_metadata_cache)
        return {"status": "success", "indexed_files": len(new_metadata_cache)}


indexer = Indexer()
