"""Tests for swebenchify.validator -- prompt formatting and imports.

These tests verify the VALIDATION_PROMPT template, VALIDATION_TOOLS
constant, and that the public API can be imported.  Actual agent calls
are NOT tested here.
"""

from __future__ import annotations

import inspect


class TestValidationPrompt:
    """Test that VALIDATION_PROMPT formats correctly."""

    def test_prompt_formats_without_error(self) -> None:
        """Formatting with all required keys should not raise KeyError."""
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123def",
            env_spec='{"language": "python"}',
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert isinstance(result, str)

    def test_prompt_contains_repo(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="django/django",
            commit="deadbeef",
            env_spec="{}",
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert "django/django" in result

    def test_prompt_contains_commit(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123def456",
            env_spec="{}",
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert "abc123def456" in result

    def test_prompt_contains_env_spec(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123",
            env_spec='{"language": "python", "test_cmd": "pytest"}',
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert '"language": "python"' in result
        assert '"test_cmd": "pytest"' in result

    def test_prompt_contains_patch_paths(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123",
            env_spec="{}",
            test_patch_path="/workspace/test.patch",
            gold_patch_path="/workspace/gold.patch",
        )
        assert "/workspace/test.patch" in result
        assert "/workspace/gold.patch" in result

    def test_prompt_has_literal_braces_for_json_schema(self) -> None:
        """After formatting, the JSON examples should have actual { } braces."""
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123",
            env_spec="{}",
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        # The JSON schema examples should contain real braces, not {{/}}.
        assert "{{" not in result
        assert "}}" not in result
        # And should contain the field names from the schema.
        assert '"status"' in result
        assert '"FAIL_TO_PASS"' in result
        assert '"PASS_TO_PASS"' in result
        assert '"error_message"' in result

    def test_prompt_mentions_validation_result_filename(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123",
            env_spec="{}",
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert "validation_result.json" in result

    def test_prompt_mentions_git_apply(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123",
            env_spec="{}",
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert "git apply" in result

    def test_prompt_describes_all_status_values(self) -> None:
        from swebenchify.validator import VALIDATION_PROMPT

        result = VALIDATION_PROMPT.format(
            repo="pallets/flask",
            commit="abc123",
            env_spec="{}",
            test_patch_path="/tmp/test.patch",
            gold_patch_path="/tmp/gold.patch",
        )
        assert '"valid"' in result
        assert '"invalid"' in result
        assert '"error"' in result


class TestValidationToolsList:
    """Test the VALIDATION_TOOLS constant."""

    def test_validation_tools_is_list(self) -> None:
        from swebenchify.validator import VALIDATION_TOOLS

        assert isinstance(VALIDATION_TOOLS, list)

    def test_validation_tools_contains_required_tools(self) -> None:
        from swebenchify.validator import VALIDATION_TOOLS

        for tool in ["Bash", "Read", "Write"]:
            assert tool in VALIDATION_TOOLS

    def test_validation_tools_has_exactly_three(self) -> None:
        from swebenchify.validator import VALIDATION_TOOLS

        assert len(VALIDATION_TOOLS) == 3


class TestValidateInstanceSignature:
    """Test that validate_instance has the expected signature."""

    def test_importable(self) -> None:
        from swebenchify.validator import validate_instance

        assert callable(validate_instance)

    def test_is_coroutine_function(self) -> None:
        from swebenchify.validator import validate_instance

        assert inspect.iscoroutinefunction(validate_instance)

    def test_signature_parameters(self) -> None:
        from swebenchify.validator import validate_instance

        sig = inspect.signature(validate_instance)
        param_names = list(sig.parameters.keys())
        assert "candidate" in param_names
        assert "env_spec" in param_names
        assert "repo" in param_names
        assert "workspace_mgr" in param_names
        assert "cost_tracker" in param_names
        assert "max_attempts" in param_names
        assert "max_turns" in param_names
        assert "budget_usd" in param_names

    def test_default_values(self) -> None:
        from swebenchify.validator import validate_instance

        sig = inspect.signature(validate_instance)
        params = sig.parameters
        assert params["cost_tracker"].default is None
        assert params["max_attempts"].default == 3
        assert params["max_turns"].default == 60
        assert params["budget_usd"].default == 3.0


class TestValidateInstancesSignature:
    """Test that validate_instances has the expected signature."""

    def test_importable(self) -> None:
        from swebenchify.validator import validate_instances

        assert callable(validate_instances)

    def test_is_coroutine_function(self) -> None:
        from swebenchify.validator import validate_instances

        assert inspect.iscoroutinefunction(validate_instances)

    def test_signature_parameters(self) -> None:
        from swebenchify.validator import validate_instances

        sig = inspect.signature(validate_instances)
        param_names = list(sig.parameters.keys())
        assert "candidates" in param_names
        assert "env_specs" in param_names
        assert "repo" in param_names
        assert "workspace_mgr" in param_names
        assert "cost_tracker" in param_names
        assert "max_concurrent" in param_names
        assert "max_attempts" in param_names
        assert "max_turns" in param_names
        assert "budget_usd" in param_names
        assert "instance_versions" in param_names

    def test_default_values(self) -> None:
        from swebenchify.validator import validate_instances

        sig = inspect.signature(validate_instances)
        params = sig.parameters
        assert params["cost_tracker"].default is None
        assert params["max_concurrent"].default == 8
        assert params["max_attempts"].default == 3
        assert params["max_turns"].default == 60
        assert params["budget_usd"].default == 3.0
        assert params["instance_versions"].default is None


class TestValidationResultConstruction:
    """Test that ValidationResult can be constructed with all status values."""

    def test_valid_status(self) -> None:
        from swebenchify.models import ValidationResult

        vr = ValidationResult(
            status="valid",
            FAIL_TO_PASS=["test_a", "test_b"],
            PASS_TO_PASS=["test_c"],
        )
        assert vr.status == "valid"
        assert vr.FAIL_TO_PASS == ["test_a", "test_b"]
        assert vr.PASS_TO_PASS == ["test_c"]
        assert vr.error_message is None

    def test_invalid_status(self) -> None:
        from swebenchify.models import ValidationResult

        vr = ValidationResult(
            status="invalid",
            FAIL_TO_PASS=[],
            PASS_TO_PASS=["test_c"],
        )
        assert vr.status == "invalid"
        assert vr.FAIL_TO_PASS == []

    def test_error_status(self) -> None:
        from swebenchify.models import ValidationResult

        vr = ValidationResult(
            status="error",
            error_message="Something went wrong",
        )
        assert vr.status == "error"
        assert vr.error_message == "Something went wrong"
        assert vr.FAIL_TO_PASS == []
        assert vr.PASS_TO_PASS == []

    def test_default_lists(self) -> None:
        from swebenchify.models import ValidationResult

        vr = ValidationResult(status="valid")
        assert vr.FAIL_TO_PASS == []
        assert vr.PASS_TO_PASS == []
        assert vr.error_message is None
