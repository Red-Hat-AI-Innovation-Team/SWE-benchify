"""Stage 4: Instance validation.

Dispatches a coding agent to validate each candidate instance by running
tests before and after applying the gold patch. See SPEC.md Section 5.5.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from swebenchify.dispatcher import AgentResult, CostTracker, run_agent_with_retry
from swebenchify.models import (
    AnyEnvironmentSpec,
    CandidateInstance,
    EnvironmentSpec,
    GoEnvironmentSpec,
    Repository,
    ValidationResult,
)
from swebenchify.parsers import GoJSONParser
from swebenchify.workspace import WorkspaceManager

logger = logging.getLogger(__name__)

# The prompt uses .format() with {repo}, {commit}, {env_spec},
# {test_patch_path}, and {gold_patch_path}.  Literal braces in JSON
# schema examples are doubled ({{ / }}).
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

# ---------------------------------------------------------------------------
# Go validation prompt
# ---------------------------------------------------------------------------

# For Go instances the agent writes raw go test -json output to files.
# The Python side (validate_instance) parses those files deterministically
# using GoJSONParser — the agent does NOT interpret results.
GO_VALIDATION_PROMPT = """\
You are validating a Go benchmark instance for {repo} at commit {commit}.

## Environment
```json
{env_spec}
```

## Steps

1. Set up the Go environment:
   - If module_mode is "vendored", ensure GOFLAGS includes -mod=vendor.
   - Apply any system dependencies if needed (they should already be present).

2. Apply the test patch:
   ```
   git apply {test_patch_path}
   ```

3. Run the test command and capture raw JSON output:
   ```
   {test_cmd} -json 2>&1 | tee pre_fix_output.txt
   ```
   If the test command already includes -json, omit the flag.
   If the command fails to compile (exit code non-zero with no test output),
   that is a build error — continue to step 6.

4. Apply the gold patch:
   ```
   git apply {gold_patch_path}
   ```

5. Run the test command again and capture JSON output:
   ```
   {test_cmd} -json 2>&1 | tee post_fix_output.txt
   ```

6. Write validation_meta.json:
   ```json
   {{
     "status": "done",
     "error_message": null
   }}
   ```
   If something went catastrophically wrong (e.g., git apply failed),
   set status to "error" and describe the problem in error_message.

## Rules
- Write ONLY raw go test -json output to pre_fix_output.txt and post_fix_output.txt.
- Do NOT interpret or summarise test results — that happens on the Python side.
- If a file already exists, overwrite it.
- Do NOT modify any source files other than applying the patches.
"""


def _compute_f2p_p2p(
    pre_parse: dict[str, str],
    post_parse: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Compute FAIL_TO_PASS and PASS_TO_PASS from deterministic parse results.

    Args:
        pre_parse:  test_id -> status before applying gold patch.
        post_parse: test_id -> status after applying gold patch.

    Returns:
        ``(FAIL_TO_PASS, PASS_TO_PASS)`` lists.
    """
    pre_failed = {t for t, s in pre_parse.items() if s == "failed"}
    pre_passed = {t for t, s in pre_parse.items() if s == "passed"}
    post_passed = {t for t, s in post_parse.items() if s == "passed"}

    fail_to_pass = sorted(pre_failed & post_passed)
    pass_to_pass = sorted(pre_passed & post_passed)
    return fail_to_pass, pass_to_pass


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
    """Execute a single validation run and return its result."""
    return await validate_instance(
        candidate=candidate,
        env_spec=env_spec,
        repo=repo,
        workspace_mgr=workspace_mgr,
        cost_tracker=cost_tracker,
        max_attempts=max_attempts,
        max_turns=max_turns,
        budget_usd=budget_usd,
        n_runs=1,  # prevent recursion
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
) -> ValidationResult:
    """Validate a single candidate instance by running tests before and after the gold patch.

    When ``n_runs > 1``, runs validation N times and applies flake quarantine:
    - A test is stable-fail if it fails on ALL N pre-fix runs.
    - A test is stable-pass if it passes on ALL N post-fix runs.
    - F2P = stable-fail ∩ stable-pass.
    - Tests that are inconsistent across runs are quarantined and removed.
    - If all F2P tests are quarantined, returns ``status="invalid"``.

    Returns a ValidationResult with FAIL_TO_PASS and PASS_TO_PASS test lists.
    """
    # Multi-run quarantine path
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

    # Prepare workspace
    inst_dir = workspace_mgr.prepare_validation_workspace(
        repo=repo,
        instance_id=candidate.instance_id,
        base_commit=candidate.base_commit,
        test_patch=candidate.test_patch or "",
        gold_patch=candidate.patch or "",
    )
    worktree = inst_dir / "repo"

    is_go = isinstance(env_spec, GoEnvironmentSpec)

    if is_go:
        env_spec_dict = {
            "language": env_spec.language,
            "go_version": env_spec.go_version,
            "build_cmd": env_spec.build_cmd,
            "test_cmd": env_spec.test_cmd,
            "module_mode": env_spec.module_mode,
            "goflags": env_spec.goflags,
            "system_dependencies": env_spec.system_dependencies,
        }
        prompt = GO_VALIDATION_PROMPT.format(
            repo=repo.full_name,
            commit=candidate.base_commit,
            env_spec=json.dumps(env_spec_dict, indent=2),
            test_cmd=env_spec.test_cmd,
            test_patch_path=str(inst_dir / "test.patch"),
            gold_patch_path=str(inst_dir / "gold.patch"),
        )
        output_files = ["pre_fix_output.txt", "post_fix_output.txt", "validation_meta.json"]
    else:
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

    # Run agent
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

    # Parse output — Go path uses deterministic parser; Python path uses agent output
    if is_go:
        return _parse_go_validation_output(worktree, result)
    else:
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
    """Run N validation passes and quarantine flaky tests.

    A test is stable only if its outcome is consistent across all runs.
    Flaky tests (inconsistent across runs) are quarantined and removed from F2P.

    Returns a ValidationResult with quarantine metadata populated.
    """
    # Per-run sets derived from FAIL_TO_PASS and PASS_TO_PASS of each run.
    # FAIL_TO_PASS already encodes "failed pre-fix AND passed post-fix".
    # PASS_TO_PASS encodes "passed in both pre- and post-fix runs".
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
            # Propagate hard errors immediately
            return single

        if not single.compiled:
            first_compiled = False

        per_run_f2p.append(set(single.FAIL_TO_PASS))
        per_run_p2p.append(set(single.PASS_TO_PASS))

    # Stable F2P: present in ALL runs (consistently flipped fail→pass)
    f2p_union = per_run_f2p[0].copy()
    stable_f2p = per_run_f2p[0].copy()
    for run_set in per_run_f2p[1:]:
        f2p_union |= run_set
        stable_f2p &= run_set

    f2p = sorted(stable_f2p)

    # Flaky: appeared in SOME runs but not all
    flaky = f2p_union - stable_f2p
    quarantined = sorted(flaky)
    flake_count = len(quarantined)

    # Stable P2P: passed in ALL runs
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


def _parse_go_validation_output(
    worktree: Path,
    result: "AgentResult",
) -> ValidationResult:
    """Parse Go validation agent output using GoJSONParser."""
    meta_path = worktree / "validation_meta.json"
    pre_path = worktree / "pre_fix_output.txt"
    post_path = worktree / "post_fix_output.txt"

    if result.is_error:
        return ValidationResult(
            status="error",
            error_message=f"Agent failed: {result.status} - {result.output or 'no output'}",
        )

    # Check for explicit agent error
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            if meta.get("status") == "error":
                return ValidationResult(
                    status="error",
                    error_message=meta.get("error_message", "Agent reported error"),
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # Read raw test output
    pre_log = pre_path.read_text() if pre_path.exists() else ""
    post_log = post_path.read_text() if post_path.exists() else ""

    parser = GoJSONParser()
    pre_result = parser.parse(pre_log)
    post_result = parser.parse(post_log)

    compiled = pre_result["compiled"]
    fail_to_pass, pass_to_pass = _compute_f2p_p2p(
        pre_result["tests"], post_result["tests"]
    )

    if not compiled:
        return ValidationResult(
            status="invalid",
            compiled=False,
            pre_fix_log=pre_log or None,
            post_fix_log=post_log or None,
            error_message="Pre-fix build failed (compiled=False)",
        )

    status = "valid" if fail_to_pass else "invalid"
    return ValidationResult(
        status=status,
        FAIL_TO_PASS=fail_to_pass,
        PASS_TO_PASS=pass_to_pass,
        compiled=compiled,
        pre_fix_log=pre_log or None,
        post_fix_log=post_log or None,
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
    env_specs: dict[str, AnyEnvironmentSpec],  # keyed by version
    repo: Repository,
    workspace_mgr: WorkspaceManager,
    cost_tracker: CostTracker | None = None,
    max_concurrent: int = 8,
    max_attempts: int = 3,
    max_turns: int = 60,
    budget_usd: float = 3.0,
    instance_versions: dict[str, str] | None = None,  # instance_id -> version
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
            # Find the env spec for this instance's version
            version = (instance_versions or {}).get(candidate.instance_id, "unknown")
            env_spec = env_specs.get(version)
            if env_spec is None:
                # Try first available env spec as fallback
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
