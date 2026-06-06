"""Tests for swebenchify.grader — grade() API.

All Docker calls are mocked so no Docker daemon is required.
The gold-patch acceptance criterion (resolves=True) and the
compiled=False distinct-outcome criterion are verified with
synthetic go test -json fixture output.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from swebenchify.grader import (
    GradeResult,
    __version__,
    _affected_packages,
    _compute_f2p_p2p,
    _decode_list,
    _extract_section,
    _F2P_PHASE_SEPARATOR,
    _make_dockerfile,
    _make_f2p_dockerfile,
    _make_f2p_run_script,
    _make_run_script,
    _parse_f2p_output,
    compute_f2p,
    grade,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _event(**kwargs) -> str:
    return json.dumps(kwargs)


def _passing_output(pkg: str, test: str) -> str:
    return "\n".join([
        _event(Action="run", Package=pkg, Test=test),
        _event(Action="pass", Package=pkg, Test=test, Elapsed=0.001),
        _event(Action="pass", Package=pkg, Elapsed=0.01),
    ])


def _failing_output(pkg: str, test: str) -> str:
    return "\n".join([
        _event(Action="run", Package=pkg, Test=test),
        _event(Action="fail", Package=pkg, Test=test, Elapsed=0.001),
        _event(Action="fail", Package=pkg, Elapsed=0.01),
    ])


def _compile_error_output(pkg: str) -> str:
    return "\n".join([
        _event(Action="output", Package=pkg, Output="# " + pkg + "\n"),
        _event(Action="output", Package=pkg, Output="./foo.go:5: undefined: Bar\n"),
        _event(Action="build-fail", Package=pkg),
        _event(Action="fail", Package=pkg, Elapsed=0.0),
    ])


def _mixed_output(pkg: str, passing: list[str], failing: list[str]) -> str:
    lines = []
    for t in passing:
        lines.extend([
            _event(Action="run", Package=pkg, Test=t),
            _event(Action="pass", Package=pkg, Test=t, Elapsed=0),
        ])
    for t in failing:
        lines.extend([
            _event(Action="run", Package=pkg, Test=t),
            _event(Action="fail", Package=pkg, Test=t, Elapsed=0),
        ])
    lines.append(_event(Action="fail" if failing else "pass", Package=pkg, Elapsed=0.01))
    return "\n".join(lines)


# A minimal fake instance dict matching the grade() contract
_INSTANCE = {
    "repo": "etcd-io/etcd",
    "base_commit": "abc123def456",
    "test_patch": (
        "diff --git a/server/etcdserver/api/etcdhttp/health_test.go "
        "b/server/etcdserver/api/etcdhttp/health_test.go\n"
        "--- a/server/etcdserver/api/etcdhttp/health_test.go\n"
        "+++ b/server/etcdserver/api/etcdhttp/health_test.go\n"
        "@@ -1,2 +1,3 @@\n package etcdhttp\n+// new test\n"
    ),
    "FAIL_TO_PASS": json.dumps(["TestHTTPSubPath", "TestLearnerReadyCheck"]),
    "PASS_TO_PASS": json.dumps(["TestServeHealth"]),
}

_PKG = "go.etcd.io/etcd/server/v3/etcdserver/api/etcdhttp"

# Gold patch output: all recorded F2P pass AND all P2P pass
_GOLD_OUTPUT = _mixed_output(
    pkg=_PKG,
    passing=["TestHTTPSubPath", "TestLearnerReadyCheck", "TestServeHealth"],
    failing=[],
)

# Bad patch: F2P tests still fail
_BAD_OUTPUT = _mixed_output(
    pkg=_PKG,
    passing=["TestServeHealth"],
    failing=["TestHTTPSubPath", "TestLearnerReadyCheck"],
)

# Partial patch: one F2P passes but not the other
_PARTIAL_OUTPUT = _mixed_output(
    pkg=_PKG,
    passing=["TestHTTPSubPath", "TestServeHealth"],
    failing=["TestLearnerReadyCheck"],
)

# Regression patch: F2P pass but P2P breaks
_REGRESSION_OUTPUT = _mixed_output(
    pkg=_PKG,
    passing=["TestHTTPSubPath", "TestLearnerReadyCheck"],
    failing=["TestServeHealth"],   # P2P test now fails!
)


def _mock_grade(raw_output: str, build_rc: int = 0):
    """Context manager: patches Docker calls to return synthetic output."""
    return patch.multiple(
        "swebenchify.grader",
        _docker_available=MagicMock(return_value=True),
        _docker_build=MagicMock(return_value=(build_rc, "build log")),
        _docker_run=MagicMock(return_value=(0, raw_output)),
    )


# ---------------------------------------------------------------------------
# Core grade() behaviour
# ---------------------------------------------------------------------------

class TestGradeResolved:
    def test_gold_patch_resolves(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "diff --git a/fix.go ...")
        assert result.resolved is True

    def test_bad_patch_not_resolved(self) -> None:
        with _mock_grade(_BAD_OUTPUT):
            result = grade(_INSTANCE, "diff --git a/bad.go ...")
        assert result.resolved is False

    def test_partial_patch_not_resolved(self) -> None:
        with _mock_grade(_PARTIAL_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert result.resolved is False

    def test_regression_not_resolved(self) -> None:
        """A patch that breaks a P2P test must not be marked resolved."""
        with _mock_grade(_REGRESSION_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert result.resolved is False


class TestGradeCompiledFlag:
    def test_compile_error_gives_resolved_false(self) -> None:
        with _mock_grade(_compile_error_output(_PKG)):
            result = grade(_INSTANCE, "patch")
        assert result.compiled is False
        assert result.resolved is False

    def test_compile_error_is_distinct_from_test_failure(self) -> None:
        """compiled=False is a distinct outcome — the F2P tests didn't even run."""
        with _mock_grade(_compile_error_output(_PKG)):
            result = grade(_INSTANCE, "patch")
        assert result.compiled is False
        # All F2P/P2P test results should be "missing" (never ran)
        for tr in result.f2p:
            assert tr.status == "missing"
        for tr in result.p2p:
            assert tr.status == "missing"

    def test_test_failure_leaves_compiled_true(self) -> None:
        """A test failure is NOT a compile error."""
        with _mock_grade(_BAD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert result.compiled is True


class TestGradePerTestResults:
    def test_f2p_results_include_all_recorded_tests(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        f2p_ids = {r.test_id for r in result.f2p}
        assert "TestHTTPSubPath" in f2p_ids
        assert "TestLearnerReadyCheck" in f2p_ids

    def test_p2p_results_include_all_recorded_tests(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        p2p_ids = {r.test_id for r in result.p2p}
        assert "TestServeHealth" in p2p_ids

    def test_f2p_status_passed_on_gold(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        for tr in result.f2p:
            assert tr.status == "passed", f"{tr.test_id} should be passed"

    def test_f2p_status_failed_on_bad_patch(self) -> None:
        with _mock_grade(_BAD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        statuses = {tr.test_id: tr.status for tr in result.f2p}
        assert statuses["TestHTTPSubPath"] == "failed"
        assert statuses["TestLearnerReadyCheck"] == "failed"

    def test_missing_test_status(self) -> None:
        # Output has none of the recorded tests (e.g., wrong package scoped)
        empty_output = _event(Action="pass", Package=_PKG, Elapsed=0.1)
        with _mock_grade(empty_output):
            result = grade(_INSTANCE, "patch")
        for tr in result.f2p + result.p2p:
            assert tr.status == "missing"


class TestGradeTelemetry:
    def test_telemetry_contains_grader_version(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert result.telemetry["grader_version"] == __version__

    def test_telemetry_contains_elapsed_s(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert "elapsed_s" in result.telemetry
        assert isinstance(result.telemetry["elapsed_s"], float)

    def test_telemetry_contains_pkg_scope(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert "pkg_scope" in result.telemetry

    def test_telemetry_contains_f2p_p2p_pass(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(_INSTANCE, "patch")
        assert result.telemetry["f2p_pass"] is True
        assert result.telemetry["p2p_pass"] is True


class TestGradeInputFormats:
    def test_accepts_dict_instance(self) -> None:
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(dict(_INSTANCE), "patch")
        assert isinstance(result, GradeResult)

    def test_accepts_dataclass_instance(self) -> None:
        from swebenchify.models import TaskInstance
        inst = TaskInstance(
            repo="etcd-io/etcd",
            instance_id="etcd-io__etcd-19086",
            base_commit="abc123",
            patch="diff",
            test_patch=_INSTANCE["test_patch"],
            problem_statement="fix",
            hints_text="",
            created_at="2024-01-01T00:00:00Z",
            version="1.23",
            FAIL_TO_PASS=_INSTANCE["FAIL_TO_PASS"],
            PASS_TO_PASS=_INSTANCE["PASS_TO_PASS"],
        )
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(inst, "patch")
        assert isinstance(result, GradeResult)

    def test_accepts_list_f2p_p2p(self) -> None:
        inst = dict(_INSTANCE)
        inst["FAIL_TO_PASS"] = ["TestHTTPSubPath", "TestLearnerReadyCheck"]
        inst["PASS_TO_PASS"] = ["TestServeHealth"]
        with _mock_grade(_GOLD_OUTPUT):
            result = grade(inst, "patch")
        assert isinstance(result, GradeResult)

    def test_empty_candidate_patch(self) -> None:
        with _mock_grade(_BAD_OUTPUT):
            result = grade(_INSTANCE, "")
        assert isinstance(result, GradeResult)
        assert result.resolved is False

    def test_no_docker_raises_runtime_error(self) -> None:
        with patch("swebenchify.grader._docker_available", return_value=False):
            with pytest.raises(RuntimeError, match="Docker is not available"):
                grade(_INSTANCE, "patch")


class TestGradeBuildFailure:
    def test_build_failure_returns_unresolved(self) -> None:
        with _mock_grade("", build_rc=1):
            result = grade(_INSTANCE, "patch")
        assert result.resolved is False
        assert result.compiled is False

    def test_build_failure_telemetry(self) -> None:
        with _mock_grade("", build_rc=1):
            result = grade(_INSTANCE, "patch")
        assert result.telemetry["build_rc"] == 1
        assert "error" in result.telemetry


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestDecodeList:
    def test_json_encoded_string(self) -> None:
        assert _decode_list('["TestFoo", "TestBar"]') == ["TestFoo", "TestBar"]

    def test_plain_list(self) -> None:
        assert _decode_list(["TestFoo"]) == ["TestFoo"]

    def test_empty_string(self) -> None:
        assert _decode_list("[]") == []

    def test_none(self) -> None:
        assert _decode_list(None) == []


class TestAffectedPackages:
    def test_extracts_package_from_diff(self) -> None:
        patch = (
            "diff --git a/server/etcdhttp/health_test.go "
            "b/server/etcdhttp/health_test.go\n"
        )
        pkgs = _affected_packages(patch)
        assert any("server" in p for p in pkgs)

    def test_empty_patch_returns_all(self) -> None:
        assert _affected_packages("") == ["./..."]

    def test_root_level_file(self) -> None:
        patch = "diff --git a/main.go b/main.go\n"
        pkgs = _affected_packages(patch)
        assert pkgs  # non-empty


class TestMakeDockerfile:
    def test_contains_base_image(self) -> None:
        df = _make_dockerfile("golang:1.23", "etcd-io/etcd", "abc123")
        assert "golang:1.23" in df

    def test_contains_clone_and_checkout(self) -> None:
        df = _make_dockerfile("golang:latest", "etcd-io/etcd", "abc123")
        assert "etcd-io/etcd" in df
        assert "abc123" in df

    def test_copies_patches(self) -> None:
        df = _make_dockerfile("golang:latest", "etcd-io/etcd", "abc123")
        assert "test.patch" in df
        assert "candidate.patch" in df


class TestMakeRunScript:
    def test_applies_both_patches(self) -> None:
        script = _make_run_script("./server/...")
        assert "test.patch" in script
        assert "candidate.patch" in script

    def test_runs_go_test_json(self) -> None:
        script = _make_run_script("./server/...")
        assert "go test -json" in script

    def test_includes_pkg_scope(self) -> None:
        script = _make_run_script("./server/etcdhttp")
        assert "./server/etcdhttp" in script


class TestVersion:
    def test_version_is_string(self) -> None:
        assert isinstance(__version__, str)

    def test_version_format(self) -> None:
        # Should be semver-ish
        parts = __version__.split(".")
        assert len(parts) >= 2
        assert all(p.isdigit() for p in parts)


# ---------------------------------------------------------------------------
# compute_f2p() and helpers
# ---------------------------------------------------------------------------


class TestComputeF2PP2P:
    def test_basic_f2p(self) -> None:
        pre = {"pkg.TestA": "failed", "pkg.TestB": "passed"}
        post = {"pkg.TestA": "passed", "pkg.TestB": "passed"}
        f2p, p2p = _compute_f2p_p2p(pre, post)
        assert "pkg.TestA" in f2p
        assert "pkg.TestB" in p2p

    def test_empty_inputs(self) -> None:
        f2p, p2p = _compute_f2p_p2p({}, {})
        assert f2p == []
        assert p2p == []

    def test_no_flip(self) -> None:
        pre = {"pkg.TestA": "failed"}
        post = {"pkg.TestA": "failed"}
        f2p, _ = _compute_f2p_p2p(pre, post)
        assert f2p == []

    def test_sorted_output(self) -> None:
        pre = {"pkg.TestZ": "failed", "pkg.TestA": "failed"}
        post = {"pkg.TestZ": "passed", "pkg.TestA": "passed"}
        f2p, _ = _compute_f2p_p2p(pre, post)
        assert f2p == sorted(f2p)


class TestMakeF2PDockerfile:
    def test_contains_base_image(self) -> None:
        df = _make_f2p_dockerfile("golang:1.23", "etcd-io/etcd", "abc123")
        assert "golang:1.23" in df

    def test_copies_gold_patch(self) -> None:
        df = _make_f2p_dockerfile("golang:latest", "etcd-io/etcd", "abc123")
        assert "gold.patch" in df
        assert "candidate.patch" not in df

    def test_uses_env_spec_go_version(self) -> None:
        from swebenchify.models import GoEnvironmentSpec
        spec = GoEnvironmentSpec(go_version="1.22", test_cmd="go test ./...")
        df = _make_f2p_dockerfile("golang:latest", "etcd-io/etcd", "abc123", spec)
        assert "golang:1.22" in df

    def test_includes_system_deps(self) -> None:
        from swebenchify.models import GoEnvironmentSpec
        spec = GoEnvironmentSpec(
            go_version="1.22", test_cmd="go test ./...",
            system_dependencies=["git", "make"],
        )
        df = _make_f2p_dockerfile("golang:latest", "etcd-io/etcd", "abc123", spec)
        assert "git make" in df

    def test_includes_goflags(self) -> None:
        from swebenchify.models import GoEnvironmentSpec
        spec = GoEnvironmentSpec(
            go_version="1.22", test_cmd="go test ./...",
            goflags="-mod=vendor",
        )
        df = _make_f2p_dockerfile("golang:latest", "etcd-io/etcd", "abc123", spec)
        assert "-mod=vendor" in df


class TestMakeF2PRunScript:
    def test_single_run_has_pre_and_post_markers(self) -> None:
        script = _make_f2p_run_script("./...", n_runs=1)
        assert f"{_F2P_PHASE_SEPARATOR}_RUN_1_PRE" in script
        assert f"{_F2P_PHASE_SEPARATOR}_RUN_1_POST" in script

    def test_three_runs_has_all_markers(self) -> None:
        script = _make_f2p_run_script("./...", n_runs=3)
        for i in range(1, 4):
            assert f"{_F2P_PHASE_SEPARATOR}_RUN_{i}_PRE" in script
            assert f"{_F2P_PHASE_SEPARATOR}_RUN_{i}_POST" in script

    def test_applies_test_and_gold_patches(self) -> None:
        script = _make_f2p_run_script("./...", n_runs=1)
        assert "test.patch" in script
        assert "gold.patch" in script

    def test_resets_between_runs(self) -> None:
        script = _make_f2p_run_script("./...", n_runs=2)
        assert "git checkout -- ." in script
        assert "git clean" in script


class TestExtractSection:
    def test_extracts_between_markers(self) -> None:
        text = "before\n===START===\ndata line 1\ndata line 2\n===END===\nafter"
        result = _extract_section(text, "===START===", "===END===")
        assert "data line 1" in result
        assert "data line 2" in result
        assert "before" not in result
        assert "after" not in result

    def test_extracts_to_end_when_no_end_marker(self) -> None:
        text = "before\n===START===\ndata\n"
        result = _extract_section(text, "===START===", "===MISSING===")
        assert "data" in result

    def test_returns_empty_when_no_start_marker(self) -> None:
        result = _extract_section("just text", "===MISSING===", "===END===")
        assert result == ""


class TestParseF2POutput:
    def _make_f2p_raw(self, pre_output: str, post_output: str, run: int = 1) -> str:
        return (
            f"{_F2P_PHASE_SEPARATOR}_RUN_{run}_PRE\n"
            f"{pre_output}\n"
            f"{_F2P_PHASE_SEPARATOR}_RUN_{run}_POST\n"
            f"{post_output}\n"
        )

    def test_basic_f2p_computation(self) -> None:
        pre = _failing_output(_PKG, "TestHTTPSubPath")
        post = _passing_output(_PKG, "TestHTTPSubPath")
        raw = self._make_f2p_raw(pre, post)
        result = _parse_f2p_output(raw, n_runs=1)
        assert result.status == "valid"
        assert len(result.FAIL_TO_PASS) > 0

    def test_no_flip_gives_invalid(self) -> None:
        output = _failing_output(_PKG, "TestHTTPSubPath")
        raw = self._make_f2p_raw(output, output)
        result = _parse_f2p_output(raw, n_runs=1)
        assert result.status == "invalid"
        assert result.FAIL_TO_PASS == []

    def test_p2p_computed(self) -> None:
        pre = _mixed_output(_PKG, passing=["TestServeHealth"], failing=["TestHTTPSubPath"])
        post = _mixed_output(_PKG, passing=["TestServeHealth", "TestHTTPSubPath"], failing=[])
        raw = self._make_f2p_raw(pre, post)
        result = _parse_f2p_output(raw, n_runs=1)
        assert len(result.PASS_TO_PASS) > 0

    def test_patch_apply_failure(self) -> None:
        raw = "PATCH_APPLY_FAILED\n"
        result = _parse_f2p_output(raw, n_runs=1)
        assert result.status == "error"

    def test_multi_run_quarantine(self) -> None:
        pre_flaky_fail = _mixed_output(_PKG, passing=[], failing=["TestStable", "TestFlaky"])
        pre_flaky_pass = _mixed_output(_PKG, passing=["TestFlaky"], failing=["TestStable"])
        post_both = _mixed_output(_PKG, passing=["TestStable", "TestFlaky"], failing=[])

        # Run 1: both TestStable and TestFlaky in F2P
        run1 = self._make_f2p_raw(pre_flaky_fail, post_both, run=1)
        # Run 2: only TestStable in F2P (TestFlaky passes pre-fix)
        run2 = self._make_f2p_raw(pre_flaky_pass, post_both, run=2)

        raw = run1 + run2
        result = _parse_f2p_output(raw, n_runs=2)
        assert result.n_runs == 2
        assert result.flake_count >= 1

    def test_compile_error_detected(self) -> None:
        pre = _compile_error_output(_PKG)
        post = _passing_output(_PKG, "TestHTTPSubPath")
        raw = self._make_f2p_raw(pre, post)
        result = _parse_f2p_output(raw, n_runs=1)
        assert result.compiled is False


class TestComputeF2PFunction:
    _FAKE_TEST_PATCH = "diff --git a/pkg/foo_test.go b/pkg/foo_test.go\n--- a/pkg/foo_test.go\n+++ b/pkg/foo_test.go\n"

    def test_no_docker_raises(self) -> None:
        with patch("swebenchify.grader._docker_available", return_value=False):
            with pytest.raises(RuntimeError, match="Docker is not available"):
                compute_f2p("etcd-io/etcd", "abc123", self._FAKE_TEST_PATCH, "gold")

    def test_build_failure_returns_error(self) -> None:
        with patch.multiple(
            "swebenchify.grader",
            _docker_available=MagicMock(return_value=True),
            _docker_build=MagicMock(return_value=(1, "build failed")),
        ):
            result = compute_f2p("etcd-io/etcd", "abc123", self._FAKE_TEST_PATCH, "gold")
        assert result.status == "error"
        assert result.compiled is False

    def test_timeout_returns_error(self) -> None:
        with patch.multiple(
            "swebenchify.grader",
            _docker_available=MagicMock(return_value=True),
            _docker_build=MagicMock(return_value=(0, "ok")),
            _docker_run=MagicMock(return_value=(-1, "TIMEOUT after 600s")),
        ):
            result = compute_f2p("etcd-io/etcd", "abc123", self._FAKE_TEST_PATCH, "gold")
        assert result.status == "error"
        assert "timed out" in result.error_message

    def test_successful_run(self) -> None:
        pre = _failing_output(_PKG, "TestHTTPSubPath")
        post = _passing_output(_PKG, "TestHTTPSubPath")
        raw = (
            f"{_F2P_PHASE_SEPARATOR}_RUN_1_PRE\n{pre}\n"
            f"{_F2P_PHASE_SEPARATOR}_RUN_1_POST\n{post}\n"
        )
        with patch.multiple(
            "swebenchify.grader",
            _docker_available=MagicMock(return_value=True),
            _docker_build=MagicMock(return_value=(0, "ok")),
            _docker_run=MagicMock(return_value=(0, raw)),
        ):
            result = compute_f2p("etcd-io/etcd", "abc123", self._FAKE_TEST_PATCH, "gold")
        assert result.status == "valid"
        assert len(result.FAIL_TO_PASS) > 0
