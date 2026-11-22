import importlib
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest


def test_spa_serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log('x')", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_DIST_DIR", str(dist))
    monkeypatch.setenv("SERVE_FRONTEND", "true")

    # reload main to pick up env
    import main as main_module

    importlib.reload(main_module)
    from fastapi.testclient import TestClient

    client = TestClient(main_module.app)

    r = client.get("/")
    assert r.status_code == 200
    assert "SPA" in r.text

    r2 = client.get("/health")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"

    r3 = client.get("/workspace/noexiste")
    assert r3.status_code == 404
    assert "SPA" not in r3.text

    # static file
    r4 = client.get("/assets/app.js")
    assert r4.status_code == 200
    assert "console.log" in r4.text

    # restore default import state
    monkeypatch.delenv("FRONTEND_DIST_DIR", raising=False)
    importlib.reload(main_module)


def test_build_dist(tmp_path: Path):
    out_dir = tmp_path / "out"
    script = Path(__file__).resolve().parents[2] / "scripts" / "build_dist.py"
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
    if not frontend_dist.is_file():
        pytest.skip("frontend/dist not built")

    subprocess.run(
        [sys.executable, str(script), "--target", "all", "--skip-frontend-build", "--version", "9.9.9", "--output-dir", str(out_dir)],
        check=True,
        capture_output=True,
    )

    win = out_dir / "privatecopilot-9.9.9-windows.zip"
    linux = out_dir / "privatecopilot-9.9.9-linux.tar.gz"
    macos = out_dir / "privatecopilot-9.9.9-macos.tar.gz"
    assert win.is_file()
    assert linux.is_file()
    assert macos.is_file()

    with zipfile.ZipFile(win) as zf:
        names = zf.namelist()
        assert any("backend/main.py" in n for n in names)
        assert any("frontend_dist/index.html" in n for n in names)
        assert any("LICENSE" in n for n in names)
        assert any("launch.py" in n for n in names)
        assert any("start.bat" in n for n in names)
        assert any("start.sh" in n for n in names)
        assert not any("/tests/" in n for n in names)
        assert not any("/venv/" in n for n in names)

    with tarfile.open(linux, "r:gz") as tf:
        names = tf.getnames()
        assert any("backend/main.py" in n for n in names)
        assert any("frontend_dist/index.html" in n for n in names)
        # start.sh executable bit
        for m in tf.getmembers():
            if m.name.endswith("start.sh"):
                assert (m.mode & 0o111) != 0
