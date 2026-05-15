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
from swebenchify.models import EnvironmentSpec, RepoVersion, Repository
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

Report the MINIMUM supported version (e.g. if requires-python >= 3.8, \
report "3.8"). If not specified, use "3.9".

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
