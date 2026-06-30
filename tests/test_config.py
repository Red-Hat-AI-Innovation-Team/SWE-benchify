"""Tests for swebenchify.config — YAML config parsing and env var resolution."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from swebenchify.config import Config, load_config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Write a minimal valid config file and return its path."""
    config_file = tmp_path / "swebenchify.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            repos:
              - pallets/flask
              - django/django

            github:
              token: $SWEBENCHIFY_TEST_TOKEN

            pipeline:
              max_concurrent_repos: 2
              max_concurrent_validations: 4
              max_prs_per_repo: 100
              pr_date_range:
                after: "2020-01-01"
                before: "2024-01-01"

            agent:
              max_attempts: 5
              env_discovery:
                max_turns: 100
                budget_usd: 10.0
              validation:
                max_turns: 50
                budget_usd: 2.0

            filters:
              min_problem_statement_words: 20
              max_patch_lines: 300
              no_urls_in_problem: false
              no_shas_in_problem: true

            output:
              dir: ./my_output
              upload_to_hf: true
              hf_repo: myuser/my-dataset
        """)
    )
    return config_file


def test_load_config_parses_all_fields(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full config with all fields set should parse correctly."""
    monkeypatch.setenv("SWEBENCHIFY_TEST_TOKEN", "ghp_testtoken123")
    config = load_config(str(tmp_config))

    assert isinstance(config, Config)
    assert config.repos == ["pallets/flask", "django/django"]
    assert config.github_token == "ghp_testtoken123"

    # Pipeline
    assert config.pipeline.max_concurrent_repos == 2
    assert config.pipeline.max_concurrent_validations == 4
    assert config.pipeline.max_prs_per_repo == 100
    assert config.pipeline.pr_after == "2020-01-01"
    assert config.pipeline.pr_before == "2024-01-01"

    # Agent
    assert config.agent.max_attempts == 5
    assert config.agent.env_discovery.max_turns == 100
    assert config.agent.env_discovery.budget_usd == 10.0
    assert config.agent.validation.max_turns == 50
    assert config.agent.validation.budget_usd == 2.0

    # Filters
    assert config.filters.min_problem_statement_words == 20
    assert config.filters.max_patch_lines == 300
    assert config.filters.no_urls_in_problem is False
    assert config.filters.no_shas_in_problem is True

    # Output
    assert config.output.dir == "./my_output"
    assert config.output.upload_to_hf is True
    assert config.output.hf_repo == "myuser/my-dataset"


def test_env_var_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """$VAR references should be resolved from os.environ."""
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            repos:
              - pallets/flask
            github:
              token: $MY_GH_TOKEN
              tokens:
                pallets/flask: $FLASK_TOKEN
        """)
    )
    monkeypatch.setenv("MY_GH_TOKEN", "ghp_global")
    monkeypatch.setenv("FLASK_TOKEN", "ghp_flask")

    config = load_config(str(config_file))

    assert config.github_token == "ghp_global"
    assert config.github_tokens == {"pallets/flask": "ghp_flask"}


def test_unset_env_var_resolves_to_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """$VAR that is not set in the environment should resolve to None for
    the individual token, but a fallback token must be present to avoid
    the validation error."""
    monkeypatch.delenv("NONEXISTENT_TOKEN_VAR", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fallback")

    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            repos:
              - pallets/flask
            github:
              token: $NONEXISTENT_TOKEN_VAR
              tokens:
                pallets/flask: $GITHUB_TOKEN
        """)
    )

    config = load_config(str(config_file))
    assert config.github_token is None
    assert config.github_tokens["pallets/flask"] == "ghp_fallback"


def test_defaults_applied_for_minimal_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A config with only 'repos' should get defaults for everything else."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_testdefault")

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

    assert config.repos == ["owner/repo"]
    assert config.github_token == "ghp_testdefault"
    assert config.github_tokens == {}
    assert config.pipeline.max_concurrent_repos == 4
    assert config.pipeline.max_concurrent_validations == 8
    assert config.pipeline.max_prs_per_repo is None
    assert config.agent.max_attempts == 3
    assert config.agent.env_discovery.max_turns == 80
    assert config.agent.validation.max_turns == 60
    assert config.agent.validation.budget_usd == 3.0
    assert config.filters.min_problem_statement_words == 40
    assert config.filters.max_patch_lines == 500
    assert config.output.dir == "./output"
    assert config.output.upload_to_hf is False


def test_missing_repos_raises_value_error(tmp_path: Path) -> None:
    """Config without 'repos' should raise ValueError."""
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text("github:\n  token: abc\n")

    with pytest.raises(ValueError, match="repos"):
        load_config(str(config_file))


def test_empty_repos_raises_value_error(tmp_path: Path) -> None:
    """Config with empty 'repos' list should raise ValueError."""
    config_file = tmp_path / "cfg.yaml"
    config_file.write_text("repos: []\n")

    with pytest.raises(ValueError, match="repos"):
        load_config(str(config_file))


def test_file_not_found_raises(tmp_path: Path) -> None:
    """load_config with a non-existent path should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "does_not_exist.yaml"))


def test_no_github_token_raises_value_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config without any GitHub token should raise ValueError."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    config_file = tmp_path / "cfg.yaml"
    config_file.write_text("repos:\n  - owner/repo\n")

    with pytest.raises(ValueError, match="No GitHub token configured"):
        load_config(str(config_file))


def test_output_dir_not_writable_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config with a non-writable output dir should raise ValueError."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    # Create a read-only directory
    ro_dir = tmp_path / "readonly_output"
    ro_dir.mkdir()
    ro_dir.chmod(0o444)

    config_file = tmp_path / "cfg.yaml"
    config_file.write_text(
        textwrap.dedent(f"""\
            repos:
              - owner/repo
            github:
              token: $GITHUB_TOKEN
            output:
              dir: {ro_dir}
        """)
    )

    try:
        with pytest.raises(ValueError, match="not writable"):
            load_config(str(config_file))
    finally:
        ro_dir.chmod(0o755)


class TestRustConfig:
    """Tests for Rust-specific configuration fields."""

    def test_rust_repos_default_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert config.rust_repos == []

    def test_rust_repos_parsed_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                repos:
                  - cloudflare/pingora
                github:
                  token: $GITHUB_TOKEN
                rust_repos:
                  - cloudflare/pingora
            """)
        )
        config = load_config(str(config_file))
        assert config.rust_repos == ["cloudflare/pingora"]

    def test_rust_n_runs_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert config.pipeline.rust_n_runs == 3

    def test_rust_validation_timeout_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert config.pipeline.rust_validation_timeout == 600

    def test_rust_n_runs_parsed_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        config_file = tmp_path / "cfg.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                repos:
                  - owner/repo
                github:
                  token: $GITHUB_TOKEN
                pipeline:
                  rust_n_runs: 5
                  rust_validation_timeout: 900
            """)
        )
        config = load_config(str(config_file))
        assert config.pipeline.rust_n_runs == 5
        assert config.pipeline.rust_validation_timeout == 900
