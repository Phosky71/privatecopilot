import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import requests
from core.logging_config import logger
from services.workspace_service import WORKSPACES_DIR

PROVIDERS_FILE = os.path.join(WORKSPACES_DIR, ".providers.json")


def _mask_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}...{key[-4:]}"


def normalize_openai_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")].rstrip("/")
    path = urlparse(url).path.rstrip("/")
    last = path.split("/")[-1] if path else ""
    is_version = bool(last) and (last.startswith("v") and any(c.isdigit() for c in last))
    if not is_version and last not in ("openai",):
        url = url + "/v1"
    return url


def normalize_anthropic_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url.endswith("/messages"):
        url = url[: -len("/messages")].rstrip("/")
    path = urlparse(url).path.rstrip("/")
    last = path.split("/")[-1] if path else ""
    is_version = bool(last) and (last.startswith("v") and any(c.isdigit() for c in last))
    if not is_version:
        url = url + "/v1"
    return url


class ProviderStore:
    def __init__(self):
        self._lock = threading.RLock()

    def _load(self) -> list[dict[str, Any]]:
        if os.path.exists(PROVIDERS_FILE):
            try:
                with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except (OSError, json.JSONDecodeError):
                return []
        return []

    def _save(self, providers: list[dict[str, Any]]):
        os.makedirs(WORKSPACES_DIR, exist_ok=True)
        with open(PROVIDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(providers, f, indent=2)

    def list_raw(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self._load()]

    def list_sanitized(self) -> list[dict[str, Any]]:
        out = []
        for p in self.list_raw():
            item = dict(p)
            key = item.pop("api_key", None)
            item["has_api_key"] = bool(key)
            item["api_key_masked"] = _mask_key(key)
            out.append(item)
        return out

    def get(self, provider_id: str) -> dict[str, Any] | None:
        for p in self.list_raw():
            if p.get("id") == provider_id:
                return p
        return None

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            providers = self._load()
            new_id = data.get("id") or f"prov-{os.urandom(4).hex()}"
            item = {
                "id": new_id,
                "name": data.get("name") or new_id,
                "provider_type": data.get("provider_type", "openai_compatible"),
                "base_url": data.get("base_url", ""),
                "api_key": data.get("api_key"),
                "models": data.get("models") or [],
                "enabled": data.get("enabled", True),
            }
            providers.append(item)
            self._save(providers)
            return item

    def update(self, provider_id: str, data: dict[str, Any], clear_api_key: bool = False) -> dict[str, Any] | None:
        with self._lock:
            providers = self._load()
            for p in providers:
                if p.get("id") == provider_id:
                    if data.get("name") is not None:
                        p["name"] = data["name"]
                    if data.get("provider_type") is not None:
                        p["provider_type"] = data["provider_type"]
                    if data.get("base_url") is not None:
                        p["base_url"] = data["base_url"]
                    if data.get("models") is not None:
                        p["models"] = data["models"]
                    if data.get("enabled") is not None:
                        p["enabled"] = data["enabled"]
                    if clear_api_key:
                        p["api_key"] = None
                    elif data.get("api_key"):
                        p["api_key"] = data["api_key"]
                    self._save(providers)
                    return p
            return None

    def delete(self, provider_id: str) -> bool:
        with self._lock:
            providers = self._load()
            new = [p for p in providers if p.get("id") != provider_id]
            if len(new) == len(providers):
                return False
            self._save(new)
            return True

    def test_connection(self, data: dict[str, Any]) -> dict[str, Any]:
        ptype = data.get("provider_type")
        base_url = data.get("base_url", "")
        api_key = data.get("api_key")
        # If testing existing provider without key, load from store
        pid = data.get("id")
        if pid and not api_key:
            existing = self.get(pid)
            if existing:
                api_key = existing.get("api_key")
        try:
            if ptype == "ollama":
                url = base_url.rstrip("/") + "/api/tags"
                headers = {}
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    models = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
                    return {"ok": True, "models_found": models, "error": None}
                return {"ok": False, "models_found": [], "error": f"HTTP {r.status_code}"}
            # openai compatible / anthropic
            if ptype == "anthropic":
                url = normalize_anthropic_base(base_url) + "/messages"
                headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
                # just models? Anthropic has no /models; use provided models
                return {"ok": True, "models_found": data.get("models") or [], "error": None}
            url = normalize_openai_base(base_url) + "/models"
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            r = requests.get(url, timeout=3, headers=headers)
            if r.status_code == 200:
                models = [m.get("id") for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id")]
                if not models:
                    models = data.get("models") or []
                return {"ok": True, "models_found": models, "error": None}
            return {"ok": False, "models_found": [], "error": f"HTTP {r.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "models_found": [], "error": str(e)}


provider_store = ProviderStore()


def _probe_url(url: str, timeout: float = 0.8) -> requests.Response | None:
    try:
        return requests.get(url, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None


def _probe_ollama(base_url: str) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/api/tags"
    r = _probe_url(url, 0.8)
    if r is None or r.status_code != 200:
        return []
    models = []
    for m in r.json().get("models", []):
        raw = m.get("name")
        if raw:
            models.append({"raw": raw, "provider_id": "ollama", "provider_name": "Ollama", "provider_type": "ollama", "is_local": True})
    return models


def _probe_openai(base_url: str, provider_id: str, provider_name: str, provider_type: str, api_key: str | None = None, is_local: bool = True, timeout: float = 0.8) -> list[dict[str, Any]]:
    url = normalize_openai_base(base_url) + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = requests.get(url, timeout=timeout, headers=headers)
    except Exception:  # noqa: BLE001
        return []
    if r.status_code != 200:
        return []
    data = r.json().get("data")
    if not isinstance(data, list):
        return []
    models = []
    for m in data:
        if isinstance(m, dict) and m.get("id"):
            models.append({"raw": m["id"], "provider_id": provider_id, "provider_name": provider_name, "provider_type": provider_type, "is_local": is_local})
    return models


def discover_models() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (models, providers_status)."""
    models: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []

    # Local standard probes in parallel.
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    lmstudio_url = os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")

    llamaproc_urls = []
    if os.getenv("LLAMACPP_BASE_URL"):
        llamaproc_urls.append(os.getenv("LLAMACPP_BASE_URL"))
    else:
        llamaproc_urls = ["http://127.0.0.1:8080", "http://127.0.0.1:9931", "http://127.0.0.1:8033"]

    def probe_ollama():
        res = _probe_ollama(ollama_url)
        status.append({"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": ollama_url, "online": bool(res)})
        return res

    def probe_lmstudio():
        res = _probe_openai(lmstudio_url, "lmstudio", "LM Studio", "openai_compatible", is_local=True, timeout=0.8)
        status.append({"id": "lmstudio", "name": "LM Studio", "type": "openai_compatible", "base_url": lmstudio_url, "online": bool(res)})
        return res

    def probe_llamacpp(url):
        res = _probe_openai(url, f"llamacpp-{url.split(':')[-1].rstrip('/')}", "llama.cpp", "openai_compatible", is_local=True, timeout=0.8)
        # tag as llama.cpp if owned_by llamacpp or /props exists
        online = bool(res)
        status.append({"id": f"llamacpp-{url.split(':')[-1].rstrip('/')}", "name": "llama.cpp", "type": "openai_compatible", "base_url": url, "online": online})
        return res

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(probe_ollama), ex.submit(probe_lmstudio)]
        for u in llamaproc_urls:
            futures.append(ex.submit(probe_llamacpp, u))
        for f in as_completed(futures):
            try:
                models.extend(f.result())
            except Exception as e:  # noqa: BLE001
                logger.debug("Probe failed: %s", e)

    # Configured providers.
    for prov in provider_store.list_raw():
        if not prov.get("enabled", True):
            continue
        ptype = prov.get("provider_type")
        base_url = prov.get("base_url", "")
        api_key = prov.get("api_key")
        pid = prov.get("id")
        pname = prov.get("name", pid)
        is_local = "127.0.0.1" in base_url or "localhost" in base_url
        timeout = 2.0 if not is_local else 0.8
        found = []
        if ptype == "ollama":
            found = _probe_ollama(base_url)
            # override provider info
            for m in found:
                m["provider_id"] = pid
                m["provider_name"] = pname
                m["provider_type"] = "ollama"
                m["is_local"] = is_local
        elif ptype in ("openai_compatible",):
            found = _probe_openai(base_url, pid, pname, "openai_compatible", api_key=api_key, is_local=is_local, timeout=timeout)
        elif ptype == "anthropic":
            # no /models; use manual models
            found = []
            for raw in prov.get("models") or []:
                found.append({"raw": raw, "provider_id": pid, "provider_name": pname, "provider_type": "anthropic", "is_local": is_local})
        # merge manual models
        for raw in prov.get("models") or []:
            if not any(m["raw"] == raw and m["provider_id"] == pid for m in found):
                found.append({"raw": raw, "provider_id": pid, "provider_name": pname, "provider_type": ptype, "is_local": is_local})

        online = bool(found)
        status.append({"id": pid, "name": pname, "type": ptype, "base_url": base_url, "online": online})
        models.extend(found)

    # Build final model list with composite ids.
    final_models = []
    for m in models:
        raw = m["raw"]
        pid = m["provider_id"]
        pname = m["provider_name"]
        ptype = m["provider_type"]
        is_local = m["is_local"]
        final_models.append({
            "id": f"{pid}::{raw}",
            "name": f"[{pname}] {raw}",
            "model": raw,
            "provider_id": pid,
            "provider_name": pname,
            "provider_type": ptype,
            "is_local": is_local,
        })

    # Dedup by id
    seen = set()
    deduped = []
    for m in final_models:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        deduped.append(m)

    default = deduped[0]["id"] if deduped else None
    return deduped, status, default


def get_models_config() -> dict:
    models, status, default = discover_models()
    return {
        "default": default,
        "models": models,
        "providers_status": status,
    }
