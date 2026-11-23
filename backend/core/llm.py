import json
import os

import requests
from core.logging_config import logger
from core.providers import (
    discover_models,
    normalize_anthropic_base,
    normalize_openai_base,
    provider_store,
)
from core.providers import get_models_config as _get_models_config
from core.rag import rag_service
from services.workspace_service import workspace_service


class LLMClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            self.active_model_id = workspace_service.get_active_model_id()
        except Exception:  # noqa: BLE001
            self.active_model_id = None

    def get_models_config(self) -> dict:
        return _get_models_config()

    def set_active_model(self, model_id: str) -> str:
        self.active_model_id = model_id
        return model_id

    def _resolve_provider(self, composite_id: str):
        # composite id: provider_id::raw_model_id
        if "::" in composite_id:
            pid, raw = composite_id.split("::", 1)
        else:
            # legacy fallback: treat as ollama raw id
            pid, raw = "ollama", composite_id

        # configured provider?
        prov = provider_store.get(pid)
        if prov:
            return prov, raw

        # local presets
        if pid == "ollama":
            return {"id": "ollama", "provider_type": "ollama", "base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"), "api_key": None, "name": "Ollama"}, raw
        if pid == "lmstudio":
            return {"id": "lmstudio", "provider_type": "openai_compatible", "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"), "api_key": None, "name": "LM Studio"}, raw
        if pid.startswith("llamacpp"):
            # find url from env or port
            port = pid.split("-")[-1]
            url = os.getenv("LLAMACPP_BASE_URL", f"http://127.0.0.1:{port}")
            return {"id": pid, "provider_type": "openai_compatible", "base_url": url, "api_key": None, "name": "llama.cpp"}, raw

        # fallback: search discovered models
        models, _status, _default = discover_models()
        for m in models:
            if m.get("id") == composite_id:
                # build minimal provider from status
                for s in _status:
                    if s.get("id") == pid:
                        return {"id": pid, "provider_type": m.get("provider_type", "openai_compatible"), "base_url": s.get("base_url", ""), "api_key": None, "name": s.get("name", pid)}, raw
        return None, raw

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
            "You MUST answer ONLY using the provided workspace context fragments. "
            "It is strictly forbidden to invent file paths, symbols, hex colors, or code that are not present in the context. "
            "If the context states the workspace is not indexed or has no relevant matches, say so clearly and tell the user to run \"Index Workspace\". "
            "Only emit <edit> tags when the user asks to modify or create a real workspace file; never emit fictitious examples like path/to/file.ext. "
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
        else:
            chunk_count = rag_service.get_collection_count(workspace_id)
            if chunk_count == 0:
                user_content = (
                    "Context: [WORKSPACE NOT INDEXED — 0 indexed chunks in vector database. "
                    "Do NOT invent files, colors, or code. Tell the user clearly to run \"Index Workspace\" first.]\n\n"
                    f"User Question:\n{query}"
                )
            else:
                user_content = (
                    "Context: [No relevant chunks found in indexed workspace files for this query. "
                    "Do NOT invent non-existent files.]\n\n"
                    f"User Question:\n{query}"
                )

        messages.append({"role": "user", "content": user_content})
        return messages

    def _log_request(self, workspace_id: str, model_name: str):
        logger.info("LLM request: workspace=%s selected_model=%s", workspace_id, model_name)

    def generate(self, workspace_id: str, query: str, history: list[dict[str, str]] | None = None) -> str:
        model_id = self.resolve_model(workspace_id)
        self._log_request(workspace_id, model_id)
        prov, raw_model = self._resolve_provider(model_id)
        messages = self.build_messages(workspace_id, query, history)

        ptype = prov.get("provider_type") if prov else "ollama"
        base_url = (prov.get("base_url") if prov else self.base_url) or self.base_url
        api_key = prov.get("api_key") if prov else None

        if ptype == "ollama":
            url = base_url.rstrip("/") + "/api/chat"
            response = requests.post(url, json={"model": raw_model, "messages": messages, "stream": False}, timeout=(5, 120))
            if response.status_code == 200:
                data = response.json()
                if "message" in data:
                    return data["message"].get("content", "")
                return data.get("response", "")
            raise RuntimeError(f"Ollama API Error: {response.text}")

        if ptype == "anthropic":
            url = normalize_anthropic_base(base_url) + "/messages"
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            chat_msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
            headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {"model": raw_model, "max_tokens": 4096, "system": system_msg, "messages": chat_msgs, "stream": False}
            response = requests.post(url, json=payload, headers=headers, timeout=(5, 120))
            if response.status_code == 200:
                data = response.json()
                content = data.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "")
                return ""
            raise RuntimeError(f"Anthropic API Error: {response.text}")

        # openai compatible
        url = normalize_openai_base(base_url) + "/chat/completions"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": raw_model, "messages": messages, "stream": False}
        response = requests.post(url, json=payload, headers=headers, timeout=(5, 120))
        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
        raise RuntimeError(f"OpenAI-compatible API Error: {response.text}")

    def generate_stream(self, workspace_id: str, query: str, history: list[dict[str, str]] | None = None):
        model_id = self.resolve_model(workspace_id)
        self._log_request(workspace_id, model_id)
        prov, raw_model = self._resolve_provider(model_id)
        messages = self.build_messages(workspace_id, query, history)

        ptype = prov.get("provider_type") if prov else "ollama"
        base_url = (prov.get("base_url") if prov else self.base_url) or self.base_url
        api_key = prov.get("api_key") if prov else None

        if ptype == "ollama":
            url = base_url.rstrip("/") + "/api/chat"
            try:
                response = requests.post(url, json={"model": raw_model, "messages": messages, "stream": True}, stream=True, timeout=(5, 120))
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
            return

        if ptype == "anthropic":
            url = normalize_anthropic_base(base_url) + "/messages"
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            chat_msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
            headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {"model": raw_model, "max_tokens": 4096, "system": system_msg, "messages": chat_msgs, "stream": True}
            try:
                response = requests.post(url, json=payload, headers=headers, stream=True, timeout=(5, 120))
            except requests.RequestException as e:
                logger.error("Anthropic stream connection failed: %s", e)
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
                return
            if response.status_code != 200:
                yield f"data: {json.dumps({'error': f'Anthropic API Error: {response.text}', 'done': True})}\n\n"
                return
            try:
                for line in response.iter_lines():
                    if not line:
                        continue
                    text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
                    if not text.startswith("data:"):
                        continue
                    payload_str = text[5:].strip()
                    if not payload_str or payload_str == "[DONE]":
                        continue
                    data = json.loads(payload_str)
                    etype = data.get("type")
                    if etype == "content_block_delta":
                        delta = data.get("delta", {})
                        content = delta.get("text", "")
                        if content:
                            yield f"data: {json.dumps({'response': content, 'done': False})}\n\n"
                    elif etype == "message_stop":
                        yield f"data: {json.dumps({'response': '', 'done': True})}\n\n"
            except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
                logger.error("Anthropic stream failed: %s", e)
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
            return

        # openai compatible
        url = normalize_openai_base(base_url) + "/chat/completions"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": raw_model, "messages": messages, "stream": True}
        try:
            response = requests.post(url, json=payload, headers=headers, stream=True, timeout=(5, 120))
        except requests.RequestException as e:
            logger.error("OpenAI-compatible stream connection failed: %s", e)
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
            return
        if response.status_code != 200:
            yield f"data: {json.dumps({'error': f'OpenAI-compatible API Error: {response.text}', 'done': True})}\n\n"
            return
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
                if not text.startswith("data:"):
                    continue
                payload_str = text[5:].strip()
                if not payload_str or payload_str == "[DONE]":
                    if payload_str == "[DONE]":
                        yield f"data: {json.dumps({'response': '', 'done': True})}\n\n"
                    continue
                data = json.loads(payload_str)
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield f"data: {json.dumps({'response': content, 'done': False})}\n\n"
                if data.get("done"):
                    yield f"data: {json.dumps({'response': '', 'done': True})}\n\n"
        except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
            logger.error("OpenAI-compatible stream failed: %s", e)
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"


llm_client = LLMClient()
