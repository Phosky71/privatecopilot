import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

WORKSPACES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workspaces")


class WorkspaceService:
    def __init__(self):
        self._lock = threading.RLock()
        if not os.path.exists(WORKSPACES_DIR):
            os.makedirs(WORKSPACES_DIR)

    def _get_workspace_dir(self, workspace_id: str) -> str:
        return os.path.join(WORKSPACES_DIR, workspace_id)

    def _get_config_path(self, workspace_id: str) -> str:
        return os.path.join(self._get_workspace_dir(workspace_id), "config.json")

    def _get_state_path(self) -> str:
        return os.path.join(WORKSPACES_DIR, ".app_state.json")

    def _get_chat_history_path(self, workspace_id: str) -> str:
        return os.path.join(self._get_workspace_dir(workspace_id), "chat_history.json")

    def _load_state(self) -> dict[str, Any]:
        path = self._get_state_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _save_state(self, state: dict[str, Any]):
        os.makedirs(WORKSPACES_DIR, exist_ok=True)
        with open(self._get_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def get_app_state(self) -> dict[str, Any]:
        with self._lock:
            return self._load_state()

    def set_app_state(self, updates: dict[str, Any]):
        with self._lock:
            state = self._load_state()
            state.update(updates)
            self._save_state(state)

    def get_active_workspace_id(self) -> str:
        return self.get_app_state().get("active_workspace_id")

    def set_active_workspace_id(self, value):
        self.set_app_state({"active_workspace_id": value})

    def get_active_model_id(self):
        return self.get_app_state().get("active_model_id")

    def set_active_model_id(self, value):
        self.set_app_state({"active_model_id": value})

    def open_workspace_by_path(self, folder_path: str, name: str | None = None) -> dict[str, Any]:
        with self._lock:
            resolved = Path(folder_path).resolve()
            if not resolved.is_dir():
                raise ValueError(f"Folder path does not exist or is not a directory: {folder_path}")

            resolved_str = str(resolved)

            for ws in self.get_workspaces():
                folders = ws.get("folders", [])
                if folders:
                    try:
                        if Path(folders[0]).resolve() == resolved:
                            return ws
                    except (OSError, ValueError):
                        continue

            if name and name.strip():
                ws_name = name.strip()
            else:
                ws_name = resolved.name or str(resolved)

            workspace_id = str(uuid.uuid4())
            ws_dir = self._get_workspace_dir(workspace_id)
            os.makedirs(ws_dir, exist_ok=True)

            config = {
                "id": workspace_id,
                "name": ws_name,
                "folders": [resolved_str],
                "files": [],
            }

            with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

            return config

    def get_git_init_policy(self) -> str:
        policy = self.get_app_state().get("git_init_policy", "ask")
        if policy not in {"ask", "auto", "never"}:
            return "ask"
        return policy

    def set_git_init_policy(self, policy: str) -> str:
        if policy not in {"ask", "auto", "never"}:
            raise ValueError("Invalid git_init_policy")
        self.set_app_state({"git_init_policy": policy})
        return policy

    def get_chat_history(self, workspace_id: str) -> list[dict[str, str]]:
        with self._lock:
            self.get_workspace(workspace_id)  # validate existence
            path = self._get_chat_history_path(workspace_id)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                except (OSError, json.JSONDecodeError):
                    return []
            return []

    def append_chat_turn(self, workspace_id: str, user_message: str, assistant_message: str):
        with self._lock:
            self.get_workspace(workspace_id)
            history = self.get_chat_history(workspace_id)
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": assistant_message})
            path = self._get_chat_history_path(workspace_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)

    def clear_chat_history(self, workspace_id: str):
        with self._lock:
            self.get_workspace(workspace_id)
            path = self._get_chat_history_path(workspace_id)
            if os.path.exists(path):
                os.remove(path)

    def create_workspace(self, name: str) -> dict[str, Any]:
        with self._lock:
            workspace_id = str(uuid.uuid4())
            ws_dir = self._get_workspace_dir(workspace_id)
            os.makedirs(ws_dir, exist_ok=True)

            config = {
                "id": workspace_id,
                "name": name,
                "folders": [],
                "files": [],
            }

            with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)

            return config

    def get_workspaces(self) -> list[dict[str, Any]]:
        with self._lock:
            workspaces = []
            if not os.path.exists(WORKSPACES_DIR):
                return workspaces

            for ws_id in os.listdir(WORKSPACES_DIR):
                config_path = self._get_config_path(ws_id)
                if os.path.exists(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        workspaces.append(json.load(f))
            return workspaces

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            config_path = self._get_config_path(workspace_id)
            if not os.path.exists(config_path):
                raise ValueError(f"Workspace {workspace_id} not found")

            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                if "files" not in config:
                    config["files"] = []
                return config

    def add_folder(self, workspace_id: str, folder_path: str) -> dict[str, Any]:
        with self._lock:
            if not os.path.exists(folder_path):
                raise ValueError(f"Folder path does not exist: {folder_path}")

            config = self.get_workspace(workspace_id)

            if folder_path not in config["folders"]:
                config["folders"].append(folder_path)
                with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)

            return config

    def remove_folder(self, workspace_id: str, folder_path: str) -> dict[str, Any]:
        with self._lock:
            config = self.get_workspace(workspace_id)

            if folder_path in config["folders"]:
                config["folders"].remove(folder_path)
                with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)

            return config

    def update_model(self, workspace_id: str, model: str) -> dict[str, Any]:
        with self._lock:
            config = self.get_workspace(workspace_id)
            config["model"] = model
            with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            return config

    def update_workspace_name(self, workspace_id: str, name: str) -> dict[str, Any]:
        with self._lock:
            config = self.get_workspace(workspace_id)
            config["name"] = name
            with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            return config

    def delete_workspace(self, workspace_id: str):
        with self._lock:
            ws_dir = self._get_workspace_dir(workspace_id)
            if os.path.exists(ws_dir):
                shutil.rmtree(ws_dir)
            from db.chroma_manager import chroma_manager
            if workspace_id in chroma_manager.clients:
                del chroma_manager.clients[workspace_id]

    def add_file(self, workspace_id: str, file_path: str) -> dict[str, Any]:
        with self._lock:
            if not os.path.exists(file_path):
                raise ValueError(f"File path does not exist: {file_path}")

            config = self.get_workspace(workspace_id)

            if file_path not in config.get("files", []):
                config.setdefault("files", []).append(file_path)
                with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)

            return config

    def remove_file(self, workspace_id: str, file_path: str) -> dict[str, Any]:
        with self._lock:
            config = self.get_workspace(workspace_id)

            if file_path in config.get("files", []):
                config["files"].remove(file_path)
                with open(self._get_config_path(workspace_id), "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=4)

            return config


workspace_service = WorkspaceService()
