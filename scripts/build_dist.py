import argparse
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_frontend_build():
    frontend_dir = ROOT / "frontend"
    subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)
    if not (frontend_dir / "dist" / "index.html").is_file():
        raise SystemExit("frontend/dist/index.html not found after build")


def assemble(target_dir: Path):
    backend_src = ROOT / "backend"
    backend_dst = target_dir / "backend"
    backend_dst.mkdir(parents=True, exist_ok=True)

    # Copy backend production code
    for name in ("api", "core", "db", "services"):
        src = backend_src / name
        if src.exists():
            shutil.copytree(src, backend_dst / name, dirs_exist_ok=True,
                           ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", "tests"))
    for fname in ("main.py", "requirements.txt"):
        src = backend_src / fname
        if src.exists():
            shutil.copy2(src, backend_dst / fname)

    # Remove tests if copied
    for p in backend_dst.rglob("tests"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    for p in backend_dst.rglob("__pycache__"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    frontend_dist_src = ROOT / "frontend" / "dist"
    if not frontend_dist_src.is_dir():
        raise SystemExit("frontend/dist not found; run npm run build or pass --skip-frontend-build with prebuilt dist")
    shutil.copytree(frontend_dist_src, target_dir / "frontend_dist", dirs_exist_ok=True)

    # workspaces/.gitkeep
    ws = target_dir / "workspaces"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".gitkeep").write_text("", encoding="utf-8")

    # LICENSE and README
    for fname in ("LICENSE", "README.md"):
        src = ROOT / fname
        if src.exists():
            shutil.copy2(src, target_dir / fname)

    # launch.py
    (target_dir / "launch.py").write_text(LAUNCH_PY, encoding="utf-8")

    # start.bat
    (target_dir / "start.bat").write_text(START_BAT, encoding="utf-8")

    # start.sh
    start_sh = target_dir / "start.sh"
    start_sh.write_text(START_SH, encoding="utf-8")
    os.chmod(start_sh, 0o755)


LAUNCH_PY = r'''import os
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV = BACKEND / "venv"
FRONTEND_DIST = ROOT / "frontend_dist"


def venv_python():
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def ensure_venv():
    py = venv_python()
    if py.exists():
        return py
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    py = venv_python()
    subprocess.run([str(py), "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")], check=True)
    return py


def main():
    no_browser = "--no-browser" in sys.argv
    py = ensure_venv()
    if not (BACKEND / "venv" / "Lib" / "site-packages" / "fastapi").exists() and not (BACKEND / "venv" / "lib").exists():
        subprocess.run([str(py), "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")], check=True)

    env = os.environ.copy()
    env["FRONTEND_DIST_DIR"] = str(FRONTEND_DIST)
    env["SERVE_FRONTEND"] = "true"

    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(BACKEND),
        env=env,
    )
    url = "http://127.0.0.1:8000"
    print(f"PrivateCopilot is running at {url}")
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
'''

START_BAT = """@echo off
python launch.py %*
"""

START_SH = """#!/usr/bin/env bash
python3 launch.py "$@"
"""


def make_zip(src_dir: Path, out_path: Path):
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                arc = path.relative_to(src_dir)
                zf.write(path, arc)


def make_targz(src_dir: Path, out_path: Path):
    with tarfile.open(out_path, "w:gz") as tf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                arc = path.relative_to(src_dir)
                info = tf.gettarinfo(str(path), arcname=str(arc))
                if path.name == "start.sh":
                    info.mode = 0o755
                with open(path, "rb") as f:
                    tf.addfile(info, f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["windows", "linux", "macos", "all"], default="all")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--skip-frontend-build", action="store_true")
    args = parser.parse_args()

    if not args.skip_frontend_build:
        run_frontend_build()

    frontend_dist = ROOT / "frontend" / "dist"
    if not (frontend_dist / "index.html").is_file():
        raise SystemExit("frontend/dist/index.html not found")

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = ["windows", "linux", "macos"] if args.target == "all" else [args.target]

    for target in targets:
        tmp = ROOT / ".build_tmp" / target
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        assemble(tmp)

        version = args.version
        if target == "windows":
            out_path = out_dir / f"privatecopilot-{version}-windows.zip"
            make_zip(tmp, out_path)
        elif target == "linux":
            out_path = out_dir / f"privatecopilot-{version}-linux.tar.gz"
            make_targz(tmp, out_path)
        elif target == "macos":
            out_path = out_dir / f"privatecopilot-{version}-macos.tar.gz"
            make_targz(tmp, out_path)
        print(f"Created {out_path}")

    # cleanup
    build_tmp = ROOT / ".build_tmp"
    if build_tmp.exists():
        shutil.rmtree(build_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
