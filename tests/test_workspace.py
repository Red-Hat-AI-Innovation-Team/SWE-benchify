"""Tests for swebenchify.workspace -- WorkspaceManager path logic and caching.

These tests exercise path calculations and cached env spec reading.
Git operations (clone, worktree) are NOT tested here because they
require a real repository.
"""

from __future__ import annotations

import json
from pathlib import Path

from swebenchify.models import Repository
from swebenchify.workspace import WorkspaceManager


def _repo(name: str = "pallets/flask") -> Repository:
    return Repository(full_name=name)


class TestRepoDirPaths:
    """Test that path helpers return the correct directory structure."""

    def test_repo_dir(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        assert mgr.repo_dir(repo) == tmp_path / "pallets__flask"

    def test_repo_dir_nested_owner(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("my-org/my-repo")
        assert mgr.repo_dir(repo) == tmp_path / "my-org__my-repo"

    def test_bare_clone_path(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("django/django")
        expected = tmp_path / "django__django" / "repo.git"
        assert mgr.bare_clone_path(repo) == expected

    def test_env_cache_dir(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        expected = tmp_path / "pallets__flask" / "envs" / "2.3.1"
        assert mgr.env_cache_dir(repo, "2.3.1") == expected

    def test_env_cache_dir_different_versions(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        v1 = mgr.env_cache_dir(repo, "1.0")
        v2 = mgr.env_cache_dir(repo, "2.0")
        assert v1 != v2
        assert v1.name == "1.0"
        assert v2.name == "2.0"


class TestInstanceDir:
    """Test instance_dir slug extraction from instance_id."""

    def test_standard_instance_id(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        iid = "pallets__flask-4045"
        expected = tmp_path / "pallets__flask" / "instances" / iid
        assert mgr.instance_dir(iid) == expected

    def test_slug_extraction_splits_on_last_dash(self, tmp_path: Path) -> None:
        """instance_id with dashes in the slug should split on the last one."""
        mgr = WorkspaceManager(tmp_path)
        iid = "my-org__my-repo-123"
        expected = tmp_path / "my-org__my-repo" / "instances" / iid
        assert mgr.instance_dir(iid) == expected

    def test_numeric_pr_number(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        iid = "owner__repo-999"
        result = mgr.instance_dir(iid)
        assert result.name == iid
        assert result.parent.name == "instances"
        assert result.parent.parent.name == "owner__repo"


class TestCachedEnvSpec:
    """Test get_cached_env_spec reads from the filesystem cache."""

    def test_returns_none_when_no_cache(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        assert mgr.get_cached_env_spec(repo, "1.0") is None

    def test_returns_cached_dict(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        cache_dir = mgr.env_cache_dir(repo, "2.0")
        cache_dir.mkdir(parents=True)

        spec = {
            "language": "python",
            "language_version": "3.11",
            "package_manager": "pip",
            "install_cmd": "pip install -e .[dev]",
            "test_cmd": "python -m pytest -x",
            "pre_install": [],
            "system_dependencies": [],
        }
        (cache_dir / "env_spec.json").write_text(json.dumps(spec))

        result = mgr.get_cached_env_spec(repo, "2.0")
        assert result is not None
        assert result["language"] == "python"
        assert result["test_cmd"] == "python -m pytest -x"

    def test_different_version_not_cached(self, tmp_path: Path) -> None:
        """Cache for version 2.0 should not affect version 3.0."""
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        cache_dir = mgr.env_cache_dir(repo, "2.0")
        cache_dir.mkdir(parents=True)
        (cache_dir / "env_spec.json").write_text('{"language": "python"}')

        assert mgr.get_cached_env_spec(repo, "2.0") is not None
        assert mgr.get_cached_env_spec(repo, "3.0") is None


class TestCachedVersion:
    """Test get_cached_version reads version.json from cache."""

    def test_returns_none_when_no_cache(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        assert mgr.get_cached_version(repo, "1.0") is None

    def test_returns_cached_dict(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        repo = _repo("pallets/flask")
        cache_dir = mgr.env_cache_dir(repo, "2.0")
        cache_dir.mkdir(parents=True)

        ver = {"repo": "pallets/flask", "commit": "abc123", "version": "2.0"}
        (cache_dir / "version.json").write_text(json.dumps(ver))

        result = mgr.get_cached_version(repo, "2.0")
        assert result is not None
        assert result["version"] == "2.0"
        assert result["commit"] == "abc123"


class TestWorkspaceManagerInit:
    """Test WorkspaceManager initialization."""

    def test_root_is_path(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(tmp_path)
        assert isinstance(mgr.root, Path)
        assert mgr.root == tmp_path

    def test_root_from_string(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(str(tmp_path))
        assert isinstance(mgr.root, Path)
        assert mgr.root == tmp_path
