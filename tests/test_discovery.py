"""Tests for swebenchify.discovery -- prompt formatting and imports.

These tests verify the ENV_DISCOVERY_PROMPT template and that the
public API can be imported.  Actual agent calls are NOT tested here.
"""

from __future__ import annotations

import inspect


class TestEnvDiscoveryPrompt:
    """Test that ENV_DISCOVERY_PROMPT formats correctly."""

    def test_prompt_formats_without_error(self) -> None:
        """Formatting with repo and commit should not raise KeyError."""
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="pallets/flask", commit="abc123def"
        )
        assert isinstance(result, str)

    def test_prompt_contains_repo(self) -> None:
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="django/django", commit="deadbeef"
        )
        assert "django/django" in result

    def test_prompt_contains_commit(self) -> None:
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="pallets/flask", commit="abc123def456"
        )
        assert "abc123def456" in result

    def test_prompt_has_literal_braces_for_json_schema(self) -> None:
        """After formatting, the JSON examples should have actual { } braces."""
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="pallets/flask", commit="abc123"
        )
        # The JSON schema examples should contain real braces, not {{/}}.
        assert "{{" not in result
        assert "}}" not in result
        # And should contain the field names from the schema.
        assert '"language"' in result
        assert '"install_cmd"' in result
        assert '"test_cmd"' in result
        assert '"version"' in result

    def test_prompt_contains_env_spec_filename(self) -> None:
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="pallets/flask", commit="abc123"
        )
        assert "env_spec.json" in result

    def test_prompt_contains_version_filename(self) -> None:
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="pallets/flask", commit="abc123"
        )
        assert "version.json" in result

    def test_prompt_mentions_editable_installs(self) -> None:
        from swebenchify.discovery import ENV_DISCOVERY_PROMPT

        result = ENV_DISCOVERY_PROMPT.format(
            repo="pallets/flask", commit="abc123"
        )
        assert "editable" in result.lower() or "dev" in result.lower()


class TestEnvToolsList:
    """Test the ENV_TOOLS constant."""

    def test_env_tools_contains_required_tools(self) -> None:
        from swebenchify.discovery import ENV_TOOLS

        for tool in ["Bash", "Read", "Write", "Glob", "Grep"]:
            assert tool in ENV_TOOLS

    def test_env_tools_is_list(self) -> None:
        from swebenchify.discovery import ENV_TOOLS

        assert isinstance(ENV_TOOLS, list)


class TestGoEnvDiscoveryPrompt:
    """Test that GO_ENV_DISCOVERY_PROMPT formats correctly for Go repos."""

    def test_prompt_formats_without_error(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert isinstance(result, str)

    def test_prompt_contains_repo(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="etcd-io/etcd", commit="deadbeef"
        )
        assert "etcd-io/etcd" in result

    def test_prompt_contains_commit(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123def456"
        )
        assert "abc123def456" in result

    def test_prompt_references_go_mod(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert "go.mod" in result

    def test_prompt_references_go_test_json(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert "-json" in result

    def test_prompt_references_module_mode(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert "vendor" in result.lower()

    def test_prompt_outputs_go_env_spec_json(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert "go_env_spec.json" in result

    def test_prompt_has_literal_braces_for_json_schema(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert "{{" not in result
        assert "}}" not in result
        assert '"go_version"' in result
        assert '"test_cmd"' in result
        assert '"module_mode"' in result

    def test_prompt_does_not_install_anything(self) -> None:
        from swebenchify.discovery import GO_ENV_DISCOVERY_PROMPT

        result = GO_ENV_DISCOVERY_PROMPT.format(
            repo="kubernetes/kubectl", commit="abc123"
        )
        assert "Do NOT install" in result


class TestDiscoverGoEnvironmentSignature:
    """Test that discover_go_environment has the expected signature."""

    def test_importable(self) -> None:
        from swebenchify.discovery import discover_go_environment

        assert callable(discover_go_environment)

    def test_is_coroutine_function(self) -> None:
        import inspect

        from swebenchify.discovery import discover_go_environment

        assert inspect.iscoroutinefunction(discover_go_environment)

    def test_signature_parameters(self) -> None:
        import inspect

        from swebenchify.discovery import discover_go_environment

        sig = inspect.signature(discover_go_environment)
        param_names = list(sig.parameters.keys())
        assert "repo" in param_names
        assert "commit" in param_names
        assert "workspace_mgr" in param_names
        assert "registry" in param_names
        assert "cost_tracker" in param_names


class TestDiscoverEnvironmentSignature:
    """Test that the public API has the expected signature."""

    def test_importable(self) -> None:
        from swebenchify.discovery import discover_environment

        assert callable(discover_environment)

    def test_is_coroutine_function(self) -> None:
        from swebenchify.discovery import discover_environment

        assert inspect.iscoroutinefunction(discover_environment)

    def test_signature_parameters(self) -> None:
        from swebenchify.discovery import discover_environment

        sig = inspect.signature(discover_environment)
        param_names = list(sig.parameters.keys())
        assert "repo" in param_names
        assert "commit" in param_names
        assert "version" in param_names
        assert "workspace_mgr" in param_names
        assert "cost_tracker" in param_names
        assert "max_attempts" in param_names
        assert "max_turns" in param_names
        assert "budget_usd" in param_names

    def test_default_values(self) -> None:
        from swebenchify.discovery import discover_environment

        sig = inspect.signature(discover_environment)
        params = sig.parameters
        assert params["cost_tracker"].default is None
        assert params["max_attempts"].default == 3
        assert params["max_turns"].default == 80
        assert params["budget_usd"].default == 5.0


class TestRustDiscoveryPrompt:
    """Test that RUST_ENV_DISCOVERY_PROMPT formats correctly for Rust repos."""

    def test_prompt_contains_output_files(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        assert "rust_env_spec.json" in RUST_ENV_DISCOVERY_PROMPT
        assert "version.json" in RUST_ENV_DISCOVERY_PROMPT

    def test_prompt_format_strings(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        formatted = RUST_ENV_DISCOVERY_PROMPT.format(repo="test/repo", commit="abc123")
        assert "test/repo" in formatted
        assert "abc123" in formatted

    def test_prompt_mentions_toolchain_detection(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        assert "rust-toolchain.toml" in RUST_ENV_DISCOVERY_PROMPT
        assert "Cargo.toml" in RUST_ENV_DISCOVERY_PROMPT

    def test_prompt_mentions_workspace(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        assert "workspace" in RUST_ENV_DISCOVERY_PROMPT.lower()

    def test_prompt_rules_no_install(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        assert "do not install" in RUST_ENV_DISCOVERY_PROMPT.lower()

    def test_prompt_has_literal_braces_for_json_schema(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        result = RUST_ENV_DISCOVERY_PROMPT.format(
            repo="nickel-org/nickel.rs", commit="abc123"
        )
        assert "{{" not in result
        assert "}}" not in result
        assert '"rust_version"' in result
        assert '"test_cmd"' in result
        assert '"workspace_mode"' in result

    def test_prompt_mentions_edition(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        assert "edition" in RUST_ENV_DISCOVERY_PROMPT.lower()

    def test_prompt_mentions_features(self) -> None:
        from swebenchify.discovery import RUST_ENV_DISCOVERY_PROMPT

        assert "--all-features" in RUST_ENV_DISCOVERY_PROMPT


class TestDiscoverRustEnvironmentSignature:
    """Test that discover_rust_environment has the expected signature."""

    def test_importable(self) -> None:
        from swebenchify.discovery import discover_rust_environment

        assert callable(discover_rust_environment)

    def test_is_coroutine_function(self) -> None:
        from swebenchify.discovery import discover_rust_environment

        assert inspect.iscoroutinefunction(discover_rust_environment)

    def test_signature_parameters(self) -> None:
        from swebenchify.discovery import discover_rust_environment

        sig = inspect.signature(discover_rust_environment)
        param_names = list(sig.parameters.keys())
        assert "repo" in param_names
        assert "commit" in param_names
        assert "workspace_mgr" in param_names
        assert "registry" in param_names
        assert "cost_tracker" in param_names
