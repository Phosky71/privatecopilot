import json
import os
from typing import Any

import requests
from core.logging_config import logger
from core.rag import rag_service
from services.workspace_service import workspace_service


class LLMClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            from services.workspace_service import workspace_service

            self.active_model_id = workspace_service.get_active_model_id()
        except Exception:  # noqa: BLE001
            self.active_model_id = None

    def get_models_config(self) -> dict[str, Any]:
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if res.status_code == 200:
                data = res.json()
                models = []
                for m in data.get("models", []):
                    model_name = m.get("name")
                    models.append({
                        "id": model_name,
                        "name": model_name,
                        "model": model_name
                    })
                
                default_model = models[0]["id"] if models else None
                return {
                    "default": default_model,
                    "models": models
                }
        except requests.RequestException as e:
            logger.warning("Error fetching Ollama models: %s", e)
            
        return {
            "default": None,
            "models": []
        }

    def set_active_model(self, model_id: str) -> str:
        self.active_model_id = model_id
        return model_id

    def resolve_model_details(self, workspace_id: str | None = None) -> tuple[str, str]:
        # 1. Workspace model
        if workspace_id:
            try:
                ws = workspace_service.get_workspace(workspace_id)
                ws_model = ws.get("model")
                if ws_model:
                    return ws_model, "workspace"
            except (ValueError, OSError, KeyError) as e:
                logger.debug("Could not resolve workspace model: %s", e)
                
        # 2. Global selected model
        if self.active_model_id:
            return self.active_model_id, "global"
            
        # 3. Default model
        config = self.get_models_config()
        if config.get("default"):
            return config["default"], "default"
            
        return "", "none"

    def resolve_model(self, workspace_id: str | None = None) -> str:
        model, _ = self.resolve_model_details(workspace_id)
        return model

    def build_messages(self, workspace_id: str, query: str, history: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
        # Improve RAG query for short follow-ups using last user question.
        search_query = query
        if history:
            last_user = None
            for msg in reversed(history):
                if msg.get("role") == "user":
                    last_user = msg.get("content", "")
                    break
            if last_user and len(query.strip()) < 80:
                search_query = f"{last_user}\n{query}"

        results = rag_service.search(workspace_id, search_query, top_k=5)

        context_parts = []
        for r in results:
            source = r['metadata'].get('source', 'Unknown')
            content = r['document']
            context_parts.append(f"--- File: {source} ---\n{content}")

        context_str = "\n\n".join(context_parts)

        system_prompt = (
            "You are a local AI coding assistant. You have access to the user's workspace files. "
            "Use the provided context to answer the user's questions about their codebase. "
            "IMPORTANT: If you want to propose a file modification, you MUST use the following exact XML format:\n"
            "<edit file=\"path/to/file.ext\">\n"
            "<original>\n"
            "exact old code to replace\n"
            "</original>\n"
            "<replacement>\n"
            "new code\n"
            "</replacement>\n"
            "</edit>\n"
            "Do not use markdown code blocks for file edits. Only use the <edit> tags."
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        # Bounded history window.
        if history:
            trimmed: list[dict[str, str]] = []
            total_chars = 0
            for msg in reversed(history):
                role = msg.get("role")
                content = msg.get("content", "")
                if role not in ("user", "assistant"):
                    continue
                if total_chars + len(content) > 12000:
                    break
                trimmed.insert(0, {"role": role, "content": content})
                total_chars += len(content)
                if len(trimmed) >= 12:
                    break

            messages.extend(trimmed)

        user_content = query
        if context_str:
            user_content = f"Context:\n{context_str}\n\nUser Question:\n{query}"

        messages.append({"role": "user", "content": user_content})
        return messages

    def _log_request(self, workspace_id: str, model_name: str):
        logger.info("LLM request: workspace=%s selected_model=%s", workspace_id, model_name)

    def generate(self, workspace_id: str, query: str, history: list[dict[str, str]] | None = None) -> str:
        model = self.resolve_model(workspace_id)
        self._log_request(workspace_id, model)

        messages = self.build_messages(workspace_id, query, history)

        response = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
            timeout=(5, 120),
        )

        if response.status_code == 200:
            data = response.json()
            if "message" in data:
                return data["message"].get("content", "")
            return data.get("response", "")
        else:
            raise RuntimeError(f"Ollama API Error: {response.text}")

    def generate_stream(self, workspace_id: str, query: str, history: list[dict[str, str]] | None = None):
        model = self.resolve_model(workspace_id)
        self._log_request(workspace_id, model)

        messages = self.build_messages(workspace_id, query, history)

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
                stream=True,
                timeout=(5, 120),
            )
        except requests.RequestException as e:
            logger.error("Ollama stream connection failed: %s", e)
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
            return

        if response.status_code != 200:
            yield f"data: {json.dumps({'error': f'Ollama API Error: {response.text}', 'done': True})}\n\n"
            return

        try:
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    content = ""
                    if isinstance(data.get("message"), dict):
                        content = data["message"].get("content", "")
                    if not content:
                        content = data.get("response", "")
                    done_flag = bool(data.get("done", False))
                    yield f"data: {json.dumps({'response': content, 'done': done_flag})}\n\n"
        except (requests.RequestException, ValueError) as e:
            logger.error("Ollama stream failed: %s", e)
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

llm_client = LLMClient()
