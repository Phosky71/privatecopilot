import os
import threading

import chromadb

WORKSPACES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workspaces")


class ChromaManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.clients = {}

    def _get_db_path(self, workspace_id: str) -> str:
        return os.path.join(WORKSPACES_DIR, workspace_id, "chroma_db")

    def get_client(self, workspace_id: str):
        with self._lock:
            if workspace_id not in self.clients:
                db_path = self._get_db_path(workspace_id)
                os.makedirs(db_path, exist_ok=True)
                client = chromadb.PersistentClient(path=db_path)
                self.clients[workspace_id] = client
            return self.clients[workspace_id]

    def get_collection(self, workspace_id: str, collection_name: str = "codebase"):
        with self._lock:
            client = self.get_client(workspace_id)
            return client.get_or_create_collection(name=collection_name)

    def remove_client(self, workspace_id: str):
        with self._lock:
            self.clients.pop(workspace_id, None)


chroma_manager = ChromaManager()
