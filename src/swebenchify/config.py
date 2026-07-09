"""Configuration parsing for SWE-benchify.

Loads YAML config files with environment variable resolution for secret
values. See docs/SPEC.md Section 6 for the configuration schema.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AgentStageConfig:
    """Configuration for a single agent stage (env discovery or validation)."""

    max_turns: int = 80
    budget_usd: float = 5.0


@dataclass
class AgentConfig:
    """Configuration for the agent dispatcher."""

    max_attempts: int = 3
    sandbox: str = "local"  # "local" or "docker"
    docker_image: str = "python:3.11-slim"  # base image for docker sandbox
    env_discovery: AgentStageConfig = field(
        default_factory=lambda: AgentStageConfig()
    )
    validation: AgentStageConfig = field(
        default_factory=lambda: AgentStageConfig(max_turns=60, budget_usd=3.0)
    )
    quality_eval: AgentStageConfig = field(
        default_factory=lambda: AgentStageConfig(max_turns=20, budget_usd=0.50)
    )


@dataclass
class PipelineConfig:
    """Configuration for pipeline concurrency and PR filtering."""

    max_concurrent_repos: int = 4
    max_concurrent_validations: int = 8
    max_prs_per_repo: int | None = None
    pr_after: str | None = None
    pr_before: str | None = None
    go_n_runs: int = 3  # number of validation runs for Go flake quarantine
    go_validation_timeout: int = 300  # seconds per test run phase in Docker
    python_n_runs: int = 1  # number of validation runs for Python flake quarantine
    python_validation_timeout: int = 600  # seconds per test run phase for Python Docker
    rust_n_runs: int = 3
    rust_validation_timeout: int = 600


@dataclass
class FilterConfig:
    """Configuration for quality filters (docs/SPEC.md Section 5.6)."""

    min_problem_statement_words: int = 40
    max_patch_lines: int = 500
    min_patch_lines: int = 1
    min_fail_to_pass: int = 1
    no_urls_in_problem: bool = True
    no_shas_in_problem: bool = True
    no_image_only_problem: bool = True
    no_new_symbol_tests: bool = True


@dataclass
class OutputConfig:
    """Configuration for output paths and HuggingFace upload."""

    dir: str = "./output"
    upload_to_hf: bool = False
    hf_repo: str | None = None


@dataclass
class DockerConfig:
    """Configuration for Docker image registry publishing."""

    registry: str = ""
    push_images: bool = False


@dataclass
class HarborConfig:
    """Configuration for Harbor task emission."""

    registry_url: str = ""
    org_name: str = "swebenchify"
    emit: bool = False


@dataclass
class Config:
    """Top-level configuration for SWE-benchify."""

    repos: list[str]
    github_token: str | None = None
    github_tokens: dict[str, str] = field(default_factory=dict)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    harbor: HarborConfig = field(default_factory=HarborConfig)
    go_repos: list[str] = field(default_factory=list)
    rust_repos: list[str] = field(default_factory=list)
    rh_jira_projects: list[str] = field(default_factory=lambda: ["STOR", "MGMT"])
    decontam_reference_paths: list[str] = field(default_factory=list)


_ENV_VAR_PATTERN = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


def _resolve_env_var(value: object) -> object:
    """Resolve a $VAR string to its environment variable value.

    If the value is a string matching $VAR_NAME, look it up in os.environ.
    Returns None if the variable is unset or empty.
    Non-string values are returned as-is.
    """
    if not isinstance(value, str):
        return value
    match = _ENV_VAR_PATTERN.match(value)
    if match:
        env_val = os.environ.get(match.group(1))
        if not env_val:
            return None
        return env_val
    return value


def _build_agent_stage_config(data: dict | None) -> AgentStageConfig:
    if data is None:
        return AgentStageConfig()
    return AgentStageConfig(
        max_turns=data.get("max_turns", AgentStageConfig.max_turns),
        budget_usd=data.get("budget_usd", AgentStageConfig.budget_usd),
    )


def _build_agent_config(data: dict | None) -> AgentConfig:
    if data is None:
        return AgentConfig()
    return AgentConfig(
        max_attempts=data.get("max_attempts", AgentConfig.max_attempts),
        sandbox=data.get("sandbox", AgentConfig.sandbox),
        docker_image=data.get("docker_image", AgentConfig.docker_image),
        env_discovery=_build_agent_stage_config(data.get("env_discovery")),
        validation=_build_agent_stage_config(
            data.get("validation")
            if data.get("validation") is not None
            else {"max_turns": 60, "budget_usd": 3.0}
        ),
        quality_eval=_build_agent_stage_config(
            data.get("quality_eval")
            if data.get("quality_eval") is not None
            else {"max_turns": 20, "budget_usd": 0.50}
        ),
    )


def _build_pipeline_config(data: dict | None) -> PipelineConfig:
    if data is None:
        return PipelineConfig()
    pr_date_range = data.get("pr_date_range", {}) or {}
    return PipelineConfig(
        max_concurrent_repos=data.get(
            "max_concurrent_repos", PipelineConfig.max_concurrent_repos
        ),
        max_concurrent_validations=data.get(
            "max_concurrent_validations", PipelineConfig.max_concurrent_validations
        ),
        max_prs_per_repo=data.get("max_prs_per_repo"),
        pr_after=pr_date_range.get("after"),
        pr_before=pr_date_range.get("before"),
        go_n_runs=data.get("go_n_runs", PipelineConfig.go_n_runs),
        go_validation_timeout=data.get(
            "go_validation_timeout", PipelineConfig.go_validation_timeout
        ),
        python_n_runs=data.get("python_n_runs", PipelineConfig.python_n_runs),
        python_validation_timeout=data.get(
            "python_validation_timeout", PipelineConfig.python_validation_timeout
        ),
        rust_n_runs=data.get("rust_n_runs", PipelineConfig.rust_n_runs),
        rust_validation_timeout=data.get(
            "rust_validation_timeout", PipelineConfig.rust_validation_timeout
        ),
    )


def _build_filter_config(data: dict | None) -> FilterConfig:
    if data is None:
        return FilterConfig()
    return FilterConfig(
        min_problem_statement_words=data.get(
            "min_problem_statement_words",
            FilterConfig.min_problem_statement_words,
        ),
        max_patch_lines=data.get(
            "max_patch_lines", FilterConfig.max_patch_lines
        ),
        min_patch_lines=data.get(
            "min_patch_lines", FilterConfig.min_patch_lines
        ),
        min_fail_to_pass=data.get(
            "min_fail_to_pass", FilterConfig.min_fail_to_pass
        ),
        no_urls_in_problem=data.get(
            "no_urls_in_problem", FilterConfig.no_urls_in_problem
        ),
        no_shas_in_problem=data.get(
            "no_shas_in_problem", FilterConfig.no_shas_in_problem
        ),
        no_image_only_problem=data.get(
            "no_image_only_problem", FilterConfig.no_image_only_problem
        ),
        no_new_symbol_tests=data.get(
            "no_new_symbol_tests", FilterConfig.no_new_symbol_tests
        ),
    )


def _build_output_config(data: dict | None) -> OutputConfig:
    if data is None:
        return OutputConfig()
    return OutputConfig(
        dir=data.get("dir", OutputConfig.dir),
        upload_to_hf=data.get("upload_to_hf", OutputConfig.upload_to_hf),
        hf_repo=data.get("hf_repo"),
    )


def _build_docker_config(data: dict | None) -> DockerConfig:
    if data is None:
        return DockerConfig()
    return DockerConfig(
        registry=data.get("registry", DockerConfig.registry),
        push_images=data.get("push_images", DockerConfig.push_images),
    )


def _build_harbor_config(data: dict | None) -> HarborConfig:
    if data is None:
        return HarborConfig()
    return HarborConfig(
        registry_url=data.get("registry_url", HarborConfig.registry_url),
        org_name=data.get("org_name", HarborConfig.org_name),
        emit=data.get("emit", HarborConfig.emit),
    )


def load_config(path: str) -> Config:
    """Load and validate a SWE-benchify configuration from a YAML file.

    Environment variable references ($VAR) are resolved from os.environ.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A validated Config dataclass.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If required fields are missing or invalid.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    logger.debug("parsed YAML config from path=%s", path)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML mapping")

    # Validate required fields
    repos = raw.get("repos")
    if not repos or not isinstance(repos, list) or len(repos) == 0:
        raise ValueError("'repos' is required and must be a non-empty list")

    # Resolve GitHub tokens
    github_section = raw.get("github", {}) or {}
    github_token = _resolve_env_var(github_section.get("token"))
    github_tokens: dict[str, str] = {}
    raw_tokens = github_section.get("tokens", {}) or {}
    for repo_name, token_val in raw_tokens.items():
        resolved = _resolve_env_var(token_val)
        if resolved is not None:
            github_tokens[repo_name] = str(resolved)
        else:
            logger.warning("token for repo=%s resolved to None, skipping", repo_name)

    cfg = Config(
        repos=repos,
        github_token=str(github_token) if github_token is not None else None,
        github_tokens=github_tokens,
        pipeline=_build_pipeline_config(raw.get("pipeline")),
        agent=_build_agent_config(raw.get("agent")),
        filters=_build_filter_config(raw.get("filters")),
        output=_build_output_config(raw.get("output")),
        docker=_build_docker_config(raw.get("docker")),
        harbor=_build_harbor_config(raw.get("harbor")),
        go_repos=raw.get("go_repos", []) or [],
        rust_repos=raw.get("rust_repos", []) or [],
        rh_jira_projects=raw.get("rh_jira_projects", ["STOR", "MGMT"]) or ["STOR", "MGMT"],
        decontam_reference_paths=raw.get("decontam_reference_paths", []) or [],
    )

    if not cfg.github_token and not cfg.github_tokens:
        raise ValueError(
            "No GitHub token configured. Set github.token or github.tokens "
            "in config, or $GITHUB_TOKEN env var."
        )

    output_path = Path(cfg.output.dir)
    output_path.mkdir(parents=True, exist_ok=True)
    if not os.access(str(output_path), os.W_OK):
        raise ValueError(f"Output directory is not writable: {cfg.output.dir}")

    go_count = len(cfg.go_repos)
    rust_count = len(cfg.rust_repos)
    logger.info(
        "config loaded: repos=%d, go_repos=%d, rust_repos=%d, output=%s",
        len(cfg.repos), go_count, rust_count, cfg.output.dir,
    )
    return cfg
