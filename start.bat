@echo off
echo Starting PrivateCopilot...

echo Starting Backend...
start cmd /k "cd backend && call venv\Scripts\activate.bat && uvicorn main:app --reload --host 127.0.0.1 --port 8000"

echo Starting Frontend...
start cmd /k "cd frontend && npm run dev"

echo Both services started.