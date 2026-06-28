"""Tests for Rust Docker validation via the backend registry and grader.compute_f2p."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swebenchify.backends import get_backend
from swebenchify.grader import _parse_f2p_output_generic, compute_f2p, _F2P_PHASE_SEPARATOR
from swebenchify.models import RustEnvironmentSpec
from swebenchify.parsers import RustTestParser, normalize_rust_f2p
from swebenchify.sandbox import RustImageCache


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _rust_passing(tests: list[str]) -> str:
    lines = [f"test {t} ... ok" for t in tests]
    lines.append(f"\ntest result: ok. {len(tests)} passed; 0 failed; 0 ignored\n")
    return "\n".join(lines)


def _rust_failing(tests: list[str]) -> str:
    lines = [f"test {t} ... FAILED" for t in tests]
    lines.append(f"\ntest result: FAILED. 0 passed; {len(tests)} failed; 0 ignored\n")
    return "\n".join(lines)


def _rust_mixed(passing: list[str], failing: list[str]) -> str:
    lines = []
    for t in passing:
        lines.append(f"test {t} ... ok")
    for t in failing:
        lines.append(f"test {t} ... FAILED")
    status = "FAILED" if failing else "ok"
    lines.append(f"\ntest result: {status}. {len(passing)} passed; {len(failing)} failed; 0 ignored\n")
    return "\n".join(lines)


def _rust_compile_error() -> str:
    return (
        "error[E0433]: failed to resolve: use of undeclared crate or module `foo`\n"
        " --> src/main.rs:1:5\n"
        "  |\n"
        "1 | use foo::bar;\n"
        "  |     ^^^ use of undeclared crate or module `foo`\n"
        "\n"
        "error: aborting due to previous error\n"
    )


# ---------------------------------------------------------------------------
# Backend registration
# ---------------------------------------------------------------------------

class TestRustBackendRegistered:
    def test_backend_exists(self) -> None:
        backend = get_backend("rust")
        assert backend is not None

    def test_backend_name(self) -> None:
        backend = get_backend("rust")
        assert backend.name == "rust"

    def test_backend_parser_is_rust(self) -> None:
        backend = get_backend("rust")
        assert isinstance(backend.parser, RustTestParser)

    def test_backend_default_timeout(self) -> None:
        backend = get_backend("rust")
        assert backend.default_timeout == 600

    def test_backend_failure_grep(self) -> None:
        backend = get_backend("rust")
        assert backend.failure_grep == "FAILED"

    def test_backend_normalize_f2p(self) -> None:
        backend = get_backend("rust")
        assert backend.normalize_f2p is normalize_rust_f2p


# ---------------------------------------------------------------------------
# Dockerfile generation via backend
# ---------------------------------------------------------------------------

class TestRustMakeDockerfile:
    def test_contains_rust_base_image(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec(rust_version="1.84")
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "rust:1.84-slim" in df

    def test_contains_clone_and_checkout(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec()
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "owner/repo" in df
        assert "abc123" in df

    def test_copies_patches(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec()
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "test.patch" in df
        assert "gold.patch" in df

    def test_includes_system_deps(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec(system_dependencies=["libssl-dev", "pkg-config"])
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "libssl-dev" in df
        assert "pkg-config" in df

    def test_includes_features(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec(features="--all-features")
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "--all-features" in df

    def test_defaults_to_rust_latest(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec()
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "rust:latest" in df

    def test_uses_archive_fallback(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec()
        df = backend.make_dockerfile("owner/repo", "abc123", spec)
        assert "archive" in df


# ---------------------------------------------------------------------------
# Test command generation
# ---------------------------------------------------------------------------

class TestRustMakeTestCmd:
    def test_default_cargo_test(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec()
        assert backend.make_test_cmd(spec) == "cargo test"

    def test_custom_test_cmd(self) -> None:
        backend = get_backend("rust")
        spec = RustEnvironmentSpec(test_cmd="cargo test --workspace")
        assert backend.make_test_cmd(spec) == "cargo test --workspace"


# ---------------------------------------------------------------------------
# Generic F2P output parsing with Rust parser
# ---------------------------------------------------------------------------

class TestRustF2pOutputParsing:
    def _make_f2p_raw(self, pre_output: str, post_output: str, run: int = 1) -> str:
        return (
            f"{_F2P_PHASE_SEPARATOR}_RUN_{run}_PRE\n"
            f"{pre_output}\n"
            f"{_F2P_PHASE_SEPARATOR}_RUN_{run}_POST\n"
            f"{post_output}\n"
        )

    def test_valid_single_run(self) -> None:
        pre = _rust_mixed(passing=["tests::test_b"], failing=["tests::test_a"])
        post = _rust_passing(["tests::test_a", "tests::test_b"])
        raw = self._make_f2p_raw(pre, post)
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=1)
        assert result.status == "valid"
        assert "tests::test_a" in result.FAIL_TO_PASS
        assert "tests::test_b" in result.PASS_TO_PASS

    def test_compile_error_pre_fix(self) -> None:
        pre = _rust_compile_error()
        post = _rust_passing(["tests::test_a"])
        raw = self._make_f2p_raw(pre, post)
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=1)
        assert result.compiled is False

    def test_no_failing_tests(self) -> None:
        raw = "NO_FAILING_TESTS\n"
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=1)
        assert result.status == "invalid"
        assert result.FAIL_TO_PASS == []

    def test_patch_apply_failure(self) -> None:
        raw = "PATCH_APPLY_FAILED\n"
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=1)
        assert result.status == "error"

    def test_multi_run_quarantine(self) -> None:
        pre_both_fail = _rust_mixed(passing=[], failing=["tests::stable", "tests::flaky"])
        pre_flaky_passes = _rust_mixed(passing=["tests::flaky"], failing=["tests::stable"])
        post_both_pass = _rust_passing(["tests::stable", "tests::flaky"])

        run1 = self._make_f2p_raw(pre_both_fail, post_both_pass, run=1)
        run2 = self._make_f2p_raw(pre_flaky_passes, post_both_pass, run=2)

        raw = run1 + run2
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=2)
        assert result.n_runs == 2
        assert result.flake_count >= 1
        assert "tests::stable" in result.FAIL_TO_PASS

    def test_p2p_computed(self) -> None:
        pre = _rust_mixed(passing=["tests::passing"], failing=["tests::failing"])
        post = _rust_passing(["tests::passing", "tests::failing"])
        raw = self._make_f2p_raw(pre, post)
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=1)
        assert "tests::passing" in result.PASS_TO_PASS

    def test_no_flip_gives_invalid(self) -> None:
        output = _rust_failing(["tests::test_a"])
        raw = self._make_f2p_raw(output, output)
        result = _parse_f2p_output_generic(raw, parser=RustTestParser(), normalize=normalize_rust_f2p, n_runs=1)
        assert result.status == "invalid"
        assert result.FAIL_TO_PASS == []


# ---------------------------------------------------------------------------
# RustImageCache
# ---------------------------------------------------------------------------

class TestRustImageCache:
    def test_image_name_format(self, tmp_path: Path) -> None:
        cache = RustImageCache(tmp_path)
        name = cache.image_name("owner/repo", "abc123", "deadbeefcafe1234")
        assert name == "swebenchify-rust-owner__repo-deadbeefcafe"

    def test_image_name_different_repos(self, tmp_path: Path) -> None:
        cache = RustImageCache(tmp_path)
        name1 = cache.image_name("owner/repo-a", "abc", "hash1234567890ab")
        name2 = cache.image_name("owner/repo-b", "abc", "hash1234567890ab")
        assert name1 != name2

    def test_creates_cache_dir(self, tmp_path: Path) -> None:
        RustImageCache(tmp_path)
        assert (tmp_path / "rust-images").is_dir()


# ---------------------------------------------------------------------------
# compute_f2p with Rust env_spec
# ---------------------------------------------------------------------------

class TestComputeF2pRust:
    _FAKE_TEST_PATCH = "diff --git a/tests/pool_test.rs b/tests/pool_test.rs\n--- a/tests/pool_test.rs\n+++ b/tests/pool_test.rs\n"

    def test_no_docker_raises(self) -> None:
        spec = RustEnvironmentSpec(rust_version="1.84")
        with patch("swebenchify.grader._docker_available", return_value=False):
            with pytest.raises(RuntimeError, match="Docker is not available"):
                compute_f2p("owner/repo", "abc123", self._FAKE_TEST_PATCH, "gold", env_spec=spec)

    def test_no_test_files_returns_invalid(self) -> None:
        no_rs_patch = "diff --git a/README.md b/README.md\n"
        spec = RustEnvironmentSpec(rust_version="1.84")
        with patch("swebenchify.grader._docker_available", return_value=True):
            result = compute_f2p("owner/repo", "abc123", no_rs_patch, "gold", env_spec=spec)
        assert result.status == "invalid"
        assert ".rs" in result.error_message

    def test_build_failure_returns_error(self) -> None:
        spec = RustEnvironmentSpec(rust_version="1.84")
        with patch.multiple(
            "swebenchify.grader",
            _docker_available=MagicMock(return_value=True),
            _docker_build=MagicMock(return_value=(1, "build failed")),
        ):
            result = compute_f2p("owner/repo", "abc123", self._FAKE_TEST_PATCH, "gold", env_spec=spec)
        assert result.status == "error"
        assert result.compiled is False

    def test_timeout_returns_error(self) -> None:
        spec = RustEnvironmentSpec(rust_version="1.84")
        with patch.multiple(
            "swebenchify.grader",
            _docker_available=MagicMock(return_value=True),
            _docker_build=MagicMock(return_value=(0, "ok")),
            _docker_run=MagicMock(return_value=(-1, "TIMEOUT after 1200s")),
        ), patch("swebenchify.grader.subprocess.run"):
            result = compute_f2p("owner/repo", "abc123", self._FAKE_TEST_PATCH, "gold", env_spec=spec)
        assert result.status == "error"
        assert "timed out" in result.error_message

    def test_successful_run(self) -> None:
        spec = RustEnvironmentSpec(rust_version="1.84")
        pre = _rust_failing(["tests::test_a"])
        post = _rust_passing(["tests::test_a"])
        raw = (
            f"{_F2P_PHASE_SEPARATOR}_RUN_1_PRE\n{pre}\n"
            f"{_F2P_PHASE_SEPARATOR}_RUN_1_POST\n{post}\n"
        )
        with patch.multiple(
            "swebenchify.grader",
            _docker_available=MagicMock(return_value=True),
            _docker_build=MagicMock(return_value=(0, "ok")),
            _docker_run=MagicMock(return_value=(0, raw)),
        ), patch("swebenchify.grader.subprocess.run"):
            result = compute_f2p("owner/repo", "abc123", self._FAKE_TEST_PATCH, "gold", env_spec=spec)
        assert result.status == "valid"
        assert "tests::test_a" in result.FAIL_TO_PASS
