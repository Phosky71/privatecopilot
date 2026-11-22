import subprocess
from pathlib import Path

import pytest
from services.git_service import GitInitDisabledError, GitService


def _init_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=path, check=True, capture_output=True,
    )


def _make_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folders: list[Path]):
    import services.git_service as gs_mod
    import services.workspace_service as ws_mod

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(ws_mod, "WORKSPACES_DIR", str(tmp_path / "workspaces"))
    (tmp_path / "workspaces").mkdir(exist_ok=True)
    monkeypatch.setattr(ws_mod.workspace_service, "_get_workspace_dir", lambda _ws: str(ws_dir))

    ws_id = "ws-multi"
    monkeypatch.setattr(ws_mod.workspace_service, "get_workspace", lambda _ws: {
        "id": ws_id,
        "name": "multi",
        "folders": [str(f) for f in folders],
        "files": [],
    })
    monkeypatch.setattr(gs_mod.workspace_service, "get_workspace", ws_mod.workspace_service.get_workspace)
    return ws_id


def test_multi_repo_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    _init_repo(repo1)
    _init_repo(repo2)

    ws_id = _make_workspace(tmp_path, monkeypatch, [repo1, repo2])

    svc = GitService()
    status = svc.get_status(ws_id)
    assert "repositories" in status
    assert len(status["repositories"]) == 2
    # no .git created in non-repo folders (already repos here)
    assert status["repositories"][0]["initialized"] is True
    assert status["repositories"][1]["initialized"] is True


def test_multi_repo_apply_absolute_and_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    _init_repo(repo1)
    _init_repo(repo2)
    (repo1 / "a.txt").write_text("hello\n", encoding="utf-8")
    (repo2 / "b.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo1, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add a"], cwd=repo1, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo2, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add b"], cwd=repo2, check=True, capture_output=True)

    ws_id = _make_workspace(tmp_path, monkeypatch, [repo1, repo2])
    # set policy auto
    import services.git_service as gs_mod
    import services.workspace_service as ws_mod
    monkeypatch.setattr(ws_mod.workspace_service, "get_git_init_policy", lambda: "auto")
    monkeypatch.setattr(gs_mod.workspace_service, "get_git_init_policy", lambda: "auto")

    svc = GitService()

    # absolute path to repo2
    _, repo = svc.apply_edit_and_commit(ws_id, str(repo2 / "b.txt"), "hello", "hi", confirm_git_init=True)
    assert repo == str(repo2.resolve())
    assert (repo2 / "b.txt").read_text(encoding="utf-8") == "hi\n"

    # relative unique: a.txt only in repo1
    (repo1 / "a.txt").write_text("hello\n", encoding="utf-8")
    _, repo = svc.apply_edit_and_commit(ws_id, "a.txt", "hello", "hi", confirm_git_init=True)
    assert repo == str(repo1.resolve())

    # prefix with folder name
    (repo2 / "sub.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "sub.txt"], cwd=repo2, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-m", "add sub"], cwd=repo2, check=True, capture_output=True)
    _, repo = svc.apply_edit_and_commit(ws_id, "repo2/sub.txt", "hello", "hi", confirm_git_init=True)
    assert repo == str(repo2.resolve())


def test_multi_repo_ambiguous_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    _init_repo(repo1)
    _init_repo(repo2)

    ws_id = _make_workspace(tmp_path, monkeypatch, [repo1, repo2])
    import services.git_service as gs_mod
    import services.workspace_service as ws_mod
    monkeypatch.setattr(ws_mod.workspace_service, "get_git_init_policy", lambda: "auto")
    monkeypatch.setattr(gs_mod.workspace_service, "get_git_init_policy", lambda: "auto")

    svc = GitService()
    with pytest.raises(ValueError):
        svc.apply_edit_and_commit(ws_id, "newfile.txt", "", "content\n", confirm_git_init=True)

    # with explicit repo_path works
    _, repo = svc.apply_edit_and_commit(ws_id, "newfile.txt", "", "content\n", confirm_git_init=True, repo_path=str(repo1))
    assert repo == str(repo1.resolve())
    assert (repo1 / "newfile.txt").read_text(encoding="utf-8") == "content\n"


def test_multi_repo_outside_workspace_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo1 = tmp_path / "repo1"
    _init_repo(repo1)
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")

    ws_id = _make_workspace(tmp_path, monkeypatch, [repo1])
    import services.git_service as gs_mod
    import services.workspace_service as ws_mod
    monkeypatch.setattr(ws_mod.workspace_service, "get_git_init_policy", lambda: "auto")
    monkeypatch.setattr(gs_mod.workspace_service, "get_git_init_policy", lambda: "auto")

    svc = GitService()
    with pytest.raises(ValueError):
        svc.apply_edit_and_commit(ws_id, str(outside), "x", "y", confirm_git_init=True)


def test_git_init_with_repo_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()

    ws_id = _make_workspace(tmp_path, monkeypatch, [repo1, repo2])
    import services.git_service as gs_mod
    import services.workspace_service as ws_mod
    monkeypatch.setattr(ws_mod.workspace_service, "get_git_init_policy", lambda: "ask")
    monkeypatch.setattr(gs_mod.workspace_service, "get_git_init_policy", lambda: "ask")

    svc = GitService()
    # init only repo2
    initialized = svc.init_repo(ws_id, str(repo2))
    assert initialized == str(repo2.resolve())
    assert (repo2 / ".git").exists()
    assert not (repo1 / ".git").exists()

    # policy never blocks
    monkeypatch.setattr(ws_mod.workspace_service, "get_git_init_policy", lambda: "never")
    monkeypatch.setattr(gs_mod.workspace_service, "get_git_init_policy", lambda: "never")
    with pytest.raises(GitInitDisabledError):
        svc.init_repo(ws_id, str(repo1))