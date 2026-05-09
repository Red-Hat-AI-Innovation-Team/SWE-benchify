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
    inst_dir = workspace_mgr.instance_dir(f"eval_{instance.instance_id}")
    worktree = inst_dir / "repo"

    workspace_mgr.ensure_bare_clone(repo)
    workspace_mgr.create_worktree(repo, instance.base_commit, worktree)

    # Apply test_patch so the failing tests exist
    test_patch_file = inst_dir / "test.patch"
    inst_dir.mkdir(parents=True, exist_ok=True)
    test_patch_file.write_text(instance.test_patch)

    try:
        subprocess.run(
            ["git", "apply", str(test_patch_file)],
            cwd=str(worktree),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning(
            "Failed to apply test patch for %s: %s",
            instance.instance_id,
            e.stderr,
        )
        return EvalResult(
            instance_id=instance.instance_id,
            resolved=False,
            error_message=f"Failed to apply test patch: {e.stderr}",
        )

    # Step 1: Dispatch agent to solve the problem
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

    # Step 2: Verify -- run tests and check FAIL_TO_PASS
    verify_prompt = VERIFY_PROMPT.format(
        test_cmd=env_spec.test_cmd,
        target_tests=json.dumps(f2p_tests),
    )

    verify_result = await run_agent_task(
        prompt=verify_prompt,
        cwd=str(worktree),
        tools=VERIFY_TOOLS,
        max_turns=30,
        budget_usd=1.0,
        model=model,
    )

    total_cost += verify_result.cost_usd or 0.0

    if cost_tracker:
        # Record combined cost
        combined = AgentResult(
            status="success" if not verify_result.is_error else "error",
            output=verify_result.output,
            session_id=verify_result.session_id,
            cost_usd=total_cost,
            duration_ms=(solve_result.duration_ms or 0)
            + (verify_result.duration_ms or 0),
            num_turns=(solve_result.num_turns or 0)
            + (verify_result.num_turns or 0),
            is_error=verify_result.is_error,
        )
        cost_tracker.record(
            "eval",
            repo.full_name,
            combined,
            instance_id=instance.instance_id,
        )

    # Parse verification result
    eval_result_path = worktree / "eval_result.json"
    tests_passed: list[str] = []
    tests_failed: list[str] = list(f2p_tests)  # default: all failed

    if eval_result_path.exists():
        try:
            data = json.loads(eval_result_path.read_text())
            tests_passed = data.get("tests_passed", [])
            tests_failed = data.get("tests_failed", [])
        except (json.JSONDecodeError, TypeError):
            pass

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
