import os
import subprocess
import time
from pathlib import Path

from core.logging_config import logger
from services.workspace_service import workspace_service


class GitInitRequiredError(Exception):
    pass


class GitInitDisabledError(Exception):
    pass


class GitService:
    def _get_repo_path(self, workspace_id: str) -> str:
        ws = workspace_service.get_workspace(workspace_id)
        folders = ws.get("folders", [])
        if not folders:
            raise ValueError("Workspace has no indexed folders to use as a Git repository root.")
        return folders[0]  # Use the first folder as the repo root

    def _run_cmd(self, cmd: list, cwd: str) -> str:
        try:
            result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error("[GIT ERROR] %s\n%s", " ".join(cmd), e.stderr)
            raise RuntimeError(f"Git command failed: {e.stderr}") from e

    def _branch_exists(self, repo_path: str, branch: str) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def init_repo_if_needed(self, repo_path: str):
        if not os.path.exists(os.path.join(repo_path, ".git")):
            self._run_cmd(["git", "init"], cwd=repo_path)
            self._run_cmd(["git", "add", "."], cwd=repo_path)
            try:
                self._run_cmd(["git", "-c", "user.email=privatecopilot@local", "-c", "user.name=PrivateCopilot", "commit", "-m", "Initial commit"], cwd=repo_path)
            except RuntimeError as e:
                logger.warning("Initial commit skipped: %s", e)

    def get_status(self, workspace_id: str):
        try:
            roots = self._get_workspace_repos(workspace_id)
            repositories = []
            for root in roots:
                git_dir = root / ".git"
                if not git_dir.exists():
                    repositories.append({
                        "repo_path": str(root),
                        "name": root.name,
                        "initialized": False,
                        "branch": None,
                        "pending_changes": [],
                    })
                    continue
                try:
                    branch = self._run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root))
                    status_output = self._run_cmd(["git", "status", "--porcelain"], cwd=str(root))
                    pending_changes: list[str] = []
                    if status_output:
                        for line in status_output.split("\n"):
                            if line.strip():
                                pending_changes.append(line.strip())
                    repositories.append({
                        "repo_path": str(root),
                        "name": root.name,
                        "initialized": True,
                        "branch": branch,
                        "pending_changes": pending_changes,
                    })
                except Exception as e:  # noqa: BLE001
                    repositories.append({
                        "repo_path": str(root),
                        "name": root.name,
                        "initialized": False,
                        "branch": None,
                        "pending_changes": [],
                        "error": str(e),
                    })

            first = repositories[0] if repositories else {
                "initialized": False,
                "branch": None,
                "pending_changes": [],
                "repo_path": None,
            }
            return {
                "initialized": first.get("initialized", False),
                "branch": first.get("branch"),
                "pending_changes": first.get("pending_changes", []),
                "repo_path": first.get("repo_path"),
                "repositories": repositories,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Git status failed: %s", e)
            return {"initialized": False, "branch": None, "pending_changes": [], "error": str(e)}

    def _get_workspace_repos(self, workspace_id: str) -> list[Path]:
        ws = workspace_service.get_workspace(workspace_id)
        roots: list[Path] = []
        for folder in ws.get("folders", []):
            if not os.path.exists(folder):
                continue
            p = Path(folder).resolve()
            # Remove any existing root that is inside p.
            roots = [r for r in roots if not r.is_relative_to(p)]
            if p not in roots and not any(p.is_relative_to(r) for r in roots):
                roots.append(p)
        return roots

    def init_repo(self, workspace_id: str, repo_path: str | None = None) -> str:
        roots = self._get_workspace_repos(workspace_id)
        target_root: Path | None = None
        if repo_path:
            rp = Path(repo_path).resolve()
            if rp in roots:
                target_root = rp
        if target_root is None and roots:
            target_root = roots[0]
        if target_root is None:
            raise ValueError("Workspace has no repository roots.")
        policy = workspace_service.get_git_init_policy()
        if policy == "never":
            raise GitInitDisabledError("Git initialization is disabled by policy.")
        self.init_repo_if_needed(str(target_root))
        return str(target_root)

    def _resolve_target(self, workspace_id: str, file_path: str, original: str, repo_path: str | None = None):
        ws = workspace_service.get_workspace(workspace_id)
        folders = [Path(f).resolve() for f in ws.get("folders", []) if os.path.exists(f)]
        files = [Path(f).resolve() for f in ws.get("files", []) if os.path.exists(f)]
        allowed = folders + files
        roots = self._get_workspace_repos(workspace_id)

        target = Path(file_path)
        if repo_path:
            rp = Path(repo_path).resolve()
            if rp not in roots:
                raise ValueError("repo_path is not a valid repository root for this workspace.")
            target_repo = rp
            if target.is_absolute():
                target_path = target.resolve()
            else:
                target_path = (target_repo / target).resolve()
        elif target.is_absolute():
            target_path = target.resolve()
            containing = [r for r in roots if target_path.is_relative_to(r)]
            if not containing:
                raise ValueError(f"File {file_path} is outside the repository bounds.")
            target_repo = max(containing, key=lambda r: len(str(r)))
        else:
            direct = [r for r in roots if (r / target).exists()]
            if len(direct) == 1:
                target_repo = direct[0]
                target_path = (target_repo / target).resolve()
            elif len(direct) > 1:
                raise ValueError("Ambiguous repository for file_path; specify repo_path.")
            else:
                parts = target.parts
                prefix_candidates = [r for r in roots if parts and r.name == parts[0]] if parts else []
                if len(prefix_candidates) == 1 and len(parts) > 1:
                    target_repo = prefix_candidates[0]
                    target_path = (target_repo / Path(*parts[1:])).resolve()
                elif len(prefix_candidates) > 1:
                    raise ValueError("Ambiguous repository for file_path; specify repo_path.")
                else:
                    if original.strip() == "" and len(roots) == 1:
                        target_repo = roots[0]
                        target_path = (target_repo / target).resolve()
                    else:
                        raise ValueError("Ambiguous repository for file_path; specify repo_path.")

        # Security: target must be within an allowed workspace path.
        if not any(target_path == a or target_path.is_relative_to(a) for a in allowed):
            raise ValueError(f"File {file_path} is outside the repository bounds.")

        if target_repo not in roots:
            raise ValueError(f"File {file_path} is outside the repository bounds.")

        return target_repo, target_path

    def apply_edit_and_commit(self, workspace_id: str, file_path: str, original: str, replacement: str, confirm_git_init: bool = False, repo_path: str | None = None) -> tuple[str, str]:
        target_repo, target_path = self._resolve_target(workspace_id, file_path, original, repo_path)
        repo_path = str(target_repo)

        logger.info("[AI ACTION] type=edit workspace=%s file=%s status=approved", workspace_id, target_path)

        git_dir = os.path.join(repo_path, ".git")
        if not os.path.exists(git_dir):
            policy = workspace_service.get_git_init_policy()
            if policy == "never":
                raise GitInitDisabledError("Git initialization is disabled by policy.")
            if policy == "ask" and not confirm_git_init:
                raise GitInitRequiredError("Git repository is not initialized in this workspace folder.")
            # auto or confirmed ask
            self.init_repo_if_needed(repo_path)

        if not target_path.exists():
            if original.strip() == "":
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "w", encoding="utf-8", newline="") as f:
                    f.write(replacement)
            else:
                raise FileNotFoundError(f"File {file_path} not found.")
        else:
            with open(target_path, "r", encoding="utf-8", newline="") as f:
                content = f.read()
            if original.strip():
                # Detect original line ending style.
                line_ending = "\r\n" if "\r\n" in content else "\n"
                norm_content = content.replace("\r\n", "\n")
                norm_orig = original.replace("\r\n", "\n")
                norm_repl = replacement.replace("\r\n", "\n")

                if norm_orig not in norm_content:
                    raise ValueError("Original text not found in file. AI may have hallucinated context.")

                new_content = norm_content.replace(norm_orig, norm_repl, 1)
                if line_ending == "\r\n":
                    new_content = new_content.replace("\n", "\r\n")
                with open(target_path, "w", encoding="utf-8", newline="") as f:
                    f.write(new_content)
            else:
                with open(target_path, "w", encoding="utf-8", newline="") as f:
                    f.write(replacement)

        logger.info("[AI ACTION] type=git workspace=%s file=%s status=pending", workspace_id, target_path)

        timestamp = int(time.time())
        branch_name = f"feature/ai-edit-{timestamp}"
        # Avoid branch name collisions within the same second.
        if self._branch_exists(repo_path, branch_name):
            suffix = 1
            while self._branch_exists(repo_path, f"{branch_name}-{suffix}"):
                suffix += 1
            branch_name = f"{branch_name}-{suffix}"

        try:
            self._run_cmd(["git", "checkout", "-b", branch_name], cwd=repo_path)
            self._run_cmd(["git", "add", str(target_path)], cwd=repo_path)

            filename = target_path.name
            self._run_cmd(["git", "-c", "user.email=privatecopilot@local", "-c", "user.name=PrivateCopilot", "commit", "-m", f"feat(ai): Updated {filename}"], cwd=repo_path)

            logger.info("[AI ACTION] type=git workspace=%s file=%s status=approved", workspace_id, target_path)
            return branch_name, repo_path
        except Exception as e:
            logger.error("[AI ACTION] type=git workspace=%s file=%s status=rejected", workspace_id, target_path)
            logger.error("Failed to commit: %s", e)
            raise


git_service = GitService()
