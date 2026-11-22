import os
from pathlib import Path

import uvicorn
from api.chat_routes import router as chat_router
from api.fs_routes import router as fs_router
from api.git_routes import router as git_router
from api.index_routes import router as index_router
from api.model_routes import router as model_router
from api.workspace_routes import router as workspace_router
from core.logging_config import configure_logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

configure_logging()

app = FastAPI(title="PrivateCopilot API")

_allowed = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
allowed_origins = [o.strip() for o in _allowed.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspace_router, prefix="/workspace", tags=["Workspace"])
app.include_router(chat_router, prefix="/chat", tags=["Chat"])
app.include_router(index_router, prefix="/index", tags=["Index"])
app.include_router(model_router, prefix="/model", tags=["Model"])
app.include_router(fs_router, prefix="/fs", tags=["FileSystem"])
app.include_router(git_router, prefix="/git", tags=["Git"])


@app.get("/health")
def health():
    import requests

    ollama_ok = False
    try:
        res = requests.get(f"{os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}/api/tags", timeout=2)
        ollama_ok = res.status_code == 200
    except Exception:  # noqa: BLE001
        ollama_ok = False

    deps = {}
    for mod in ("chromadb", "sentence_transformers", "fastapi", "uvicorn"):
        try:
            __import__(mod)
            deps[mod] = True
        except Exception:  # noqa: BLE001
            deps[mod] = False

    return {
        "status": "ok",
        "ollama": ollama_ok,
        "dependencies": deps,
    }


@app.get("/")
def read_root():
    dist_dir = _resolve_frontend_dist()
    if dist_dir is not None:
        index_html = dist_dir / "index.html"
        if index_html.exists():
            return FileResponse(index_html)
    return {"message": "PrivateCopilot API is running"}


API_PREFIXES = ("/workspace", "/chat", "/index", "/model", "/fs", "/git", "/health", "/docs", "/openapi.json", "/redoc")


def _resolve_frontend_dist() -> Path | None:
    if os.getenv("SERVE_FRONTEND", "true").lower() == "false":
        return None

    candidates = []
    env_dir = os.getenv("FRONTEND_DIST_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    repo_root = Path(__file__).resolve().parent.parent
    candidates.append(repo_root / "frontend_dist")
    candidates.append(repo_root / "frontend" / "dist")

    for candidate in candidates:
        try:
            if (candidate / "index.html").is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


_dist_dir = _resolve_frontend_dist()
if _dist_dir is not None:
    _assets = _dist_dir / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    from fastapi.responses import RedirectResponse

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path == "":
            return FileResponse(_dist_dir / "index.html")
        first = "/" + full_path.split("/", 1)[0]
        # Redirect bare API prefixes to their trailing-slash forms.
        if first in API_PREFIXES and not full_path.endswith("/"):
            return RedirectResponse(url=f"/{full_path}/", status_code=307)
        if any(first == p or first.startswith(p + "/") for p in API_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")
        target = (_dist_dir / full_path).resolve()
        if target.is_file() and target.is_relative_to(_dist_dir):
            return FileResponse(target)
        return FileResponse(_dist_dir / "index.html")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
