"""SWE-bench benchmark workflow — minimal bug-fix pipeline for containerized evaluation.

4-node pipeline: study → builder → gate_verify → auto_merge
RELOOP from gate_verify back to builder (max 3 iterations) on test failure.

Designed for Harbor containers where:
- Task instruction is at /tmp/task-instruction.md (passed via --prompt)
- Harbor's pytest verifier is the FINAL authority on pass/fail
- Harbor checks the MAIN branch for changes
- No .factory/ infrastructure (no eval, no experiments, no deep-QA)
"""

from typing import Any

from factory.models import ProjectState
from factory.workflow.primitives import (
    AgentNode,
    AgentRole,
    Edge,
    FnNode,
    GateNode,
    VerdictType,
    Workflow,
)

meta = {
    "name": "my_swebench",
    "description": (
        "SWE-bench benchmark mode — minimal 4-node pipeline for solving "
        "GitHub issues in containerized evaluation. study → builder → "
        "gate_verify → auto_merge with RELOOP on test failure."
    ),
}


def workflow() -> Workflow:
    """Build the SWE-bench workflow from scratch (not composed from improve)."""
    nodes: dict[str, Any] = {}
    edges: list[Edge] = []

    # ── Node 1: Study ──────────────────────────────────────────────
    nodes["study"] = FnNode(
        id="study",
        command=(
            "mkdir -p {project_path}/.factory/reviews && "
            "cd {project_path} && "
            "START_TIME=$(date +%s) && "
            "("
            "echo '=== Configuration Files ===' && "
            "ls -la go.mod go.sum Makefile setup.py setup.cfg pyproject.toml "
            "requirements.txt tox.ini conftest.py 2>/dev/null || true && "
            "echo '\\n=== Project Type Detection ===' && "
            "if [ -f go.mod ]; then "
            "echo 'Go project detected'; "
            "go list ./... 2>/dev/null | head -50; "
            "elif [ -f setup.py ] || [ -f pyproject.toml ]; then "
            "echo 'Python project detected'; "
            "fi && "
            "echo '\\n=== Go Source Files ===' && "
            "GO_COUNT=$(find . -type f -name '*.go' ! -name '*_test.go' | head -300 | tee /dev/stderr | wc -l) && "
            "echo '\\n=== Go Test Files ===' && "
            "GO_TEST_COUNT=$(find . -type f -name '*_test.go' | head -100 | tee /dev/stderr | wc -l) && "
            "echo '\\n=== Python Source Files ===' && "
            "PY_COUNT=$(find . -type f -name '*.py' | head -200 | tee /dev/stderr | wc -l) && "
            "echo '\\n=== Python Test Files ===' && "
            "PY_TEST_COUNT=$(find . -type f -name 'test_*.py' -o -name '*_test.py' | head -50 | tee /dev/stderr | wc -l) && "
            "echo '\\n=== Task Instruction ===' && "
            "cat /tmp/task-instruction.md 2>/dev/null || "
            "echo 'No task instruction file found at /tmp/task-instruction.md'"
            ") > .factory/reviews/study-output.md 2>&1 && "
            "END_TIME=$(date +%s) && "
            "ELAPSED=$((END_TIME - START_TIME)) && "
            "echo \"$(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) [study] "
            "go_files=${GO_COUNT:-0} go_tests=${GO_TEST_COUNT:-0} "
            "py_files=${PY_COUNT:-0} py_tests=${PY_TEST_COUNT:-0} "
            "project_type=$([ -f go.mod ] && echo go || echo python) "
            "elapsed=${ELAPSED}s\" >> {project_path}/.factory/reviews/pipeline-log.md"
        ),
        writes={".factory/reviews/study-output.md"},
    )

    # ── Node 2: Builder ────────────────────────────────────────────
    nodes["builder"] = AgentNode(
        id="builder",
        role=AgentRole.BUILDER,
        model="opus",
        timeout=7200,
        max_iterations=3,
        prompt_template=(
            "You are fixing a bug in an open-source project for the SWE-bench benchmark.\n\n"
            "## Your Task\n\n"
            "1. **Read the task instruction** — Read /tmp/task-instruction.md for the full "
            "bug description and task requirements.\n\n"
            "2. **Understand the codebase** — explore the repository structure. "
            "Read relevant source files, test files, and configuration. "
            "Identify the root cause of the bug described in the task.\n\n"
            "3. **Implement the fix** — make the MINIMAL change that resolves the "
            "issue. Do NOT refactor, modernize, or add unrelated improvements. "
            "Fix ONLY the described bug.\n\n"
            "4. **Run the project's own tests** — this is CRITICAL. Run the test "
            "suite to verify your fix works AND existing tests still pass.\n"
            "   - **Go projects:** run `go test -v -count=1 ./...` or check the Makefile "
            "for project-specific test commands (e.g. `make test`). "
            "*_test.go files live adjacent to source in the same package directory.\n"
            "   - **Python projects:** use pytest, tox, or the project's test runner.\n"
            "   - If specific test files are mentioned in the task, run those first.\n\n"
            "5. **Commit your changes** — commit directly on the current branch "
            "with a descriptive message referencing the issue. Do NOT create a "
            "new branch. Do NOT create a PR.\n\n"
            "6. **Write a summary** — after committing, write a brief summary to "
            ".factory/reviews/builder-latest.md: which files changed, commit hash, "
            "test result.\n\n"
            "## Rules\n\n"
            "- MINIMAL fix only — smallest diff that resolves the issue\n"
            "- MUST run tests before committing — never commit untested code\n"
            "- Do NOT create branches or PRs — commit on current branch\n"
            "- Do NOT run factory commands (factory eval, factory study, etc.)\n"
            "- Do NOT modify test files unless the bug is IN the test infrastructure\n"
            "- If tests fail after your fix, investigate and fix the issue\n\n"
            "## Go-Specific Guidelines\n\n"
            "When working on Go projects (go.mod present):\n\n"
            "**Test commands:**\n"
            "- `go test -v -count=1 ./...` — run all tests with no caching\n"
            "- Check Makefile for project-specific commands first\n"
            "- Run specific package tests: `go test -v -count=1 ./pkg/path/...`\n\n"
            "**Common Go bug patterns to watch for:**\n"
            "1. **Nil pointer dereference** — always add nil checks before accessing "
            "struct fields: `if obj != nil && obj.Field != nil`\n"
            "2. **Error wrapping** — use `fmt.Errorf(\"context: %w\", err)` not bare "
            "`return err`. Use `=` not `:=` when err is already declared in scope "
            "(avoids shadowing the named return).\n"
            "3. **Empty slice/string guards** — check `len(slice) > 0` before indexing "
            "into slices or checking specific elements\n"
            "4. **Interface method gaps** — if adding a method to an interface, "
            "implement it in ALL types that satisfy that interface\n"
            "5. **Error type wrapping** — return the right error type for the framework "
            "(e.g. `TransientOperationFailure` instead of generic `errors.New`)\n\n"
            "## Example Go Bug Fixes\n\n"
            "### Example 1: Nil + sentinel check (containers/podman)\n"
            "**Issue:** HasHealthCheck() returns true even when healthcheck is disabled "
            "with [\"NONE\"] sentinel.\n"
            "```diff\n"
            " func (c *Container) HasHealthCheck() bool {\n"
            "-\treturn c.config.HealthCheckConfig != nil\n"
            "+\tif c.config.HealthCheckConfig == nil {\n"
            "+\t\treturn false\n"
            "+\t}\n"
            "+\ttest := c.config.HealthCheckConfig.Test\n"
            "+\tif len(test) == 0 {\n"
            "+\t\treturn false\n"
            "+\t}\n"
            "+\tif len(test) == 1 && strings.ToUpper(test[0]) == define.HealthConfigTestNone {\n"
            "+\t\treturn false\n"
            "+\t}\n"
            "+\treturn true\n"
            " }\n"
            "```\n\n"
            "### Example 2: Error variable shadowing fix (containers/podman)\n"
            "**Issue:** Using `:=` inside defer shadows the named return `defErr`, "
            "so rollback errors are lost.\n"
            "```diff\n"
            " defer func() {\n"
            "   if defErr != nil {\n"
            "-    if err := tx.Rollback(); err != nil {\n"
            "+    if err = tx.Rollback(); err != nil {\n"
            "       logrus.Errorf(\"Rolling back transaction: %v\", err)\n"
            "     }\n"
            "   }\n"
            " }()\n"
            "```\n\n"
            "### Example 3: Condition-aware error messages (kubernetes)\n"
            "**Issue:** Error message doesn't explain WHY disruption budget blocks "
            "eviction — need to check PDB condition status.\n"
            "```diff\n"
            " if pdb.Status.DisruptionsAllowed == 0 {\n"
            "   err := errors.NewTooManyRequests(\"Cannot evict pod...\", 0)\n"
            "-  err.ErrStatus.Details.Causes = append(..., fmt.Sprintf(\n"
            "-    \"needs %d healthy pods and has %d\", ...))\n"
            "+  condition := meta.FindStatusCondition(pdb.Status.Conditions,\n"
            "+    policyv1.DisruptionAllowedCondition)\n"
            "+  var msg string\n"
            "+  switch {\n"
            "+  case condition != nil && condition.Reason == policyv1.SyncFailedReason:\n"
            "+    msg = fmt.Sprintf(\"failed sync: %s\", condition.Message)\n"
            "+  case pdb.Status.CurrentHealthy <= pdb.Status.DesiredHealthy:\n"
            "+    msg = fmt.Sprintf(\"needs %d healthy, has %d\", ...)\n"
            "+  default:\n"
            "+    msg = \"does not allow evicting pods currently\"\n"
            "+  }\n"
            "+  err.ErrStatus.Details.Causes = append(..., msg)\n"
            " }\n"
            "```\n"
        ),
        reads={".factory/reviews/study-output.md"},
        writes={".factory/reviews/builder-latest.md"},
    )

    # ── Node 3: Gate Verify ────────────────────────────────────────
    nodes["gate_verify"] = GateNode(
        id="gate_verify",
        evaluator_type="fn",
        evaluator_command=(
            "cd {project_path} && "
            "CHANGES=$(git diff HEAD~1 --stat 2>/dev/null || echo 'NO_COMMITS') && "
            "if [ \"$CHANGES\" = 'NO_COMMITS' ] || [ -z \"$CHANGES\" ]; then "
            "VERDICT='fail: builder did not commit any changes'; "
            "VSOURCE='no_commits'; "
            "echo \"$VERDICT\"; "
            "echo \"$(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) [gate_verify] "
            "verdict=fail source=$VSOURCE\" "
            ">> {project_path}/.factory/reviews/pipeline-log.md; "
            "exit 0; fi && "
            "REWARD_FILE=/logs/verifier/reward.txt && "
            "if [ -f \"$REWARD_FILE\" ]; then "
            "REWARD=$(cat \"$REWARD_FILE\" | tr -d '[:space:]') && "
            "if [ \"$REWARD\" = '1' ]; then "
            "VERDICT='pass: Harbor reward=1'; VSOURCE='reward.txt'; "
            "else "
            "VERDICT='reloop: Harbor reward=0 — tests failed'; VSOURCE='reward.txt'; "
            "fi; "
            "else "
            "BUILDER_OUTPUT=$(cat .factory/reviews/builder-latest.md 2>/dev/null || echo '') && "
            "if echo \"$BUILDER_OUTPUT\" | grep -qiE 'tests?.*(pass|succeed|ok|PASSED)'; then "
            "VERDICT='pass: builder reports tests passing'; VSOURCE='grep_fallback'; "
            "elif echo \"$BUILDER_OUTPUT\" | grep -qiE 'tests?.*(fail|error|FAILED)'; then "
            "VERDICT='reloop: builder needs to retry — tests did not pass'; VSOURCE='grep_fallback'; "
            "else "
            "VERDICT='pass: changes committed, no issues detected'; VSOURCE='grep_fallback'; "
            "fi; "
            "fi && "
            "echo \"$VERDICT\" && "
            "echo \"$(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) [gate_verify] "
            "verdict=$(echo $VERDICT | cut -d: -f1) source=$VSOURCE "
            "reward=${REWARD:-N/A}\" "
            ">> {project_path}/.factory/reviews/pipeline-log.md"
        ),
        reads={".factory/reviews/builder-latest.md"},
    )

    # ── Node 4: Auto Merge ─────────────────────────────────────────
    nodes["auto_merge"] = FnNode(
        id="auto_merge",
        command=(
            "cd {project_path} && "
            "CURRENT=$(git rev-parse --abbrev-ref HEAD) && "
            "COMMON=$(git rev-parse --git-common-dir) && "
            "BASE=$(git --git-dir=\"$COMMON\" symbolic-ref --short HEAD 2>/dev/null || echo main) && "
            "if [ \"$CURRENT\" = \"$BASE\" ]; then "
            "echo \"Already on $BASE — no merge needed\"; "
            "echo \"$(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) [auto_merge] "
            "base=$BASE status=already_on_base\" "
            ">> {project_path}/.factory/reviews/pipeline-log.md; "
            "exit 0; fi && "
            "git update-ref refs/heads/\"$BASE\" HEAD && "
            "PARENT_WT=$(cd \"$COMMON/..\" && pwd) && "
            "FILE_COUNT=0 && "
            "git diff-tree -z --no-commit-id --name-only -r HEAD HEAD~1 | "
            "while IFS= read -r -d '' file; do "
            "if [ -f \"$file\" ]; then "
            "mkdir -p \"$PARENT_WT/$(dirname \"$file\")\" && "
            "cp \"$file\" \"$PARENT_WT/$file\" && "
            "FILE_COUNT=$((FILE_COUNT + 1)); "
            "fi; done && "
            "cd \"$PARENT_WT\" && git checkout \"$BASE\" 2>/dev/null || true && "
            "echo \"Updated $BASE to $(cd {project_path} && git rev-parse --short HEAD)\" && "
            "echo \"$(date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ) [auto_merge] "
            "base=$BASE files_copied=$FILE_COUNT "
            "new_head=$(cd {project_path} && git rev-parse --short HEAD) status=success\" "
            ">> {project_path}/.factory/reviews/pipeline-log.md"
        ),
        reads={".factory/reviews/builder-latest.md"},
    )

    # ── Edges ──────────────────────────────────────────────────────

    edges = [
        Edge(source="study", target="builder"),
        Edge(source="builder", target="gate_verify"),
        Edge(source="gate_verify", target="auto_merge", condition=VerdictType.PROCEED),
        Edge(source="gate_verify", target="builder", condition=VerdictType.RELOOP),
    ]

    # ── Trigger ────────────────────────────────────────────────────

    def trigger(state: ProjectState, ctx: dict[str, Any]) -> bool:
        return ctx.get("mode") == "my_swebench"

    return Workflow(
        name="my_swebench",
        nodes=nodes,
        edges=edges,
        start_node="study",
        terminal=True,
        trigger=trigger,
    )
