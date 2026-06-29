"""Go conformance tests (producer-only definition).

These tests verify the four conformance categories defined in the engineering
plan §2 and issue #44 — using only synthetic fixtures with no live Docker,
no network access, and no agent calls.

Category 1 — Mechanical stage: hunk classification
    Verify that _test.go files and testdata/ directories never appear in the
    gold patch; all code files stay in the gold patch.

Category 2 — Deterministic parser round-trip
    Verify that GoJSONParser produces identical results across repeated calls
    with the same input, and correctly detects compile errors.

Category 3 — Spec-generation schema
    Verify GoEnvironmentSpec construction, env_spec_hash properties, and
    GoSpecRegistry persistence.

Category 4 — Schema validity
    Verify that TaskInstance with Go-specific fields serialises correctly
    and that Python consumers can load Go JSONL without errors.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import asdict
from pathlib import Path

import pytest

from swebenchify.extractor import is_test_file, split_patch
from swebenchify.models import (
    GoEnvironmentSpec,
    TaskInstance,
    ValidationResult,
    compute_env_spec_hash,
)
from swebenchify.parsers import GoJSONParser

# ---------------------------------------------------------------------------
# Fixtures — synthetic go test -json output
# ---------------------------------------------------------------------------

def _event(**kwargs) -> str:
    return json.dumps(kwargs)


_KUBECTL_DIFF = textwrap.dedent("""\
    diff --git a/pkg/cmd/run.go b/pkg/cmd/run.go
    --- a/pkg/cmd/run.go
    +++ b/pkg/cmd/run.go
    @@ -1,2 +1,3 @@
     package cmd
    +// fixed
     func Run() {}
    diff --git a/pkg/cmd/run_test.go b/pkg/cmd/run_test.go
    --- a/pkg/cmd/run_test.go
    +++ b/pkg/cmd/run_test.go
    @@ -1,2 +1,3 @@
     package cmd
    +// new test
     func TestRun(t *testing.T) {}
""")

_PASSING_OUTPUT = "\n".join([
    _event(Action="run", Package="github.com/foo/bar", Test="TestA"),
    _event(Action="output", Package="github.com/foo/bar", Test="TestA", Output="=== RUN TestA\n"),
    _event(Action="pass", Package="github.com/foo/bar", Test="TestA", Elapsed=0.001),
    _event(Action="pass", Package="github.com/foo/bar", Elapsed=0.005),
])

_FAILING_OUTPUT = "\n".join([
    _event(Action="run", Package="github.com/foo/bar", Test="TestA"),
    _event(Action="output", Package="github.com/foo/bar", Test="TestA", Output="--- FAIL: TestA\n"),
    _event(Action="fail", Package="github.com/foo/bar", Test="TestA", Elapsed=0.001),
    _event(Action="fail", Package="github.com/foo/bar", Elapsed=0.005),
])

_COMPILE_ERROR_OUTPUT = "\n".join([
    _event(Action="output", Package="github.com/foo/bar", Output="# github.com/foo/bar\n"),
    _event(Action="output", Package="github.com/foo/bar", Output="./run.go:5:5: undefined: Foo\n"),
    _event(Action="build-fail", Package="github.com/foo/bar"),
    _event(Action="fail", Package="github.com/foo/bar", Elapsed=0.0),
])


# ---------------------------------------------------------------------------
# Category 1: Mechanical stage — hunk classification
# ---------------------------------------------------------------------------

class TestConformanceMechanicalHunkClassification:
    def test_no_test_hunk_in_gold_patch(self) -> None:
        """_test.go files must not appear in the gold patch."""
        gold, test = split_patch(_KUBECTL_DIFF)
        assert gold is not None
        assert "_test.go" not in gold

    def test_test_hunk_in_test_patch(self) -> None:
        """_test.go files must appear in the test patch."""
        gold, test = split_patch(_KUBECTL_DIFF)
        assert test is not None
        assert "run_test.go" in test

    def test_testdata_excluded_from_gold(self) -> None:
        """Files under testdata/ are classified as test files — must not go to gold."""
        # Verified via is_test_file directly; the split_patch fixture uses run_test.go
        assert is_test_file("pkg/cmd/testdata/golden.json") is True
        assert is_test_file("cmd/kubectl/testdata/golden.yaml") is True

    def test_testdata_in_test_patch(self) -> None:
        """Synthetic split: testdata file classified as test."""
        import textwrap as tw
        td_diff = tw.dedent("""\
            diff --git a/pkg/cmd/testdata/golden.json b/pkg/cmd/testdata/golden.json
            --- /dev/null
            +++ b/pkg/cmd/testdata/golden.json
            @@ -0,0 +1 @@
            +{}
        """)
        gold, test = split_patch(td_diff)
        assert gold is None
        assert test is not None
        assert "testdata" in test

    def test_source_file_in_gold_patch(self) -> None:
        """Production Go source files must be in the gold patch."""
        gold, test = split_patch(_KUBECTL_DIFF)
        assert gold is not None
        assert "run.go" in gold

    def test_is_test_file_go_test_suffix(self) -> None:
        assert is_test_file("pkg/cmd/run_test.go") is True

    def test_is_test_file_go_source_not_test(self) -> None:
        assert is_test_file("pkg/cmd/run.go") is False

    def test_is_test_file_testdata_dir(self) -> None:
        assert is_test_file("pkg/cmd/testdata/golden.json") is True

    def test_is_test_file_no_false_positive_on_contest(self) -> None:
        assert is_test_file("internal/contest.go") is False

    def test_is_test_file_no_false_positive_on_latest(self) -> None:
        assert is_test_file("staging/latest.go") is False

    def test_split_deterministic(self) -> None:
        """split_patch must return the same result on repeated calls."""
        results = [split_patch(_KUBECTL_DIFF) for _ in range(5)]
        golds = [r[0] for r in results]
        tests = [r[1] for r in results]
        assert all(g == golds[0] for g in golds)
        assert all(t == tests[0] for t in tests)


# ---------------------------------------------------------------------------
# Category 2: Deterministic parser round-trip
# ---------------------------------------------------------------------------

class TestConformanceDeterministicParser:
    def test_parser_deterministic_passing(self) -> None:
        """Same passing output → identical ParseResult across 10 calls."""
        parser = GoJSONParser()
        results = [parser.parse(_PASSING_OUTPUT) for _ in range(10)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_parser_deterministic_failing(self) -> None:
        """Same failing output → identical ParseResult across 10 calls."""
        parser = GoJSONParser()
        results = [parser.parse(_FAILING_OUTPUT) for _ in range(10)]
        first = results[0]
        for r in results[1:]:
            assert r == first

    def test_f2p_computation_deterministic(self) -> None:
        """Fixed pre/post fixtures → identical F2P list across 10 calls."""
        from swebenchify.grader import _compute_f2p_p2p

        parser = GoJSONParser()
        pre = parser.parse(_FAILING_OUTPUT)["tests"]
        post = parser.parse(_PASSING_OUTPUT)["tests"]

        results = [_compute_f2p_p2p(pre, post) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_compile_error_detected(self) -> None:
        """Compile-error output → compiled=False, empty tests dict."""
        result = GoJSONParser().parse(_COMPILE_ERROR_OUTPUT)
        assert result["compiled"] is False
        assert result["tests"] == {}

    def test_passing_test_parsed_correctly(self) -> None:
        result = GoJSONParser().parse(_PASSING_OUTPUT)
        assert result["compiled"] is True
        assert result["tests"]["github.com/foo/bar.TestA"] == "passed"

    def test_failing_test_still_compiled(self) -> None:
        """A test failure is NOT a compile error."""
        result = GoJSONParser().parse(_FAILING_OUTPUT)
        assert result["compiled"] is True
        assert result["tests"]["github.com/foo/bar.TestA"] == "failed"

    def test_f2p_from_pre_fail_post_pass(self) -> None:
        from swebenchify.grader import _compute_f2p_p2p

        parser = GoJSONParser()
        pre = parser.parse(_FAILING_OUTPUT)["tests"]
        post = parser.parse(_PASSING_OUTPUT)["tests"]
        f2p, _ = _compute_f2p_p2p(pre, post)
        assert "github.com/foo/bar.TestA" in f2p

    def test_empty_input_is_compile_error(self) -> None:
        result = GoJSONParser().parse("")
        assert result["compiled"] is False


# ---------------------------------------------------------------------------
# Category 3: Spec-generation schema
# ---------------------------------------------------------------------------

class TestConformanceSpecSchema:
    def test_go_env_spec_required_fields(self) -> None:
        """A GoEnvironmentSpec with all fields produces a 64-char hex hash."""
        spec = GoEnvironmentSpec(
            go_version="1.22",
            build_cmd="make build",
            test_cmd="go test ./pkg/...",
            module_mode="modules",
            goflags="",
            system_dependencies=[],
        )
        h = compute_env_spec_hash(spec)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_go_env_spec_hash_stability(self) -> None:
        """Serialize, deserialize, recompute → same hash."""
        spec = GoEnvironmentSpec(
            go_version="1.22",
            test_cmd="go test ./...",
            module_mode="vendored",
        )
        h1 = compute_env_spec_hash(spec)
        # Simulate round-trip through JSON
        spec2 = GoEnvironmentSpec(
            go_version=spec.go_version,
            test_cmd=spec.test_cmd,
            module_mode=spec.module_mode,
        )
        h2 = compute_env_spec_hash(spec2)
        assert h1 == h2

    def test_go_spec_registry_persistence(self, tmp_path: Path) -> None:
        """Write to tmp_path, reload → same mappings."""
        from swebenchify.go_registry import GoSpecRegistry

        spec = GoEnvironmentSpec(go_version="1.22", test_cmd="go test ./...")
        h = compute_env_spec_hash(spec)

        reg1 = GoSpecRegistry(tmp_path)
        version = reg1.register("kubernetes/kubectl", "abc123", spec)

        reg2 = GoSpecRegistry(tmp_path)
        assert reg2.get_version(h) == version
        assert reg2.get_era_commit(h) == "abc123"

    def test_hash_changes_on_spec_change(self) -> None:
        spec_a = GoEnvironmentSpec(go_version="1.21", test_cmd="go test ./...")
        spec_b = GoEnvironmentSpec(go_version="1.22", test_cmd="go test ./...")
        assert compute_env_spec_hash(spec_a) != compute_env_spec_hash(spec_b)

    def test_module_mode_affects_hash(self) -> None:
        spec_a = GoEnvironmentSpec(go_version="1.22", module_mode="modules")
        spec_b = GoEnvironmentSpec(go_version="1.22", module_mode="vendored")
        assert compute_env_spec_hash(spec_a) != compute_env_spec_hash(spec_b)


# ---------------------------------------------------------------------------
# Category 4: Schema validity (backward compatibility)
# ---------------------------------------------------------------------------

class TestConformanceSchemaValidity:
    def _make_go_task_instance(self, **overrides) -> TaskInstance:
        defaults = dict(
            repo="kubernetes/kubectl",
            instance_id="kubernetes__kubectl-1234",
            base_commit="abc123def456",
            patch="diff --git a/pkg/cmd/run.go b/pkg/cmd/run.go\n+// fix\n",
            test_patch="diff --git a/pkg/cmd/run_test.go b/pkg/cmd/run_test.go\n+// test\n",
            problem_statement="Fix the Run command to handle edge cases correctly.",
            hints_text="",
            created_at="2024-01-15T10:00:00Z",
            version="1.22-ab3f1200",
            FAIL_TO_PASS=json.dumps(["github.com/foo/bar.TestRun"]),
            PASS_TO_PASS=json.dumps(["github.com/foo/bar.TestOther"]),
            environment_setup_commit="setup_abc123",
            image_name="swebenchify-go-kubernetes__kubectl-ab3f1200ab3f",
        )
        defaults.update(overrides)
        return TaskInstance(**defaults)

    def test_task_instance_with_go_fields_is_valid(self) -> None:
        """A TaskInstance with Go-specific fields must serialize to valid JSON."""
        inst = self._make_go_task_instance()
        d = asdict(inst)
        serialised = json.dumps(d)
        assert isinstance(serialised, str)

    def test_asdict_produces_all_fields(self) -> None:
        inst = self._make_go_task_instance()
        d = asdict(inst)
        assert "image_name" in d
        assert d["image_name"] == "swebenchify-go-kubernetes__kubectl-ab3f1200ab3f"

    def test_go_instance_backward_compatible(self, tmp_path: Path) -> None:
        """Python consumers loading Go JSONL must not error on extra fields."""
        inst = self._make_go_task_instance()
        jsonl_path = tmp_path / "instances.jsonl"
        with open(jsonl_path, "w") as f:
            f.write(json.dumps(asdict(inst)) + "\n")

        # A Python consumer that only knows the base schema fields can load
        # the line without errors (extra keys are just ignored).
        with open(jsonl_path) as f:
            for line in f:
                data = json.loads(line)
                # These are the base SWEbenchInstance fields
                assert data["repo"] == inst.repo
                assert data["instance_id"] == inst.instance_id
                assert data["base_commit"] == inst.base_commit
                assert data["patch"] == inst.patch
                assert data["version"] == inst.version

    def test_fail_to_pass_is_json_encoded_list(self) -> None:
        inst = self._make_go_task_instance()
        f2p = json.loads(inst.FAIL_TO_PASS)
        assert isinstance(f2p, list)
        assert all(isinstance(t, str) for t in f2p)

    def test_pass_to_pass_is_json_encoded_list(self) -> None:
        inst = self._make_go_task_instance()
        p2p = json.loads(inst.PASS_TO_PASS)
        assert isinstance(p2p, list)

    def test_validation_result_with_quarantine_fields_serializable(self) -> None:
        """ValidationResult with quarantine fields must be constructible."""
        vr = ValidationResult(
            status="valid",
            FAIL_TO_PASS=["github.com/foo/bar.TestRun"],
            PASS_TO_PASS=["github.com/foo/bar.TestOther"],
            compiled=True,
            n_runs=3,
            flake_count=1,
            quarantined_tests=["github.com/foo/bar.TestFlaky"],
        )
        assert vr.n_runs == 3
        assert len(vr.quarantined_tests) == 1

    def test_image_name_none_for_python_instance(self) -> None:
        """Python instances have image_name=None (Go-only field)."""
        inst = TaskInstance(
            repo="pallets/flask",
            instance_id="pallets__flask-1",
            base_commit="abc",
            patch="",
            test_patch="",
            problem_statement="Fix thing",
            hints_text="",
            created_at="2024-01-01T00:00:00Z",
            version="2.3",
            FAIL_TO_PASS="[]",
            PASS_TO_PASS="[]",
        )
        assert inst.image_name is None
