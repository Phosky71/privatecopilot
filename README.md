# PrivateCopilot

PrivateCopilot is a **local, single-user AI coding assistant**. It provides isolated workspaces over local folders, a from-scratch RAG system built on ChromaDB and SentenceTransformers (`all-MiniLM-L6-v2`), and a streaming chat interface powered by a local Ollama model. The assistant can propose file edits as `<edit>` blocks that are reviewed through a diff viewer and applied via Git branches/commits.

## Implemented features

- **Workspace isolation**: open a folder directly as a workspace (`+ Open Workspace Folder` / `POST /workspace/open`), attach folders/files, switch active workspace.
- **Indexing**: incremental indexing by file mtime, chunking (1000 chars, 200 overlap), embeddings stored in a per-workspace ChromaDB collection.
- **Semantic search (RAG)**: top-k retrieval injected into the LLM prompt.
- **Streaming chat**: Server-Sent Events from the FastAPI backend to the React frontend.
- **Model selection**: auto-detects Ollama, LM Studio and llama.cpp; supports cloud providers (OpenAI, Anthropic, OpenRouter, Groq, DeepSeek, custom OpenAI-compatible) with API keys; unified selector with refresh.
- **File browser**: browse the host filesystem to pick folders/files (intended for local use).
- **HITL file editing**: assistant emits `<edit file="...">` blocks; the UI shows a diff and the user accepts/rejects. Accepted edits create a `feature/ai-edit-*` branch, apply the change (preserving CRLF/LF) and commit.
- **Git status panel**: branch and pending changes for the first folder of the active workspace; `/git/status` is read-only and reports `initialized`.
- **Configurable Git init policy**: `ask` (default), `auto`, `never` via `/git/config` and `/git/init`.
- **Multi-turn chat**: conversation history persisted per workspace (`GET/DELETE /chat/history`), sent to Ollama `/api/chat`.
- **Multi-repository Git**: workspaces with multiple folders report `repositories` in `/git/status`; edits route to the correct repo.
- **Live indexing progress**: `POST /index/start`, `GET /index/status`, `GET /index/stream` (SSE) with per-file progress.
- **Health endpoint**: `GET /health` reports API status, Ollama availability and core dependencies.

## Requirements

- Python 3.12+ (verified on Python 3.14)
- Node.js 20+ (verified on Node 24)
- Git
- Ollama running locally with a code model. Verified environment has `qwen3.6:35b-a3b-coding`; any local Ollama code model works (configure via usage).

## Installation

### Backend

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
# Dev tools:
pip install -r requirements-dev.txt
```

### Frontend

```bash
cd frontend
npm install
```

## Running

From the repository root:

**Windows:**
```cmd
start.bat
```

**Cross-platform:**
```bash
python run.py
```

Or manually:

```bash
# terminal 1
cd backend && venv\Scripts\activate && uvicorn main:app --reload --host 127.0.0.1 --port 8000
# terminal 2
cd frontend && npm run dev
```

- Backend: `http://127.0.0.1:8000` (health: `GET /health`)
- Frontend: Vite default (usually `http://localhost:5173`)

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated CORS origins |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `BACKEND_HOST` | `127.0.0.1` | Backend bind host (run.py) |
| `BACKEND_PORT` | `8000` | Backend port (run.py) |
| `VITE_API_URL` | `http://localhost:8000` | Frontend API base URL |

## Verification commands

Backend:
```bash
cd backend
venv\Scripts\python.exe -m ruff check backend
venv\Scripts\python.exe -m pytest backend/tests -v
```

Frontend:
```bash
cd frontend
npm run lint
npm test
npx tsc -p tsconfig.app.json --noEmit --incremental false
npm run build
```

## Distribution and unified execution

Build distributables with:

```bash
python scripts/build_dist.py --target all --version 1.0.0
```

This produces `dist/privatecopilot-<version>-windows.zip`, `dist/privatecopilot-<version>-linux.tar.gz` and `dist/privatecopilot-<version>-macos.tar.gz`.

Each package includes `launch.py`, `start.bat`/`start.sh`, backend code, `frontend_dist/`, `workspaces/.gitkeep`, `LICENSE` and `README.md`. Run `python launch.py` (or `start.bat`/`start.sh`) to create a local venv, install dependencies and start the app at `http://127.0.0.1:8000`.

## CI/CD

- GitHub Actions: `.github/workflows/ci-release.yml`
- Gitea Actions: `.gitea/workflows/ci-release.yml`

Both run backend (ruff + pytest) and frontend (test, lint, tsc, build) checks, package distributables, and (GitHub only) create a release on `v*` tags.

## License

This project is licensed under the MIT License. See `LICENSE`.

## Limitations and current security scope

- Intended for **local, single-user** use on `127.0.0.1`. **No authentication or authorization** is implemented.
- The `/fs/list` endpoint can browse the host filesystem of the machine running the backend.
- Git operations use the **first folder** of a workspace as the repository root; `init_repo_if_needed` may initialize a repository and create an initial commit there.
- Ollama and the embedding model run locally; no cloud calls are made.
- Workspaces store absolute paths and local vector data under `workspaces/`.