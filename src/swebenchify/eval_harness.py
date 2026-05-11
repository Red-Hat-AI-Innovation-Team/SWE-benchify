"""Mini evaluation harness -- run a coding agent on benchmark instances."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import asdict
from pathlib import Path

from swebenchify.dispatcher import AgentResult, CostTracker, run_agent_task
from swebenchify.models import EnvironmentSpec, EvalResult, Repository, TaskInstance
from swebenchify.workspace import WorkspaceManager

logger = logging.getLogger(__name__)

SOLVE_PROMPT = '''You are a software engineer fixing a bug in {repo}.

The repository is checked out at the relevant commit. There are failing tests that demonstrate the bug.

## Problem
{problem_statement}

## Instructions
1. Read and understand the problem described above.
2. Find the relevant source code (do NOT modify test files).
3. Fix the bug so the failing tests pass.
4. Verify your fix by running the test command: {test_cmd}

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/).
Focus on making the minimal change needed to fix the described issue.
'''

VERIFY_PROMPT = '''Run the following test command and report the results:

```
{test_cmd}
```

After running, write `eval_result.json` with this exact schema:
{{
  "tests_passed": ["test.id.1", ...],
  "tests_failed": ["test.id.2", ...],
  "error": null
}}

List only the tests from this set: {target_tests}

If the test command fails entirely, set "error" to a description of the failure.
'''

SOLVE_TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep"]
VERIFY_TOOLS = ["Bash", "Read", "Write"]


async def eval_instance(
    instance: TaskInstance,
    env_spec: EnvironmentSpec,
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    model: str = "haiku",
    max_turns: int = 50,
    budget_usd: float = 2.0,
) -> EvalResult:
    """Run a coding agent on a single instance to try to solve it.

    The agent gets the problem_statement and must fix the code.
    Then we verify if the FAIL_TO_PASS tests now pass.
    """
    f2p_tests = json.loads(instance.FAIL_TO_PASS)

    # Prepare workspace: repo at base_commit with test_patch applied
    # Use a separate eval_instances directory to avoid colliding with validation workspaces
    inst_dir = (workspace_mgr.repo_dir(repo) / "eval_instances" / instance.instance_id).resolve()
    worktree = inst_dir / "repo"

    workspace_mgr.ensure_bare_clone(repo)
    inst_dir.mkdir(parents=True, exist_ok=True)
    workspace_mgr.create_worktree(repo, instance.base_commit, worktree)

    # Set up the environment so tests can run
    for pre_cmd in env_spec.pre_install:
        subprocess.run(pre_cmd, shell=True, cwd=str(worktree),
                       capture_output=True, text=True, timeout=120)
    install_result = subprocess.run(
        env_spec.install_cmd, shell=True, cwd=str(worktree),
        capture_output=True, text=True, timeout=300,
    )
    if install_result.returncode != 0:
        logger.warning("Install failed for %s (may still work): %s",
                       instance.instance_id, install_result.stderr[-200:])

    # Save test_patch for later (applied AFTER the agent finishes, matching SWE-bench flow)
    test_patch_file = inst_dir / "test.patch"
    test_patch_file.write_text(instance.test_patch)

    # Step 1: Dispatch agent to solve the problem (no test patch applied yet)
    solve_prompt = SOLVE_PROMPT.format(
        repo=repo.full_name,
        problem_statement=instance.problem_statement,
        test_cmd=env_spec.test_cmd,
    )

    solve_result = await run_agent_task(
        prompt=solve_prompt,
        cwd=str(worktree),
        tools=SOLVE_TOOLS,
        max_turns=max_turns,
        budget_usd=budget_usd,
        model=model,
    )

    total_cost = solve_result.cost_usd or 0.0

    if solve_result.is_error:
        if cost_tracker:
            cost_tracker.record(
                "eval",
                repo.full_name,
                solve_result,
                instance_id=instance.instance_id,
            )
        return EvalResult(
            instance_id=instance.instance_id,
            resolved=False,
            cost_usd=total_cost,
            error_message=f"Agent failed: {solve_result.status}",
        )

    # Capture the agent's patch
    try:
        diff_result = subprocess.run(
            ["git", "diff"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=30,
        )
        agent_patch = diff_result.stdout if diff_result.returncode == 0 else None
    except subprocess.TimeoutExpired:
        agent_patch = None

    if cost_tracker:
        cost_tracker.record(
            "eval", repo.full_name, solve_result, instance_id=instance.instance_id
        )

    # Step 2: Apply test_patch AFTER agent finishes, then verify
    # This matches SWE-bench's flow: agent patch → test patch → run tests
    try:
        subprocess.run(
            ["git", "apply", str(test_patch_file)],
            cwd=str(worktree), check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        try:
            subprocess.run(
                ["git", "apply", "--3way", str(test_patch_file)],
                cwd=str(worktree), check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning("Test patch failed for %s: %s", instance.instance_id, e.stderr[:100])
            return EvalResult(
                instance_id=instance.instance_id, resolved=False,
                agent_patch=agent_patch, cost_usd=total_cost,
                error_message=f"Test patch failed after agent: {e.stderr[:100]}",
            )

    tests_passed: list[str] = []
    tests_failed: list[str] = []

    # Re-install in case the agent changed dependencies
    subprocess.run(env_spec.install_cmd, shell=True, cwd=str(worktree),
                   capture_output=True, text=True, timeout=300)

    for test_id in f2p_tests:
        try:
            # Run the specific test by appending the test ID to the base command
            # pytest accepts test IDs directly; other frameworks may need adaptation
            base_cmd = env_spec.test_cmd.split()[0]  # e.g., "python" or "PYTHONPATH=."
            test_cmd = f"{env_spec.test_cmd} {test_id}" if "::" in test_id else env_spec.test_cmd
            # For pytest-style test IDs, run them directly
            if "::" in test_id:
                test_cmd = f"python -m pytest {test_id} -x -q"
            test_proc = subprocess.run(
                test_cmd, shell=True, cwd=str(worktree),
                capture_output=True, text=True, timeout=120,
            )
            if test_proc.returncode == 0:
                tests_passed.append(test_id)
            else:
                tests_failed.append(test_id)
                logger.debug("Test %s failed: %s", test_id, test_proc.stdout[-200:])
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("Test execution failed for %s: %s", test_id, e)
            tests_failed.append(test_id)

    resolved = len(tests_passed) == len(f2p_tests) and len(tests_failed) == 0

    return EvalResult(
        instance_id=instance.instance_id,
        resolved=resolved,
        agent_patch=agent_patch,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        cost_usd=total_cost,
    )


async def eval_instances(
    instances: list[TaskInstance],
    env_spec: EnvironmentSpec,
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    model: str = "haiku",
    max_concurrent: int = 2,
    max_turns: int = 50,
    budget_usd: float = 2.0,
) -> list[EvalResult]:
    """Evaluate multiple instances with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def eval_one(inst: TaskInstance) -> EvalResult:
        async with semaphore:
            return await eval_instance(
                inst,
                env_spec=env_spec,
                repo=repo,
                workspace_mgr=workspace_mgr,
                cost_tracker=cost_tracker,
                model=model,
                max_turns=max_turns,
                budget_usd=budget_usd,
            )

    return list(
        await asyncio.gather(
            *[eval_one(i) for i in instances], return_exceptions=False
        )
    )


def save_eval_results(results: list[EvalResult], path: str) -> None:
    """Save eval results to JSONL."""
    with open(path, "w") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")


def load_eval_results(path: str) -> list[EvalResult]:
    """Load eval results from JSONL."""
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                results.append(EvalResult(**data))
    return results
