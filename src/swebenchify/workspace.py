"""Workspace manager.

Maintains bare clones, creates per-commit worktrees, and manages
workspace lifecycle. See docs/SPEC.md Section 8.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from swebenchify.models import Repository

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manage workspaces for agent sessions.

    Handles bare clones, git worktrees, environment spec caching, and
    instance workspace lifecycle.  All workspace paths are rooted under
    a single ``root`` directory.

    Layout (from docs/SPEC.md Section 8.1)::

        {root}/
          {repo_slug}/
            repo.git/                          # bare clone
            envs/
              {version}/
                env_spec.json                  # cached EnvironmentSpec
                version.json                   # cached RepoVersion
                repo/                          # worktree at version commit
            instances/
              {instance_id}/
                repo/                          # worktree at base_commit
                test.patch
                gold.patch
                validation_result.json
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ #
    # Path helpers
    # ------------------------------------------------------------------ #

    def repo_dir(self, repo: Repository) -> Path:
        """Root dir for a repo: ``{root}/{slug}/``."""
        return self.root / repo.slug

    def bare_clone_path(self, repo: Repository) -> Path:
        """Path to the bare clone: ``{root}/{slug}/repo.git/``."""
        return self.repo_dir(repo) / "repo.git"

    def env_cache_dir(self, repo: Repository, version: str) -> Path:
        """Cache dir for env specs: ``{root}/{slug}/envs/{version}/``."""
        return self.repo_dir(repo) / "envs" / version

    def instance_dir(self, instance_id: str) -> Path:
        """Working dir for an instance: ``{root}/{slug}/instances/{instance_id}/``.

        The slug is extracted from the instance_id by splitting on the
        last ``-`` character (e.g. ``"owner__repo-123"`` -> ``"owner__repo"``).
        """
        slug = instance_id.rsplit("-", 1)[0]
        return self.root / slug / "instances" / instance_id

    # ------------------------------------------------------------------ #
    # Git operations
    # ------------------------------------------------------------------ #

    def ensure_bare_clone(self, repo: Repository) -> Path:
        """Clone the repo as a bare clone if not already present.

        Returns the path to the bare clone directory.
        """
        clone_path = self.bare_clone_path(repo)
        if clone_path.exists():
            logger.info("Bare clone exists: %s", clone_path)
            return clone_path

        clone_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{repo.full_name}.git"
        if repo.access_token:
            url = (
                f"https://x-access-token:{repo.access_token}"
                f"@github.com/{repo.full_name}.git"
            )

        logger.info("Cloning %s to %s", repo.full_name, clone_path)
        try:
            subprocess.run(
                ["git", "clone", "--bare", url, str(clone_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            sanitized_cmd = (
                [c.replace(repo.access_token, "***") for c in e.cmd]
                if repo.access_token
                else e.cmd
            )
            raise subprocess.CalledProcessError(
                e.returncode, sanitized_cmd, e.stdout, e.stderr
            ) from None
        return clone_path

    def create_worktree(
        self, repo: Repository, commit: str, target_dir: Path
    ) -> Path:
        """Create a git worktree at *target_dir* checked out at *commit*.

        If *target_dir* already exists the method returns immediately.
        Before creating the worktree, a ``git fetch origin`` is issued
        against the bare clone so that the requested commit is available.

        Returns the *target_dir* path.
        """
        if target_dir.exists():
            logger.info("Worktree already exists: %s", target_dir)
            return target_dir

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        bare_clone = self.bare_clone_path(repo)

        # Fetch latest to make sure we have the commit.
        subprocess.run(
            ["git", "--git-dir", str(bare_clone), "fetch", "origin"],
            capture_output=True,
            text=True,
        )

        # Create the worktree in detached-HEAD mode.
        subprocess.run(
            [
                "git",
                "--git-dir",
                str(bare_clone),
                "worktree",
                "add",
                "--detach",
                str(target_dir),
                commit,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return target_dir

    # ------------------------------------------------------------------ #
    # High-level workspace preparation
    # ------------------------------------------------------------------ #

    def prepare_env_workspace(
        self, repo: Repository, commit: str, version: str
    ) -> Path:
        """Prepare workspace for environment discovery.

        Ensures the bare clone exists and creates a worktree at *commit*
        inside the version cache directory.

        Returns the worktree path (``envs/{version}/repo/``).
        """
        env_dir = self.env_cache_dir(repo, version)
        worktree = env_dir / "repo"
        self.ensure_bare_clone(repo)
        self.create_worktree(repo, commit, worktree)
        return worktree

    def prepare_validation_workspace(
        self,
        repo: Repository,
        instance_id: str,
        base_commit: str,
        test_patch: str,
        gold_patch: str,
    ) -> Path:
        """Prepare workspace for instance validation.

        Creates the instance directory, sets up a worktree at
        *base_commit*, and writes the test and gold patch files.

        Returns the instance directory path.
        """
        inst_dir = self.instance_dir(instance_id)
        worktree = inst_dir / "repo"
        self.ensure_bare_clone(repo)
        self.create_worktree(repo, base_commit, worktree)

        # Write patch files.
        (inst_dir / "test.patch").write_text(test_patch)
        (inst_dir / "gold.patch").write_text(gold_patch)
        return inst_dir

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #

    def cleanup_instance(self, repo: Repository, instance_id: str) -> None:
        """Remove an instance workspace and its worktree."""
        import shutil

        inst_dir = self.instance_dir(instance_id)
        worktree = inst_dir / "repo"
        bare_clone = self.bare_clone_path(repo)

        if worktree.exists():
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(bare_clone),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                ],
                capture_output=True,
                text=True,
            )

        if inst_dir.exists():
            shutil.rmtree(inst_dir)

    # ------------------------------------------------------------------ #
    # Caching
    # ------------------------------------------------------------------ #

    def get_cached_env_spec(self, repo: Repository, version: str) -> dict | None:
        """Return the cached ``env_spec.json`` for *version*, or ``None``."""
        spec_path = self.env_cache_dir(repo, version) / "env_spec.json"
        if spec_path.exists():
            return json.loads(spec_path.read_text())
        return None

    def get_cached_version(self, repo: Repository, version: str) -> dict | None:
        """Return the cached ``version.json`` for *version*, or ``None``."""
        version_path = self.env_cache_dir(repo, version) / "version.json"
        if version_path.exists():
            return json.loads(version_path.read_text())
        return None
