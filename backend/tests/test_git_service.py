import subprocess
from pathlib import Path

import pytest
from services.git_service import GitService


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = _init_repo(tmp_path / "repo")
    import services.git_service as gs_mod

    monkeypatch.setattr(gs_mod.workspace_service, "get_workspace", lambda _ws: {"folders": [str(r)]})
    return r


def test_path_traversal_relative(repo: Path):
    svc = GitService()
    with pytest.raises(ValueError):
        svc.apply_edit_and_commit("ws", "../evil.txt", "", "x")


def test_path_traversal_sibling(repo: Path):
    svc = GitService()
    sibling = repo.parent / "repo-evil"
    sibling.mkdir()
    target = sibling / "x.txt"
    with pytest.raises(ValueError):
        svc.apply_edit_and_commit("ws", str(target), "", "x")


def test_path_traversal_absolute_external(repo: Path):
    svc = GitService()
    external = repo.parent / "outside.txt"
    with pytest.raises(ValueError):
        svc.apply_edit_and_commit("ws", str(external), "a", "b")


def test_normal_edit(repo: Path):
    f = repo / "a.txt"
    f.write_text("foo bar\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add a"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    svc = GitService()
    branch, _ = svc.apply_edit_and_commit("ws", "a.txt", "foo", "baz")
    assert branch.startswith("feature/ai-edit-")
    assert f.read_text(encoding="utf-8") == "baz bar\n"


def test_create_new_file(repo: Path):
    svc = GitService()
    branch, _ = svc.apply_edit_and_commit("ws", "new.txt", "", "content\n")
    assert branch.startswith("feature/ai-edit-")
    assert (repo / "new.txt").read_text(encoding="utf-8") == "content\n"


def test_preserve_crlf(repo: Path):
    f = repo / "c.txt"
    f.write_bytes(b"line1\r\nline2\r\n")
    subprocess.run(["git", "add", "c.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add c"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    svc = GitService()
    svc.apply_edit_and_commit("ws", "c.txt", "line1", "LINE1")
    result = f.read_bytes()
    assert b"\r\n" in result
    assert result == b"LINE1\r\nline2\r\n"


def test_preserve_lf(repo: Path):
    f = repo / "l.txt"
    f.write_text("line1\nline2\n", encoding="utf-8")
    subprocess.run(["git", "add", "l.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add l"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    svc = GitService()
    svc.apply_edit_and_commit("ws", "l.txt", "line1", "LINE1")
    result = f.read_text(encoding="utf-8")
    assert "\r\n" not in result
    assert result == "LINE1\nline2\n"


def test_no_branch_collision_same_second(repo: Path, monkeypatch: pytest.MonkeyPatch):
    # Force same timestamp by monkeypatching time.time
    import services.git_service as gs

    monkeypatch.setattr(gs.time, "time", lambda: 1234567890)
    f = repo / "x.txt"
    f.write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add x"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    svc = GitService()
    b1, _ = svc.apply_edit_and_commit("ws", "x.txt", "a", "b")
    # Reset working tree to allow second edit on same file
    subprocess.run(["git", "checkout", "main" if False else "master"], cwd=repo, capture_output=True, check=False)
    # Instead, create another file to avoid checkout issues
    f2 = repo / "y.txt"
    f2.write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "y.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add y"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    b2, _ = svc.apply_edit_and_commit("ws", "y.txt", "a", "b")
    assert b1 != b2
