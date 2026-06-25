"""Stage 3: Environment discovery.

Dispatches a coding agent to discover the build, install, and test setup
for each repository version. See SPEC.md Section 5.4.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from swebenchify.dispatcher import AgentResult, CostTracker, run_agent_with_retry
from swebenchify.go_registry import GoSpecRegistry, get_go_environment_setup_commit
from swebenchify.models import (
    GoEnvironmentSpec,
    RustEnvironmentSpec,
    EnvironmentSpec,
    RepoVersion,
    Repository,
    compute_env_spec_hash,
    compute_rust_env_spec_hash,
)
from swebenchify.rust_registry import RustSpecRegistry
from swebenchify.workspace import WorkspaceManager

logger = logging.getLogger(__name__)

# The prompt uses .format() with {repo} and {commit}, so literal braces
# in the JSON schema examples are doubled ({{ / }}).
ENV_DISCOVERY_PROMPT = """\
You are setting up the build and test environment for {repo} at commit {commit}.

This environment will run inside a Docker container. Do NOT create virtual \
environments (venv/virtualenv) — install directly into the system Python.

## Step 1: Detect the target Python version

Read configuration files to find which Python version the project targets:
- pyproject.toml: `[project] requires-python`
- setup.cfg: `[options] python_requires`
- tox.ini: `[tox] envlist` (e.g. py39 means 3.9)
- .python-version
- CI configs (.github/workflows/*.yml): look for Python version matrix

Report the HIGHEST version from the CI test matrix or tox envlist. \
For example, if tox tests py38, py39, py310, py311 — report "3.11". \
If CI tests 3.9 and 3.10, report "3.10". Only fall back to \
requires-python if no CI/tox config exists. If nothing is specified, \
use "3.9".

## Step 2: Read build configuration

Find and read: setup.py, pyproject.toml, setup.cfg, package.json, \
Cargo.toml, go.mod, Makefile, tox.ini, requirements*.txt.

## Step 3: Install the project

Install the project and its dependencies. Use `python -m pip install .` \
for the base install. For Python projects, prefer non-editable installs \
unless the test suite requires editable mode.

## Step 4: Determine pinned dependency versions

After installing, run `pip freeze` and extract the pinned versions of \
the project's direct dependencies. List them in `pip_packages` as \
`["package==version", ...]`. Focus on the project's own deps, not \
transitive sub-dependencies.

## Step 5: Find and verify the test command

Find the test command (pytest, tox, unittest, etc.). Run a quick smoke \
test to confirm it works. Use the simplest form: prefer `pytest -rA` \
over `python -m pytest tests/ -x --tb=short -q`.

## Step 6: Extract project version

Get the version from metadata files (major.minor format, e.g. "2.3").

## Output

Write two JSON files to the current directory:

1. `env_spec.json`:
   {{
     "language": "<e.g. python>",
     "language_version": "<target python version, e.g. 3.9>",
     "package_manager": "<e.g. pip>",
     "install_cmd": "<e.g. python -m pip install .>",
     "test_cmd": "<e.g. pytest -rA>",
     "pip_packages": ["<package==version>", "..."],
     "pre_install": [],
     "system_dependencies": ["<optional apt packages>"]
   }}

2. `version.json`:
   {{
     "repo": "{repo}",
     "commit": "{commit}",
     "version": "<e.g. 2.3>"
   }}

## Rules
- Do NOT create virtual environments — this runs in Docker.
- `pre_install` should only contain system setup (apt-get). Do NOT put \
  pip install commands or venv creation here.
- `install_cmd` should be a single command that installs the project. \
  Put test framework deps in `pip_packages` instead.
- The test command should run fast (under 5 minutes for the full suite).
- Do NOT include any text outside the JSON in the output files.
"""

ENV_TOOLS = ["Bash", "Read", "Write", "Glob", "Grep"]

# ---------------------------------------------------------------------------
# Go environment discovery
# ---------------------------------------------------------------------------

GO_ENV_DISCOVERY_PROMPT = """\
You are setting up the build and test environment for the Go repository \
{repo} at commit {commit}.

## Step 1: Detect the Go toolchain version

Read go.mod to find the `go` directive (e.g. `go 1.22`).  Also check the
`GOTOOLCHAIN` environment variable or `.go-version` file if present.
Report the version as a plain semver string (e.g. "1.22").

## Step 2: Detect the test entry point

Check in this priority order:
1. `Makefile` — look for a `test:` target. Use it if it runs `go test`.
2. `hack/` directory — look for a `test*.sh` or `run-tests.sh` script.
3. Fall back to: `go test ./...`

The chosen command must produce parseable `go test -json` output. If the
command does not already include `-json`, note that callers will wrap it.

## Step 3: Detect module mode

Check whether a `vendor/` directory is present and committed:
- If yes: module_mode = "vendored", suggest adding `-mod=vendor` to GOFLAGS.
- If no: module_mode = "modules".

## Step 4: Detect system dependencies

Scan `.github/workflows/*.yml` and any `Dockerfile` for apt-get or yum
install commands. List the package names.

## Step 5: Detect the build command

Look for `make build` target or `go build ./...`. Use the Makefile target
if present.

## Output

Write two JSON files to the current directory:

1. `go_env_spec.json`:
   {{
     "language": "go",
     "go_version": "<e.g. 1.22>",
     "build_cmd": "<e.g. make build>",
     "test_cmd": "<e.g. go test ./pkg/... or make test>",
     "module_mode": "<modules|vendored>",
     "goflags": "<e.g. -mod=vendor or empty string>",
     "system_dependencies": ["<optional apt packages>"]
   }}

2. `version.json`:
   {{
     "repo": "{repo}",
     "commit": "{commit}",
     "version": "<go_version from go.mod>"
   }}

## Rules
- Do NOT install anything — only inspect configuration files.
- Do NOT create virtual environments or modify the repository.
- Do NOT include any text outside the JSON in the output files.
- If you cannot determine a field, use an empty string rather than null.
"""

# ---------------------------------------------------------------------------
# Rust environment discovery
# ---------------------------------------------------------------------------

RUST_ENV_DISCOVERY_PROMPT = """\
You are setting up the build and test environment for the Rust repository \
{repo} at commit {commit}.

## Step 1: Detect the Rust toolchain version

Read configuration files to find which Rust version the project targets:
- rust-toolchain.toml: look for `channel` field under `[toolchain]` \
  (e.g. "1.84.0" or "stable")
- rust-toolchain (legacy format): plain text value (e.g. "1.84.0")
- Cargo.toml: `rust-version` field (MSRV, e.g. "1.70")
- Cargo.toml: `edition` field — use to infer minimum Rust version if no \
  explicit version is found (2015 → 1.0, 2018 → 1.31, 2021 → 1.56, \
  2024 → 1.85)
- CI configs (.github/workflows/*.yml): look for Rust version matrix

Report the version as a plain string (e.g. "1.84"). Prefer \
rust-toolchain.toml > rust-toolchain > Cargo.toml rust-version > \
CI matrix > edition inference.

## Step 2: Detect workspace structure

Check if the root Cargo.toml has a `[workspace]` section:
- If yes: workspace_mode = "workspace". List the member crate names \
  from the `members = [...]` array.
- If no: workspace_mode = "single", workspace_members = [].

## Step 3: Detect the test command

Check in this priority order:
1. `Makefile` — look for a `test:` target. Use it if it runs `cargo test`.
2. Fall back to: `cargo test --workspace` for workspaces, \
   `cargo test` for single crates.

## Step 4: Detect the build command

Check in this priority order:
1. `Makefile` — look for a `build:` target.
2. Fall back to: `cargo build`.

## Step 5: Detect system dependencies

Scan `.github/workflows/*.yml` and any `Dockerfile` for apt-get or yum \
install commands. List the package names. Common Rust dependencies \
include: clang, cmake, perl, pkg-config, libssl-dev, protobuf-compiler.

## Step 6: Detect edition and feature flags

Read the `edition` field from Cargo.toml (e.g. "2021").
Check if CI uses `--all-features` or specific `--features` flags. \
Report features as a string (e.g. "--all-features" or "").

## Output

Write two JSON files to the current directory:

1. `rust_env_spec.json`:
   {{
     "language": "rust",
     "rust_version": "<e.g. 1.84>",
     "build_cmd": "<e.g. cargo build>",
     "test_cmd": "<e.g. cargo test --workspace>",
     "workspace_mode": "<workspace|single>",
     "workspace_members": ["<crate1>", "<crate2>"],
     "edition": "<e.g. 2021>",
     "features": "<e.g. --all-features or empty string>",
     "system_dependencies": ["<optional apt packages>"]
   }}

2. `version.json`:
   {{
     "repo": "{repo}",
     "commit": "{commit}",
     "version": "<rust_version from toolchain or Cargo.toml>"
   }}

## Rules
- Do NOT install anything — only inspect configuration files.
- Do NOT compile or build the project.
- Do NOT modify the repository.
- Do NOT include any text outside the JSON in the output files.
- If you cannot determine a field, use an empty string rather than null.
"""


async def discover_environment(
    repo: Repository,
    commit: str,
    version: str,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    max_attempts: int = 3,
    max_turns: int = 80,
    budget_usd: float = 5.0,
) -> tuple[EnvironmentSpec | None, RepoVersion | None]:
    """Discover the build/test environment for a repo at a given commit.

    Returns ``(EnvironmentSpec, RepoVersion)`` on success, or
    ``(None, None)`` on failure.

    Results are cached per ``(repo, version)`` so the agent runs at most
    once for each unique version.
    """
    # ------------------------------------------------------------------ #
    # Check cache
    # ------------------------------------------------------------------ #
    cached = workspace_mgr.get_cached_env_spec(repo, version)
    if cached is not None:
        logger.info("Using cached env spec for %s v%s", repo.full_name, version)
        env_spec = EnvironmentSpec(
            **{k: v for k, v in cached.items() if k in EnvironmentSpec.__dataclass_fields__}
        )
        version_path = workspace_mgr.env_cache_dir(repo, version) / "version.json"
        if version_path.exists():
            version_data = json.loads(version_path.read_text())
            repo_version = RepoVersion(
                **{k: v for k, v in version_data.items() if k in RepoVersion.__dataclass_fields__}
            )
        else:
            repo_version = RepoVersion(
                repo=repo.full_name, commit=commit, version=version
            )
        return env_spec, repo_version

    # ------------------------------------------------------------------ #
    # Prepare workspace
    # ------------------------------------------------------------------ #
    worktree = workspace_mgr.prepare_env_workspace(repo, commit, version)
    env_dir = workspace_mgr.env_cache_dir(repo, version)

    # ------------------------------------------------------------------ #
    # Run agent
    # ------------------------------------------------------------------ #
    prompt = ENV_DISCOVERY_PROMPT.format(repo=repo.full_name, commit=commit)
    result: AgentResult = await run_agent_with_retry(
        prompt=prompt,
        cwd=str(worktree),
        output_files=["env_spec.json", "version.json"],
        tools=ENV_TOOLS,
        max_turns=max_turns,
        budget_usd=budget_usd,
        max_attempts=max_attempts,
    )

    if cost_tracker:
        cost_tracker.record("env-discovery", repo.full_name, result)

    # ------------------------------------------------------------------ #
    # Read and validate output
    # ------------------------------------------------------------------ #
    env_spec_path = worktree / "env_spec.json"
    version_path = worktree / "version.json"

    if not result.is_error and env_spec_path.exists() and version_path.exists():
        try:
            env_data = json.loads(env_spec_path.read_text())
            ver_data = json.loads(version_path.read_text())

            env_spec = EnvironmentSpec(
                **{k: v for k, v in env_data.items() if k in EnvironmentSpec.__dataclass_fields__}
            )
            repo_version = RepoVersion(
                **{k: v for k, v in ver_data.items() if k in RepoVersion.__dataclass_fields__}
            )

            # Cache results: copy output files to the env cache directory.
            for src_file in ["env_spec.json", "version.json"]:
                src = worktree / src_file
                dst = env_dir / src_file
                if src.exists() and src != dst:
                    shutil.copy2(src, dst)

            return env_spec, repo_version

        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error("Failed to parse agent output: %s", e)
            return None, None

    logger.error(
        "Environment discovery failed for %s v%s", repo.full_name, version
    )
    return None, None


async def discover_go_environment(
    repo: Repository,
    commit: str,
    workspace_mgr: WorkspaceManager,
    registry: GoSpecRegistry,
    cost_tracker: CostTracker | None = None,
    max_attempts: int = 3,
    max_turns: int = 40,
    budget_usd: float = 2.0,
) -> tuple[GoEnvironmentSpec | None, RepoVersion | None]:
    """Discover the Go build/test environment for a repo at a given commit.

    Dispatches a lightweight read-only agent to inspect go.mod and CI
    configuration — no installation happens. Results are registered in the
    ``GoSpecRegistry`` and cached per ``(repo, env_spec_hash)``.

    Returns ``(GoEnvironmentSpec, RepoVersion)`` on success, or
    ``(None, None)`` on failure.
    """
    worktree = workspace_mgr.prepare_env_workspace(repo, commit, version="go-discovery")

    prompt = GO_ENV_DISCOVERY_PROMPT.format(repo=repo.full_name, commit=commit)
    result: AgentResult = await run_agent_with_retry(
        prompt=prompt,
        cwd=str(worktree),
        output_files=["go_env_spec.json", "version.json"],
        tools=ENV_TOOLS,
        max_turns=max_turns,
        budget_usd=budget_usd,
        max_attempts=max_attempts,
    )

    if cost_tracker:
        cost_tracker.record("go-env-discovery", repo.full_name, result)

    spec_path = worktree / "go_env_spec.json"
    version_path = worktree / "version.json"

    if not result.is_error and spec_path.exists() and version_path.exists():
        try:
            spec_data = json.loads(spec_path.read_text())

            spec = GoEnvironmentSpec(
                **{
                    k: v
                    for k, v in spec_data.items()
                    if k in GoEnvironmentSpec.__dataclass_fields__ and k != "env_spec_hash"
                }
            )
            spec.env_spec_hash = compute_env_spec_hash(spec)

            version_string = registry.register(repo.full_name, commit, spec)
            repo_version = RepoVersion(
                repo=repo.full_name,
                commit=commit,
                version=version_string,
            )
            logger.info(
                "Go env discovered for %s: go%s, test=%s, mode=%s",
                repo.full_name, spec.go_version, spec.test_cmd, spec.module_mode,
            )
            return spec, repo_version

        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.error("Failed to parse Go env agent output: %s", exc)
            return None, None

    logger.error("Go environment discovery failed for %s", repo.full_name)
    return None, None


async def discover_rust_environment(
    repo: Repository,
    commit: str,
    workspace_mgr: WorkspaceManager,
    registry: RustSpecRegistry,
    cost_tracker: CostTracker | None = None,
    max_attempts: int = 3,
    max_turns: int = 40,
    budget_usd: float = 2.0,
) -> tuple[RustEnvironmentSpec | None, RepoVersion | None]:
    """Discover the Rust build/test environment for a repo at a given commit.

    Dispatches a lightweight read-only agent to inspect Cargo.toml and CI
    configuration — no installation or compilation happens. Results are
    registered in the ``RustSpecRegistry`` and cached per
    ``(repo, env_spec_hash)``.

    Returns ``(RustEnvironmentSpec, RepoVersion)`` on success, or
    ``(None, None)`` on failure.
    """
    worktree = workspace_mgr.prepare_env_workspace(repo, commit, version="rust-discovery")

    prompt = RUST_ENV_DISCOVERY_PROMPT.format(repo=repo.full_name, commit=commit)
    result: AgentResult = await run_agent_with_retry(
        prompt=prompt,
        cwd=str(worktree),
        output_files=["rust_env_spec.json", "version.json"],
        tools=ENV_TOOLS,
        max_turns=max_turns,
        budget_usd=budget_usd,
        max_attempts=max_attempts,
    )

    if cost_tracker:
        cost_tracker.record("rust-env-discovery", repo.full_name, result)

    spec_path = worktree / "rust_env_spec.json"
    version_path = worktree / "version.json"

    if not result.is_error and spec_path.exists() and version_path.exists():
        try:
            spec_data = json.loads(spec_path.read_text())

            spec = RustEnvironmentSpec(
                **{
                    k: v
                    for k, v in spec_data.items()
                    if k in RustEnvironmentSpec.__dataclass_fields__ and k != "env_spec_hash"
                }
            )
            spec.env_spec_hash = compute_rust_env_spec_hash(spec)

            version_string = registry.register(repo.full_name, commit, spec)
            repo_version = RepoVersion(
                repo=repo.full_name,
                commit=commit,
                version=version_string,
            )
            logger.info(
                "Rust env discovered for %s: rust%s, test=%s, mode=%s",
                repo.full_name, spec.rust_version, spec.test_cmd, spec.workspace_mode,
            )
            return spec, repo_version

        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.error("Failed to parse Rust env agent output: %s", exc)
            return None, None

    logger.error("Rust environment discovery failed for %s", repo.full_name)
    return None, None
