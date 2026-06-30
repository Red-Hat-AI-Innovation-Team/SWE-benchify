"""Tests for GoImageCache and GoDockerfile in swebenchify.sandbox.

Docker subprocess calls are mocked with unittest.mock.patch so these
tests run with no Docker daemon required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from swebenchify.models import GoEnvironmentSpec
from swebenchify.sandbox import GoDockerfile, GoImageCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**overrides) -> GoEnvironmentSpec:
    defaults = dict(
        go_version="1.22",
        build_cmd="make build",
        test_cmd="go test ./pkg/...",
        module_mode="modules",
        goflags="",
        system_dependencies=[],
    )
    defaults.update(overrides)
    s = GoEnvironmentSpec(**defaults)
    from swebenchify.models import compute_env_spec_hash
    s.env_spec_hash = compute_env_spec_hash(s)
    return s


# ---------------------------------------------------------------------------
# GoDockerfile
# ---------------------------------------------------------------------------

class TestGoDockerfile:
    def test_base_image_uses_go_version(self) -> None:
        spec = _spec(go_version="1.22")
        df = GoDockerfile.generate(spec)
        assert "FROM golang:1.22" in df

    def test_default_go_version_fallback(self) -> None:
        spec = _spec(go_version="")
        df = GoDockerfile.generate(spec)
        assert "FROM golang:" in df  # falls back to a valid version

    def test_workdir_is_repo(self) -> None:
        df = GoDockerfile.generate(_spec())
        assert "WORKDIR /repo" in df

    def test_vendored_has_comment(self) -> None:
        spec = _spec(module_mode="vendored")
        df = GoDockerfile.generate(spec)
        assert "vendor" in df.lower()

    def test_modules_no_copy_vendor(self) -> None:
        spec = _spec(module_mode="modules")
        df = GoDockerfile.generate(spec)
        assert "COPY vendor" not in df

    def test_system_dependencies_in_apt_get(self) -> None:
        spec = _spec(system_dependencies=["git", "make"])
        df = GoDockerfile.generate(spec)
        assert "apt-get" in df
        assert "git" in df
        assert "make" in df

    def test_no_system_deps_no_apt_get(self) -> None:
        spec = _spec(system_dependencies=[])
        df = GoDockerfile.generate(spec)
        assert "apt-get" not in df

    def test_goflags_set_as_env(self) -> None:
        spec = _spec(goflags="-mod=vendor")
        df = GoDockerfile.generate(spec)
        assert "GOFLAGS" in df
        assert "-mod=vendor" in df

    def test_empty_goflags_no_env_line(self) -> None:
        spec = _spec(goflags="")
        df = GoDockerfile.generate(spec)
        assert "GOFLAGS" not in df

    def test_dockerfile_is_string(self) -> None:
        df = GoDockerfile.generate(_spec())
        assert isinstance(df, str)
        assert df.strip()


# ---------------------------------------------------------------------------
# GoImageCache.image_name
# ---------------------------------------------------------------------------

class TestGoImageCacheImageName:
    def test_name_stable(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()
        n1 = cache.image_name("kubernetes/kubectl", "abc123", spec.env_spec_hash)
        n2 = cache.image_name("kubernetes/kubectl", "abc123", spec.env_spec_hash)
        assert n1 == n2

    def test_name_changes_with_hash(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec_a = _spec(go_version="1.21")
        spec_b = _spec(go_version="1.22")
        n_a = cache.image_name("kubernetes/kubectl", "abc", spec_a.env_spec_hash)
        n_b = cache.image_name("kubernetes/kubectl", "abc", spec_b.env_spec_hash)
        assert n_a != n_b

    def test_name_contains_slug(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        name = cache.image_name("kubernetes/kubectl", "abc", "hash12345678")
        assert "kubectl" in name

    def test_name_lowercased(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        name = cache.image_name("My/Repo", "abc", "hash12345678")
        assert name == name.lower()

    def test_name_uses_hash_prefix(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        full_hash = "abcdef1234567890"
        name = cache.image_name("kubernetes/kubectl", "abc", full_hash)
        assert full_hash[:12] in name


# ---------------------------------------------------------------------------
# GoImageCache.is_cached
# ---------------------------------------------------------------------------

class TestGoImageCacheIsCached:
    def test_is_cached_true_when_inspect_succeeds(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        with patch("swebenchify.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert cache.is_cached("some-image") is True

    def test_is_cached_false_when_inspect_fails(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        with patch("swebenchify.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert cache.is_cached("some-image") is False

    def test_is_cached_false_when_docker_missing(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        with patch("swebenchify.sandbox.subprocess.run", side_effect=FileNotFoundError):
            assert cache.is_cached("some-image") is False


# ---------------------------------------------------------------------------
# GoImageCache.build
# ---------------------------------------------------------------------------

class TestGoImageCacheBuild:
    def test_build_returns_true_on_success(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()
        with patch("swebenchify.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert cache.build(tmp_path, spec, "test-image") is True

    def test_build_returns_false_on_failure(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()
        with patch("swebenchify.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            assert cache.build(tmp_path, spec, "test-image") is False

    def test_build_calls_docker_build(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()
        with patch("swebenchify.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            cache.build(tmp_path, spec, "test-image")
            args = mock_run.call_args[0][0]
            assert args[0] == "docker"
            assert "build" in args
            assert "test-image" in args


# ---------------------------------------------------------------------------
# GoImageCache.get_or_build
# ---------------------------------------------------------------------------

class TestGoImageCacheGetOrBuild:
    def test_uses_cache_when_hit(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()

        with patch.object(cache, "is_cached", return_value=True), \
             patch.object(cache, "build") as mock_build:
            result = cache.get_or_build("kubernetes/kubectl", "abc", spec, tmp_path)
            assert result is not None
            mock_build.assert_not_called()

    def test_builds_on_cache_miss(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()

        with patch.object(cache, "is_cached", return_value=False), \
             patch.object(cache, "build", return_value=True) as mock_build:
            result = cache.get_or_build("kubernetes/kubectl", "abc", spec, tmp_path)
            assert result is not None
            mock_build.assert_called_once()

    def test_returns_none_when_build_fails(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()

        with patch.object(cache, "is_cached", return_value=False), \
             patch.object(cache, "build", return_value=False):
            result = cache.get_or_build("kubernetes/kubectl", "abc", spec, tmp_path)
            assert result is None

    def test_force_rebuild_ignores_cache(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()

        with patch.object(cache, "is_cached", return_value=True), \
             patch.object(cache, "build", return_value=True) as mock_build:
            cache.get_or_build("kubernetes/kubectl", "abc", spec, tmp_path, force_rebuild=True)
            mock_build.assert_called_once()

    def test_returned_name_is_consistent(self, tmp_path: Path) -> None:
        cache = GoImageCache(tmp_path)
        spec = _spec()

        with patch.object(cache, "is_cached", return_value=True):
            name1 = cache.get_or_build("kubernetes/kubectl", "abc", spec, tmp_path)
            name2 = cache.get_or_build("kubernetes/kubectl", "abc", spec, tmp_path)
            assert name1 == name2


# ---------------------------------------------------------------------------
# TaskInstance image_name field
# ---------------------------------------------------------------------------

class TestTaskInstanceImageName:
    def test_image_name_defaults_none(self) -> None:
        from swebenchify.models import TaskInstance
        inst = TaskInstance(
            repo="kubernetes/kubectl",
            instance_id="kubernetes__kubectl-1",
            base_commit="abc",
            patch="",
            test_patch="",
            problem_statement="problem",
            hints_text="",
            created_at="2024-01-01T00:00:00Z",
            version="1.22-abc",
            FAIL_TO_PASS="[]",
            PASS_TO_PASS="[]",
        )
        assert inst.image_name is None

    def test_image_name_can_be_set(self) -> None:
        from swebenchify.models import TaskInstance
        inst = TaskInstance(
            repo="kubernetes/kubectl",
            instance_id="kubernetes__kubectl-1",
            base_commit="abc",
            patch="",
            test_patch="",
            problem_statement="problem",
            hints_text="",
            created_at="2024-01-01T00:00:00Z",
            version="1.22-abc",
            FAIL_TO_PASS="[]",
            PASS_TO_PASS="[]",
            image_name="swebenchify-go-kubernetes__kubectl-abc123",
        )
        assert inst.image_name == "swebenchify-go-kubernetes__kubectl-abc123"
