# PrivateCopilot Frontend

React + TypeScript + Vite frontend for PrivateCopilot.

## Scripts

- `npm run dev` — start Vite dev server.
- `npm run build` — typecheck and build for production.
- `npm run lint` — run ESLint.
- `npm test` — run unit tests for the edit-block parser (Node test runner).
- `npm run preview` — preview production build.

## Configuration

Set `VITE_API_URL` (defaults to `http://localhost:8000`) to point at the backend.

## Structure

- `src/App.tsx` — main layout, state and chat streaming.
- `src/components/` — chat, settings, file browser, diff viewer.
- `src/utils/editParser.ts` — pure parser for `<edit>` blocks in assistant messages.
- `src/types.ts` — shared TypeScript contracts.
- `src/config.ts` — API base URL.