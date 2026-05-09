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

Explore the repository. Find and read build configuration files (setup.py, \
pyproject.toml, package.json, Cargo.toml, go.mod, Makefile, tox.ini, \
setup.cfg, etc.).

Your tasks:
1. Identify the language, version, and package manager.
2. Install the project and its dependencies (prefer dev/editable installs).
3. Find the test command and run a quick smoke test to confirm it works.
4. Extract the project version from metadata files.

When done, write two JSON files to the current directory:

1. `env_spec.json` with this exact schema:
   {{
     "language": "<e.g. python>",
     "language_version": "<e.g. 3.11>",
     "package_manager": "<e.g. pip>",
     "install_cmd": "<e.g. pip install -e .[dev]>",
     "test_cmd": "<e.g. python -m pytest -x>",
     "pre_install": ["<optional setup commands>"],
     "system_dependencies": ["<optional apt packages>"]
   }}

2. `version.json` with this exact schema:
   {{
     "repo": "{repo}",
     "commit": "{commit}",
     "version": "<e.g. 2.3.1>"
   }}

Constraints:
- You may install system packages with apt-get.
- Prefer editable/development installs.
- The test command should run fast (target: under 5 minutes for the full suite).
- If the full test suite takes too long, find a subset command.
- If something fails, read error messages carefully and try alternatives.
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
