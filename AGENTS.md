# AGENTS.md

## Architecture
- `backend/`: FastAPI app (`main.py`), routers in `api/`, core logic in `core/`, services in `services/`, ChromaDB manager in `db/`.
- `frontend/`: React + TypeScript + Vite SPA.
- `scripts/build_dist.py`: cross-platform packager for distributable web bundles.
- `workspaces/`: runtime data (ignored by Git, contains `.gitkeep`).

## Verification commands
Backend:
- `ruff check backend scripts`
- `pytest backend/tests -v`

Frontend:
- `npm test`
- `npm run lint`
- `npx tsc -p tsconfig.app.json --noEmit --incremental false`
- `npm run build`

## Conventions
- Use Conventional Commits.
- Do not version `workspaces/` runtime data or `backend/venv`.
- Do not run destructive Git commands (`push --force`, `reset --hard`, `clean -fd`).
- Keep tests, linters and builds green.