"""Tests for swebenchify.eval_harness -- prompt formatting, imports, and round-trip.

These tests verify the prompt templates, tool constants, and that the
public API can be imported.  Actual agent calls are NOT tested here.
"""

from __future__ import annotations

import inspect
import json
import tempfile
from pathlib import Path

from swebenchify.eval_harness import (
    SOLVE_PROMPT,
    SOLVE_TOOLS,
    VERIFY_PROMPT,
    VERIFY_TOOLS,
    eval_instance,
    eval_instances,
    load_eval_results,
    save_eval_results,
)
from swebenchify.models import EvalResult


class TestSolvePrompt:
    """Test that SOLVE_PROMPT formats correctly."""

    def test_prompt_formats_without_error(self) -> None:
        """Formatting with all required keys should not raise KeyError."""
        result = SOLVE_PROMPT.format(
            repo="pallets/flask",
            problem_statement="Something is broken",
            test_cmd="python -m pytest -x",
        )
        assert isinstance(result, str)

    def test_prompt_contains_repo(self) -> None:
        result = SOLVE_PROMPT.format(
            repo="django/django",
            problem_statement="Bug description",
            test_cmd="pytest",
        )
        assert "django/django" in result

    def test_prompt_contains_problem_statement(self) -> None:
        result = SOLVE_PROMPT.format(
            repo="pallets/flask",
            problem_statement="The login endpoint returns 500",
            test_cmd="pytest",
        )
        assert "The login endpoint returns 500" in result

    def test_prompt_contains_test_cmd(self) -> None:
        result = SOLVE_PROMPT.format(
            repo="pallets/flask",
            problem_statement="Bug",
            test_cmd="python -m pytest tests/test_app.py -x",
        )
        assert "python -m pytest tests/test_app.py -x" in result

    def test_prompt_mentions_no_test_modification(self) -> None:
        result = SOLVE_PROMPT.format(
            repo="pallets/flask",
            problem_statement="Bug",
            test_cmd="pytest",
        )
        assert "Do NOT modify" in result
        assert "test" in result.lower()

    def test_prompt_mentions_minimal_change(self) -> None:
        result = SOLVE_PROMPT.format(
            repo="pallets/flask",
            problem_statement="Bug",
            test_cmd="pytest",
        )
        assert "minimal" in result


class TestVerifyPrompt:
    """Test that VERIFY_PROMPT formats correctly."""

    def test_prompt_formats_without_error(self) -> None:
        """Formatting with all required keys should not raise KeyError."""
        result = VERIFY_PROMPT.format(
            test_cmd="python -m pytest -x",
            target_tests='["test_foo", "test_bar"]',
        )
        assert isinstance(result, str)

    def test_prompt_contains_test_cmd(self) -> None:
        result = VERIFY_PROMPT.format(
            test_cmd="python -m pytest tests/test_app.py",
            target_tests="[]",
        )
        assert "python -m pytest tests/test_app.py" in result

    def test_prompt_contains_target_tests(self) -> None:
        result = VERIFY_PROMPT.format(
            test_cmd="pytest",
            target_tests='["test_login", "test_logout"]',
        )
        assert "test_login" in result
        assert "test_logout" in result

    def test_prompt_has_literal_braces_for_json_schema(self) -> None:
        """After formatting, the JSON examples should have actual { } braces."""
        result = VERIFY_PROMPT.format(
            test_cmd="pytest",
            target_tests="[]",
        )
        # The JSON schema examples should contain real braces, not {{/}}.
        assert "{{" not in result
        assert "}}" not in result

    def test_prompt_mentions_eval_result_json(self) -> None:
        result = VERIFY_PROMPT.format(
            test_cmd="pytest",
            target_tests="[]",
        )
        assert "eval_result.json" in result

    def test_prompt_mentions_tests_passed_and_failed(self) -> None:
        result = VERIFY_PROMPT.format(
            test_cmd="pytest",
            target_tests="[]",
        )
        assert "tests_passed" in result
        assert "tests_failed" in result


class TestSolveTools:
    """Test the SOLVE_TOOLS constant."""

    def test_is_list(self) -> None:
        assert isinstance(SOLVE_TOOLS, list)

    def test_contains_required_tools(self) -> None:
        for tool in ["Bash", "Read", "Edit", "Write", "Glob", "Grep"]:
            assert tool in SOLVE_TOOLS

    def test_has_exactly_six(self) -> None:
        assert len(SOLVE_TOOLS) == 6


class TestVerifyTools:
    """Test the VERIFY_TOOLS constant."""

    def test_is_list(self) -> None:
        assert isinstance(VERIFY_TOOLS, list)

    def test_contains_required_tools(self) -> None:
        for tool in ["Bash", "Read", "Write"]:
            assert tool in VERIFY_TOOLS

    def test_has_exactly_three(self) -> None:
        assert len(VERIFY_TOOLS) == 3


class TestEvalInstanceSignature:
    """Test that eval_instance has the expected signature."""

    def test_importable(self) -> None:
        assert callable(eval_instance)

    def test_is_coroutine_function(self) -> None:
        assert inspect.iscoroutinefunction(eval_instance)

    def test_signature_parameters(self) -> None:
        sig = inspect.signature(eval_instance)
        param_names = list(sig.parameters.keys())
        assert "instance" in param_names
        assert "env_spec" in param_names
        assert "repo" in param_names
        assert "workspace_mgr" in param_names
        assert "cost_tracker" in param_names
        assert "model" in param_names
        assert "max_turns" in param_names
        assert "budget_usd" in param_names

    def test_default_values(self) -> None:
        sig = inspect.signature(eval_instance)
        params = sig.parameters
        assert params["cost_tracker"].default is None
        assert params["model"].default == "haiku"
        assert params["max_turns"].default == 50
        assert params["budget_usd"].default == 2.0


class TestEvalInstancesSignature:
    """Test that eval_instances has the expected signature."""

    def test_importable(self) -> None:
        assert callable(eval_instances)

    def test_is_coroutine_function(self) -> None:
        assert inspect.iscoroutinefunction(eval_instances)

    def test_signature_parameters(self) -> None:
        sig = inspect.signature(eval_instances)
        param_names = list(sig.parameters.keys())
        assert "instances" in param_names
        assert "env_spec" in param_names
        assert "repo" in param_names
        assert "workspace_mgr" in param_names
        assert "cost_tracker" in param_names
        assert "model" in param_names
        assert "max_concurrent" in param_names
        assert "max_turns" in param_names
        assert "budget_usd" in param_names

    def test_default_values(self) -> None:
        sig = inspect.signature(eval_instances)
        params = sig.parameters
        assert params["cost_tracker"].default is None
        assert params["model"].default == "haiku"
        assert params["max_concurrent"].default == 2
        assert params["max_turns"].default == 50
        assert params["budget_usd"].default == 2.0


class TestEvalResultConstruction:
    """Test that EvalResult can be constructed with various configurations."""

    def test_minimal_construction(self) -> None:
        er = EvalResult(instance_id="owner__repo-123", resolved=False)
        assert er.instance_id == "owner__repo-123"
        assert er.resolved is False
        assert er.agent_patch is None
        assert er.tests_passed == []
        assert er.tests_failed == []
        assert er.cost_usd is None
        assert er.error_message is None

    def test_resolved_construction(self) -> None:
        er = EvalResult(
            instance_id="owner__repo-456",
            resolved=True,
            agent_patch="diff --git a/foo.py b/foo.py\n...",
            tests_passed=["test_a", "test_b"],
            tests_failed=[],
            cost_usd=1.50,
        )
        assert er.resolved is True
        assert er.agent_patch is not None
        assert len(er.tests_passed) == 2
        assert len(er.tests_failed) == 0
        assert er.cost_usd == 1.50

    def test_error_construction(self) -> None:
        er = EvalResult(
            instance_id="owner__repo-789",
            resolved=False,
            error_message="Agent failed: timeout",
            cost_usd=0.25,
        )
        assert er.resolved is False
        assert er.error_message == "Agent failed: timeout"


class TestSaveLoadEvalResults:
    """Test save_eval_results and load_eval_results round-trip."""

    def test_round_trip_single_result(self) -> None:
        results = [
            EvalResult(
                instance_id="owner__repo-100",
                resolved=True,
                agent_patch="diff ...",
                tests_passed=["test_foo"],
                tests_failed=[],
                cost_usd=0.75,
            )
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            save_eval_results(results, path)
            loaded = load_eval_results(path)
            assert len(loaded) == 1
            assert loaded[0].instance_id == "owner__repo-100"
            assert loaded[0].resolved is True
            assert loaded[0].agent_patch == "diff ..."
            assert loaded[0].tests_passed == ["test_foo"]
            assert loaded[0].tests_failed == []
            assert loaded[0].cost_usd == 0.75
            assert loaded[0].error_message is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_round_trip_multiple_results(self) -> None:
        results = [
            EvalResult(
                instance_id="owner__repo-1",
                resolved=True,
                tests_passed=["test_a"],
                cost_usd=1.0,
            ),
            EvalResult(
                instance_id="owner__repo-2",
                resolved=False,
                tests_failed=["test_b"],
                error_message="failed",
                cost_usd=0.5,
            ),
            EvalResult(
                instance_id="owner__repo-3",
                resolved=False,
            ),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            save_eval_results(results, path)
            loaded = load_eval_results(path)
            assert len(loaded) == 3
            assert loaded[0].instance_id == "owner__repo-1"
            assert loaded[0].resolved is True
            assert loaded[1].instance_id == "owner__repo-2"
            assert loaded[1].resolved is False
            assert loaded[1].error_message == "failed"
            assert loaded[2].instance_id == "owner__repo-3"
            assert loaded[2].resolved is False
            assert loaded[2].cost_usd is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_round_trip_empty_results(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            save_eval_results([], path)
            loaded = load_eval_results(path)
            assert loaded == []
        finally:
            Path(path).unlink(missing_ok=True)

    def test_saved_file_is_valid_jsonl(self) -> None:
        results = [
            EvalResult(instance_id="x__y-1", resolved=True, cost_usd=0.1),
            EvalResult(instance_id="x__y-2", resolved=False),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            save_eval_results(results, path)
            with open(path) as f:
                lines = [line.strip() for line in f if line.strip()]
            assert len(lines) == 2
            for line in lines:
                data = json.loads(line)
                assert "instance_id" in data
                assert "resolved" in data
        finally:
            Path(path).unlink(missing_ok=True)
