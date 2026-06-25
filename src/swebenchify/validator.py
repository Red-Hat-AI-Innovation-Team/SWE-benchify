"""Stage 4: Instance validation.

Dispatches a coding agent to validate each candidate instance by running
tests before and after applying the gold patch. See SPEC.md Section 5.5.

Go repos use deterministic Docker-based validation via grader.compute_f2p().
Python repos use the original agent-based approach.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from swebenchify.dispatcher import AgentResult, CostTracker, run_agent_with_retry
from swebenchify.grader import compute_f2p
from swebenchify.models import (
    AnyEnvironmentSpec,
    CandidateInstance,
    GoEnvironmentSpec,
    RustEnvironmentSpec,
    Repository,
    ValidationResult,
)
from swebenchify.workspace import WorkspaceManager

logger = logging.getLogger(__name__)

VALIDATION_PROMPT = """\
You are validating a benchmark instance for {repo} at commit {commit}.

## Environment Setup
The following environment spec was previously discovered for this repository:
```json
{env_spec}
```

## Steps
1. Set up the environment using the spec above (install dependencies, etc.).
2. Apply the test patch: `git apply {test_patch_path}`
   - This adds new or modified tests that should FAIL before the fix.
3. Run the test command from the env spec. Record which tests FAIL.
   - Parse the test output carefully to identify individual test names/IDs.
4. Apply the gold patch: `git apply {gold_patch_path}`
   - This is the actual fix that should make the failing tests pass.
5. Run the test command again. Record which tests PASS now.
6. Compute:
   - FAIL_TO_PASS: tests that FAILED in step 3 and PASS in step 5
   - PASS_TO_PASS: tests that PASSED in step 3 and still PASS in step 5

## Output
Write `validation_result.json` to the current directory with this exact schema:
```json
{{
  "status": "valid",
  "FAIL_TO_PASS": ["test.module::TestClass::test_method", ...],
  "PASS_TO_PASS": ["test.module::TestClass::test_other", ...],
  "error_message": null
}}
```

Status values:
- "valid": FAIL_TO_PASS has at least one test and all PASS_TO_PASS tests still pass
- "invalid": FAIL_TO_PASS is empty (the test patch doesn't catch the bug)
- "error": something went wrong (describe in error_message)

## Rules
- If tests fail for environment reasons (missing deps, build errors), debug and fix before concluding.
- Use full test identifiers (e.g., "tests/test_app.py::TestApp::test_login" for pytest).
- If you cannot get tests to run after reasonable effort, set status to "error".
- Do NOT include any text outside the JSON in validation_result.json.
"""

VALIDATION_TOOLS = ["Bash", "Read", "Write"]


async def _validate_go_docker(
    candidate: CandidateInstance,
    env_spec: GoEnvironmentSpec,
    timeout: int = 300,
    n_runs: int = 1,
) -> ValidationResult:
    """Validate a Go instance using deterministic Docker execution."""
    return await asyncio.to_thread(
        compute_f2p,
        repo=candidate.repo,
        base_commit=candidate.base_commit,
        test_patch=candidate.test_patch or "",
        gold_patch=candidate.patch or "",
        env_spec=env_spec,
        timeout=timeout,
        n_runs=n_runs,
    )


async def _validate_rust_docker(
    candidate: CandidateInstance,
    env_spec: RustEnvironmentSpec,
    timeout: int = 600,
    n_runs: int = 1,
) -> ValidationResult:
    """Validate a Rust instance using deterministic Docker execution."""
    from swebenchify.rust_grader import compute_rust_f2p

    return await asyncio.to_thread(
        compute_rust_f2p,
        repo=candidate.repo,
        base_commit=candidate.base_commit,
        test_patch=candidate.test_patch or "",
        gold_patch=candidate.patch or "",
        env_spec=env_spec,
        timeout=timeout,
        n_runs=n_runs,
    )


async def _run_once(
    candidate: CandidateInstance,
    env_spec: AnyEnvironmentSpec,
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    max_attempts: int = 3,
    max_turns: int = 60,
    budget_usd: float = 3.0,
) -> ValidationResult:
    """Execute a single validation run and return its result (Python path)."""
    return await validate_instance(
        candidate=candidate,
        env_spec=env_spec,
        repo=repo,
        workspace_mgr=workspace_mgr,
        cost_tracker=cost_tracker,
        max_attempts=max_attempts,
        max_turns=max_turns,
        budget_usd=budget_usd,
        n_runs=1,
    )


async def validate_instance(
    candidate: CandidateInstance,
    env_spec: AnyEnvironmentSpec,
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    max_attempts: int = 3,
    max_turns: int = 60,
    budget_usd: float = 3.0,
    n_runs: int = 1,
    timeout: int = 300,
) -> ValidationResult:
    """Validate a single candidate instance.

    Go repos use deterministic Docker-based validation (no agent needed).
    Python repos use the original agent-based approach.
    """
    is_go = isinstance(env_spec, GoEnvironmentSpec)
    is_rust = isinstance(env_spec, RustEnvironmentSpec)

    # Go: deterministic Docker path (handles quarantine internally)
    if is_go:
        return await _validate_go_docker(
            candidate=candidate,
            env_spec=env_spec,
            timeout=timeout,
            n_runs=n_runs,
        )

    # Rust: deterministic Docker path (handles quarantine internally)
    if is_rust:
        return await _validate_rust_docker(
            candidate=candidate,
            env_spec=env_spec,
            timeout=timeout,
            n_runs=n_runs,
        )

    # Python: agent-based path with optional multi-run quarantine
    if n_runs > 1:
        return await _validate_with_quarantine(
            candidate=candidate,
            env_spec=env_spec,
            repo=repo,
            workspace_mgr=workspace_mgr,
            cost_tracker=cost_tracker,
            max_attempts=max_attempts,
            max_turns=max_turns,
            budget_usd=budget_usd,
            n_runs=n_runs,
        )

    # Python: single-run agent validation
    inst_dir = workspace_mgr.prepare_validation_workspace(
        repo=repo,
        instance_id=candidate.instance_id,
        base_commit=candidate.base_commit,
        test_patch=candidate.test_patch or "",
        gold_patch=candidate.patch or "",
    )
    worktree = inst_dir / "repo"

    prompt = VALIDATION_PROMPT.format(
        repo=repo.full_name,
        commit=candidate.base_commit,
        env_spec=json.dumps(
            {
                "language": env_spec.language,
                "language_version": env_spec.language_version,
                "package_manager": env_spec.package_manager,
                "install_cmd": env_spec.install_cmd,
                "test_cmd": env_spec.test_cmd,
                "pre_install": env_spec.pre_install,
                "system_dependencies": env_spec.system_dependencies,
            },
            indent=2,
        ),
        test_patch_path=str(inst_dir / "test.patch"),
        gold_patch_path=str(inst_dir / "gold.patch"),
    )
    output_files = ["validation_result.json"]

    result = await run_agent_with_retry(
        prompt=prompt,
        cwd=str(worktree),
        output_files=output_files,
        tools=VALIDATION_TOOLS,
        max_turns=max_turns,
        budget_usd=budget_usd,
        max_attempts=max_attempts,
    )

    if cost_tracker:
        cost_tracker.record(
            "validation", repo.full_name, result, instance_id=candidate.instance_id
        )

    return _parse_python_validation_output(worktree, result)


async def _validate_with_quarantine(
    candidate: CandidateInstance,
    env_spec: AnyEnvironmentSpec,
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    max_attempts: int = 3,
    max_turns: int = 60,
    budget_usd: float = 3.0,
    n_runs: int = 3,
) -> ValidationResult:
    """Run N validation passes and quarantine flaky tests (Python path only)."""
    per_run_f2p: list[set[str]] = []
    per_run_p2p: list[set[str]] = []
    first_compiled = True

    for _ in range(n_runs):
        single = await _run_once(
            candidate=candidate,
            env_spec=env_spec,
            repo=repo,
            workspace_mgr=workspace_mgr,
            cost_tracker=cost_tracker,
            max_attempts=max_attempts,
            max_turns=max_turns,
            budget_usd=budget_usd,
        )
        if single.status == "error":
            return single

        if not single.compiled:
            first_compiled = False

        per_run_f2p.append(set(single.FAIL_TO_PASS))
        per_run_p2p.append(set(single.PASS_TO_PASS))

    f2p_union = per_run_f2p[0].copy()
    stable_f2p = per_run_f2p[0].copy()
    for run_set in per_run_f2p[1:]:
        f2p_union |= run_set
        stable_f2p &= run_set

    f2p = sorted(stable_f2p)
    flaky = f2p_union - stable_f2p
    quarantined = sorted(flaky)
    flake_count = len(quarantined)

    stable_p2p = per_run_p2p[0].copy()
    for run_set in per_run_p2p[1:]:
        stable_p2p &= run_set
    p2p = sorted(stable_p2p)

    if not f2p:
        return ValidationResult(
            status="invalid",
            FAIL_TO_PASS=[],
            PASS_TO_PASS=p2p,
            compiled=first_compiled,
            n_runs=n_runs,
            flake_count=flake_count,
            quarantined_tests=quarantined,
            error_message="All F2P tests quarantined as flaky" if quarantined else None,
        )

    return ValidationResult(
        status="valid",
        FAIL_TO_PASS=f2p,
        PASS_TO_PASS=p2p,
        compiled=first_compiled,
        n_runs=n_runs,
        flake_count=flake_count,
        quarantined_tests=quarantined,
    )


def _parse_python_validation_output(
    worktree: Path,
    result: "AgentResult",
) -> ValidationResult:
    """Parse Python validation agent output from validation_result.json."""
    result_path = worktree / "validation_result.json"
    if not result.is_error and result_path.exists():
        try:
            data = json.loads(result_path.read_text())
            return ValidationResult(
                status=data.get("status", "error"),
                FAIL_TO_PASS=data.get("FAIL_TO_PASS", []),
                PASS_TO_PASS=data.get("PASS_TO_PASS", []),
                error_message=data.get("error_message"),
            )
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("Failed to parse validation result: %s", e)
            return ValidationResult(status="error", error_message=str(e))

    return ValidationResult(
        status="error",
        error_message=f"Agent failed: {result.status} - {result.output or 'no output'}",
    )


async def validate_instances(
    candidates: list[CandidateInstance],
    env_specs: dict[str, AnyEnvironmentSpec],
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    max_concurrent: int = 8,
    max_attempts: int = 3,
    max_turns: int = 60,
    budget_usd: float = 3.0,
    instance_versions: dict[str, str] | None = None,
    timeout: int = 300,
    n_runs: int = 1,
) -> dict[str, ValidationResult]:
    """Validate multiple instances in parallel with bounded concurrency.

    Returns a dict mapping instance_id to ValidationResult.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: dict[str, ValidationResult] = {}

    async def validate_one(
        candidate: CandidateInstance,
    ) -> tuple[str, ValidationResult]:
        async with semaphore:
            version = (instance_versions or {}).get(candidate.instance_id, "unknown")
            env_spec = env_specs.get(version)
            if env_spec is None:
                if env_specs:
                    env_spec = next(iter(env_specs.values()))
                else:
                    return candidate.instance_id, ValidationResult(
                        status="error", error_message="No environment spec available"
                    )

            vr = await validate_instance(
                candidate=candidate,
                env_spec=env_spec,
                repo=repo,
                workspace_mgr=workspace_mgr,
                cost_tracker=cost_tracker,
                max_attempts=max_attempts,
                max_turns=max_turns,
                budget_usd=budget_usd,
                n_runs=n_runs,
                timeout=timeout,
            )
            return candidate.instance_id, vr

    tasks = [validate_one(c) for c in candidates]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in raw_results:
        if isinstance(r, Exception):
            logger.error("Validation task failed: %s", r)
            continue
        instance_id, vr = r
        results[instance_id] = vr

    return results
