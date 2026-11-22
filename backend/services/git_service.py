import os
import subprocess
import time
from pathlib import Path

from core.logging_config import logger
from services.workspace_service import workspace_service


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
                self._run_cmd(["git", "commit", "-m", "Initial commit"], cwd=repo_path)
            except RuntimeError as e:
                logger.warning("Initial commit skipped: %s", e)

    def get_status(self, workspace_id: str):
        try:
            repo_path = self._get_repo_path(workspace_id)
            self.init_repo_if_needed(repo_path)
            branch = self._run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
            status_output = self._run_cmd(["git", "status", "--porcelain"], cwd=repo_path)

            pending_changes: list[str] = []
            if status_output:
                for line in status_output.split("\n"):
                    if line.strip():
                        pending_changes.append(line.strip())

            return {
                "branch": branch,
                "pending_changes": pending_changes,
                "repo_path": repo_path,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Git status failed: %s", e)
            return {"branch": "unknown", "pending_changes": [], "error": str(e)}

    def apply_edit_and_commit(self, workspace_id: str, file_path: str, original: str, replacement: str) -> str:
        repo_path = self._get_repo_path(workspace_id)
        repo_root = Path(repo_path).resolve()

        target = Path(file_path)
        if target.is_absolute():
            target_path = target.resolve()
        else:
            target_path = (repo_root / target).resolve()

        if not target_path.is_relative_to(repo_root):
            raise ValueError(f"File {file_path} is outside the repository bounds.")

        logger.info("[AI ACTION] type=edit workspace=%s file=%s status=approved", workspace_id, target_path)

        if not target_path.exists():
            if original.strip() == "":
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(replacement, encoding="utf-8", newline="")
            else:
                raise FileNotFoundError(f"File {file_path} not found.")
        else:
            content = target_path.read_text(encoding="utf-8", newline="")
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
                target_path.write_text(new_content, encoding="utf-8", newline="")
            else:
                target_path.write_text(replacement, encoding="utf-8", newline="")

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
            self._run_cmd(["git", "commit", "-m", f"feat(ai): Updated {filename}"], cwd=repo_path)

            logger.info("[AI ACTION] type=git workspace=%s file=%s status=approved", workspace_id, target_path)
            return branch_name
        except Exception as e:
            logger.error("[AI ACTION] type=git workspace=%s file=%s status=rejected", workspace_id, target_path)
            logger.error("Failed to commit: %s", e)
            raise


git_service = GitService()
