# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-23

### Added
- Direct workspace opening by folder path (`+ Open Workspace Folder` / `POST /workspace/open`), with automatic name from folder basename and reuse of an existing workspace for the same resolved path.
- Workspace isolation with per-workspace ChromaDB collections, folders/files registration and active workspace persistence in `workspaces/.app_state.json`.
- From-scratch RAG system (ChromaDB + `all-MiniLM-L6-v2`), incremental indexing by mtime, orphaned vector cleanup, binary/size filtering and anti-hallucination rules in the LLM prompt.
- Real-time indexing progress via `POST /index/start`, `GET /index/status` and `GET /index/stream` (SSE) with phases, counts and percentage.
- Multi-provider LLM engine with parallel auto-detection of Ollama, LM Studio and llama.cpp, plus configurable OpenAI-compatible and Anthropic providers with local API key storage and masking.
- Multi-turn conversational chat via Ollama/OpenAI/Anthropic chat APIs, persistent per-workspace history (`GET/DELETE /chat/history`) and bounded history window.
- Human-in-the-loop file editing through `<edit>` blocks, diff viewer, Git branch creation and commit, with CRLF/LF preservation and multi-repository routing.
- Configurable Git initialization policy (`ask` / `auto` / `never`) with read-only `GET /git/status`, `/git/config`, `/git/init` and `POST /git/apply`.
- Unified web mode: FastAPI serves the built frontend (`frontend/dist`) with SPA fallback.
- Cross-platform distributable packager (`scripts/build_dist.py`) producing Windows `.zip`, Linux `.tar.gz` and macOS `.tar.gz`.
- MIT License, `AGENTS.md`, GitHub Actions and Gitea Actions workflows for CI and releases.
- Health endpoint (`GET /health`) reporting API, Ollama and dependency status.

### Changed
- Frontend switched to TypeScript + React 19 + Vite 8 with strict typing and ESLint.
- Backend switched to structured logging, thread-safe services and explicit timeouts for Ollama/HTTP providers.
- Workspace data and `.app_state.json` are ignored by Git; `workspaces/.gitkeep` preserves the empty folder.

### Security
- Strict path traversal validation using `Path.resolve()` and `is_relative_to()` in Git edits.
- No API keys are returned in clear text; responses expose only `has_api_key` and `api_key_masked`.
- `/fs/list` and Git operations are scoped to registered workspace paths.

### Verified
- Automated suite: 59 backend tests (`pytest`), 13 frontend tests (`npm test`), `ruff check backend scripts`, `eslint`, `tsc`, `vite build` all green.
- Functional validation performed live with LM Studio against a real workspace (RAG + chat + indexing progress).