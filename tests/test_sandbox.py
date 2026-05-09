"""Tests for swebenchify.sandbox — Docker sandboxing utilities."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from swebenchify.sandbox import (
    SandboxConfig,
    get_docker_run_prefix,
    is_docker_available,
    prepare_docker_image,
)


# ---------------------------------------------------------------------------
# SandboxConfig defaults
# ---------------------------------------------------------------------------


class TestSandboxConfig:
    def test_defaults(self) -> None:
        cfg = SandboxConfig()
        assert cfg.enabled is False
        assert cfg.docker_image == "python:3.11-slim"

    def test_custom_values(self) -> None:
        cfg = SandboxConfig(enabled=True, docker_image="ubuntu:22.04")
        assert cfg.enabled is True
        assert cfg.docker_image == "ubuntu:22.04"


# ---------------------------------------------------------------------------
# get_docker_run_prefix
# ---------------------------------------------------------------------------


class TestGetDockerRunPrefix:
    def test_disabled_returns_empty(self, tmp_path: Path) -> None:
        cfg = SandboxConfig(enabled=False)
        assert get_docker_run_prefix(cfg, tmp_path) == []

    def test_enabled_returns_docker_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear ANTHROPIC_API_KEY so it doesn't leak into the test
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        cfg = SandboxConfig(enabled=True, docker_image="python:3.11-slim")
        result = get_docker_run_prefix(cfg, tmp_path)

        assert result[0] == "docker"
        assert result[1] == "run"
        assert "--rm" in result
        assert "--network" in result
        assert "host" in result
        assert "-w" in result
        assert "/workspace" in result
        # Image name is the last element
        assert result[-1] == "python:3.11-slim"

    def test_workspace_volume_mount(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        cfg = SandboxConfig(enabled=True)
        result = get_docker_run_prefix(cfg, tmp_path)

        # Find the -v flag and check the mount
        v_index = result.index("-v")
        mount = result[v_index + 1]
        assert mount.endswith(":/workspace")
        assert str(tmp_path.resolve()) in mount

    def test_env_vars_passed_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        cfg = SandboxConfig(enabled=True)
        result = get_docker_run_prefix(cfg, tmp_path)

        # Should include -e ANTHROPIC_API_KEY=sk-test-key
        assert "-e" in result
        e_index = result.index("-e")
        assert result[e_index + 1] == "ANTHROPIC_API_KEY=sk-test-key"

    def test_custom_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("MY_CUSTOM_VAR", "hello")

        cfg = SandboxConfig(enabled=True)
        result = get_docker_run_prefix(
            cfg, tmp_path, env_vars={"MY_CUSTOM_VAR": ""}
        )

        # Should include the custom var
        assert "MY_CUSTOM_VAR=hello" in result

    def test_empty_env_var_not_included(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        cfg = SandboxConfig(enabled=True)
        result = get_docker_run_prefix(cfg, tmp_path)

        # ANTHROPIC_API_KEY is unset and default is empty, so it should
        # not appear in the command
        env_entries = [r for r in result if r.startswith("ANTHROPIC_API_KEY=")]
        assert len(env_entries) == 0


# ---------------------------------------------------------------------------
# is_docker_available
# ---------------------------------------------------------------------------


class TestIsDockerAvailable:
    def test_returns_bool(self) -> None:
        result = is_docker_available()
        assert isinstance(result, bool)

    def test_returns_false_when_docker_not_found(self) -> None:
        with patch("swebenchify.sandbox.subprocess.run", side_effect=FileNotFoundError):
            assert is_docker_available() is False


# ---------------------------------------------------------------------------
# prepare_docker_image
# ---------------------------------------------------------------------------


class TestPrepareDockerImage:
    def test_disabled_returns_none(self, tmp_path: Path) -> None:
        cfg = SandboxConfig(enabled=False)
        assert prepare_docker_image(cfg, tmp_path) is None

    def test_returns_none_when_docker_unavailable(self, tmp_path: Path) -> None:
        cfg = SandboxConfig(enabled=True)
        with patch("swebenchify.sandbox.subprocess.run", side_effect=FileNotFoundError):
            assert prepare_docker_image(cfg, tmp_path) is None


# ---------------------------------------------------------------------------
# Config parsing integration
# ---------------------------------------------------------------------------


class TestConfigParsingSandbox:
    def test_sandbox_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default agent config should have sandbox=local and default docker_image."""
        from swebenchify.config import load_config

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                repos:
                  - owner/repo
                github:
                  token: $GITHUB_TOKEN
            """)
        )

        config = load_config(str(config_file))
        assert config.agent.sandbox == "local"
        assert config.agent.docker_image == "python:3.11-slim"

    def test_sandbox_docker_parsed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting sandbox: docker and docker_image should be parsed correctly."""
        from swebenchify.config import load_config

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                repos:
                  - owner/repo
                github:
                  token: $GITHUB_TOKEN
                agent:
                  sandbox: docker
                  docker_image: ubuntu:22.04
            """)
        )

        config = load_config(str(config_file))
        assert config.agent.sandbox == "docker"
        assert config.agent.docker_image == "ubuntu:22.04"

    def test_sandbox_local_explicit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicitly setting sandbox: local should work."""
        from swebenchify.config import load_config

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                repos:
                  - owner/repo
                github:
                  token: $GITHUB_TOKEN
                agent:
                  sandbox: local
            """)
        )

        config = load_config(str(config_file))
        assert config.agent.sandbox == "local"
        assert config.agent.docker_image == "python:3.11-slim"
