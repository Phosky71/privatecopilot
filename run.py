import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def _venv_python() -> str:
    root = Path(__file__).resolve().parent
    if os.name == "nt":
        candidate = root / "backend" / "venv" / "Scripts" / "python.exe"
    else:
        candidate = root / "backend" / "venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def run_backend():
    print("Starting backend...")
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = os.getenv("BACKEND_PORT", "8000")
    python = _venv_python()
    return subprocess.Popen(
        [python, "-m", "uvicorn", "main:app", "--reload", "--host", host, "--port", port],
        cwd="backend",
    )


def run_frontend():
    print("Starting frontend...")
    return subprocess.Popen("npm run dev", shell=True, cwd="frontend")


if __name__ == "__main__":
    backend_proc = None
    frontend_proc = None
    try:
        backend_proc = run_backend()
        time.sleep(2)
        frontend_proc = run_frontend()

        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                break
            if frontend_proc.poll() is not None:
                break
    except KeyboardInterrupt:
        print("\nShutting down PrivateCopilot...")
    finally:
        for proc in (frontend_proc, backend_proc):
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
        sys.exit(0)
```<|end|><|start|>startup to=write<|channel|>analysis <|constrain|>xml<|message|><rfl:parameter name="path">
C:\Trabajo\Proyectos\zSinRevisar\privatecopilot\run.py