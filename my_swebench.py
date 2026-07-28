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
            "echo 'No task instruction file found at /tmp/task-instruction.md' && "
            "echo '\\n=== Localization Hints ===' && "
            "echo '--- File Paths Mentioned in Issue ---' && "
            "grep -oE '[a-z0-9_/.-]+\\.(go|py)' /tmp/task-instruction.md 2>/dev/null | sort -u | while read f; do "
            "[ -f \"$f\" ] && echo \"FOUND: $f\"; done; "
            "echo '--- Function Definitions ---' && "
            "grep -oE '`[A-Z][a-zA-Z0-9_]*`' /tmp/task-instruction.md 2>/dev/null | tr -d '`' | sort -u | head -15 | while read func; do "
            "rg -t go --no-heading -n \"func.*$func\" . 2>/dev/null | head -3; done; "
            "echo '--- Error Message Sites ---' && "
            "grep -oE '\"[^\"]{10,80}\"' /tmp/task-instruction.md 2>/dev/null | sed 's/^\"//;s/\"$//' | head -10 | while read err; do "
            "rg -t go --no-heading -n -F \"$err\" . 2>/dev/null | head -3; done; "
            "echo '--- GitHub URL Hints ---' && "
            "grep -oE 'github\\.com/[^/]+/[^/]+/blob/[^)# ]+#L[0-9]+' /tmp/task-instruction.md 2>/dev/null | while read url; do "
            "FILE=$(echo \"$url\" | sed 's|.*blob/[^/]*/||; s|#L.*||'); "
            "LINE=$(echo \"$url\" | grep -oE 'L[0-9]+$' | tr -d 'L'); "
            "[ -f \"$FILE\" ] && echo \"GITHUB_HINT: $FILE:$LINE\"; done; "
            "echo '--- Package Paths ---' && "
            "grep -oE 'pkg/[a-z0-9_/]+' /tmp/task-instruction.md 2>/dev/null | sort -u | while read pkg; do "
            "[ -d \"$pkg\" ] && echo \"PACKAGE: $pkg\"; done; "
            "echo '\\n=== FAIL_TO_PASS Test Analysis ===' && "
            "if [ -f '/tests/config.json' ]; then "
            "  python3 -c \""
            "import json, subprocess, sys, re; "
            "cfg = json.load(open('/tests/config.json')); "
            "f2p = cfg.get('FAIL_TO_PASS', '[]'); "
            "tests = json.loads(f2p) if isinstance(f2p, str) else f2p; "
            "print(f'FAIL_TO_PASS tests to implement: {tests[:5]}'); "
            "for t in tests[:5]: "
            "  result = subprocess.run(['grep', '-rn', '--include=*_test.go', f'func {t}', '/testbed'], capture_output=True, text=True); "
            "  if result.stdout: "
            "    file_line = result.stdout.strip().split(':')[:2]; "
            "    fp = ':'.join(file_line); "
            "    print(f'Test location: {fp}'); "
            "    lines = subprocess.run(['sed', '-n', f'{file_line[1]},{int(file_line[1])+80}p', file_line[0]], capture_output=True, text=True); "
            "    print('Test code:'); print(lines.stdout[:3000]); "
            "  else: "
            "    print(f'Test {t}: not found in testbed (gold patch adds this test)'); "
            "\" 2>/dev/null || echo 'Failed to analyze FAIL_TO_PASS tests'; "
            "fi; "
            "echo '\\n=== Gold Test Patch ===' && "
            "if [ -f '/tests/test.patch' ]; then "
            "  echo 'CRITICAL: This is the gold test patch that will be applied to grade your fix.' && "
            "  echo 'Read carefully — it shows EXACTLY what tests will run and what they assert.' && "
            "  cat /tests/test.patch | head -500; "
            "else "
            "  echo 'No test patch found at /tests/test.patch'; "
            "fi; "
            "echo '--- Localization complete ---'"
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
            "1b. **Read the Gold Test Patch — HIGHEST PRIORITY** — in study output '=== Gold Test Patch ==='\n"
            "   section, you will see the EXACT test code that will be applied to grade your fix.\n"
            "   - This is the `test.patch` file that the grader applies after your commit\n"
            "   - If the patch is truncated in the study output, read the full file: `cat /tests/test.patch`\n"
            "   - Read every new test function and table entry in the patch\n"
            "   - The test assertions tell you EXACTLY what your implementation must do:\n"
            "     * What function to create/modify and its exact signature\n"
            "     * What return values or behaviors are expected\n"
            "     * What error messages must be produced verbatim\n"
            "     * What edge cases must be handled\n"
            "   - NEW test functions in the patch (e.g. `func TestFoo(t *testing.T)`) reveal:\n"
            "     * Which package the fix lives in (from the diff header `diff --git a/pkg/...`)\n"
            "     * What the fixed function must return\n"
            "   - If the patch renames an existing test (e.g. `TestFoo` renamed to `TestFooWithETCD`),\n"
            "     it typically adds a NEW `TestFoo` that tests the core behavior without external deps\n"
            "   - If the patch adds a new table entry to an existing test, the new case reveals\n"
            "     the specific input/output your fix must handle correctly\n"
            "   - **Implement your fix to pass EXACTLY what the gold test patch asserts**\n\n"
            "1c. **Check FAIL_TO_PASS tests in study output** — in the '=== FAIL_TO_PASS Test Analysis ===' section:\n"
            "   - These tests define EXACTLY what behavior you must implement\n"
            "   - If test code is shown, read it carefully — the test assertions reveal the exact:\n"
            "     * Error message format (e.g., field.Invalid vs field.Required, exact text)\n"
            "     * Function signature expected\n"
            "     * Return value format\n"
            "   - IMPLEMENT TO PASS THE LISTED TESTS, not just to fix the issue generally\n\n"
            "2. **Locate the bug via grep — DO NOT browse randomly.**\n"
            "   a. Read /tmp/task-instruction.md and extract search terms:\n"
            "      - Error messages in quotes or backticks — HIGHEST priority, grep these VERBATIM\n"
            "      - Function names (e.g. `markVolumeErrorState`) — grep for `func.*Name`\n"
            "      - File paths or package paths (e.g. `pkg/path/file.go`) — navigate directly\n"
            "      - GitHub URLs with line numbers — extract the path after `blob/` and jump there\n"
            "   b. Check .factory/reviews/study-output.md for the '=== Localization Hints ===' section\n"
            "      — it has pre-extracted file paths, function locations, and error sites\n"
            "   c. Run targeted grep:\n"
            "      ```\n"
            "      grep -rn \"exact error message\" --include=\"*.go\"   # highest signal\n"
            "      grep -rn \"func.*FunctionName\" --include=\"*.go\"    # find definitions\n"
            "      grep -rn \"FieldName\" --include=\"*.go\"             # find usages\n"
            "      ```\n"
            "   d. Read 50+ lines around the grep match to understand surrounding logic\n"
            "   e. Verify the file matches the issue description BEFORE editing\n\n"
            "   **STOP RULE:** If you have read >10 files without finding the bug location,\n"
            "   STOP exploring. Re-read the issue text for error messages, function names, or\n"
            "   URLs you missed. Then grep for those exact strings.\n\n"
            "3. **Implement the fix** — make the MINIMAL change that resolves the "
            "issue. Do NOT refactor, modernize, or add unrelated improvements. "
            "Fix ONLY the described bug.\n\n"
            "   **Multi-file changes:** When the issue says 'some code is omitted' or provides\n"
            "   pseudocode, the fix likely spans multiple files. Grep for functions being called\n"
            "   and verify they return the error type you're checking. If a function returns nil\n"
            "   instead of the error, fix THAT function first.\n\n"
            "   **Import collision prevention (Go):** Before adding an import, check if that\n"
            "   package name is already imported. If `errors` is already imported from stdlib,\n"
            "   alias the new one: `import apierrors \"k8s.io/apimachinery/pkg/api/errors\"`.\n\n"
            "4. **Run the project's own tests** — this is CRITICAL. Run the test "
            "suite to verify your fix works AND existing tests still pass.\n"
            "   - **Go projects:** FIRST run `go build ./...` to verify your change compiles. "
            "If it fails, fix the build error before proceeding. Then run "
            "`go test -v -count=1 ./...` or the specific package: "
            "`go test -v -count=1 ./pkg/path/to/package/...`\n"
            "   - **Python projects:** use pytest, tox, or the project's test runner.\n"
            "   - If specific test files are mentioned in the task, run those first.\n\n"
            "   - If tests fail after your fix, do NOT give up — analyze what the test expects:\n"
            "     1. Re-read the Gold Test Patch (step 1b) — it shows EXACTLY what the grading tests assert\n"
            "     2. Check the specific assertion: `t.Errorf(...)`, `assert.Equal(...)`, `require.Equal(...)`\n"
            "     3. If the test checks an error MESSAGE, check the EXACT wording expected\n"
            "     4. If the test checks a FIELD (e.g., `field.Invalid` vs `field.Required`), use that exact type\n"
            "     5. Adjust your implementation to match what the gold test patch asserts\n"
            "     6. If you cannot run the gold test (it will be applied by the grader), commit best attempt\n\n"
            "5. **Commit your changes — THIS IS MANDATORY** — commit directly on the current branch.\n"
            "   Use a clear commit message. CRITICAL RULES:\n"
            "   a. **Always commit something** — even if your tests fail, commit your best attempt.\n"
            "      An imperfect fix is better than no commit. The evaluation system will score\n"
            "      your change — do NOT revert if tests fail.\n"
            "   b. If tests fail after 2 attempts to fix, commit what you have with message:\n"
            "      'fix: attempt <description> (tests failing, committing best effort)'\n"
            "   c. NEVER use `git checkout` or `git restore` to undo your changes before committing.\n"
            "   d. After committing, verify with `git diff HEAD~1` that your changes are present.\n\n"
            "6. **Write a summary** — after committing, write a brief summary to "
            ".factory/reviews/builder-latest.md: which files changed, commit hash, "
            "test result.\n\n"
            "## Rules\n\n"
            "- MINIMAL fix only — smallest diff that resolves the issue\n"
            "- MUST run tests before committing — never commit untested code\n"
            "- Do NOT create branches or PRs — commit on current branch\n"
            "- Do NOT run factory commands (factory eval, factory study, etc.)\n"
            "- **ABSOLUTELY DO NOT modify test files** (`*_test.go`, `*_test.py`, etc.).\n"
            "  The verifier will REVERT any test file changes before grading.\n"
            "  Modifying test files guarantees reward=0. Even if a test seems broken, fix the\n"
            "  production code — do NOT edit the test.\n"
            "  Exception: only modify tests if the task explicitly says 'the bug is in the test'.\n"
            "- If tests fail after your fix, investigate and fix the issue\n"
            "- **NEVER leave an empty commit.** If you modified a file, it must be committed.\n"
            "  If `git status` shows no changes after your work, something went wrong — re-apply your fix.\n"
            "- Check for import conflicts before adding new imports — if a package "
            "is already imported, use the existing import or add an alias\n"
            "- After making changes, run `go build ./...` to verify compilation "
            "BEFORE running the full test suite\n"
            "- When the issue points to a specific line as 'the problem', verify if that line is the "
            "DECISION POINT or the ERROR SOURCE. If it's a switch/if routing on error type, the fix "
            "is in the functions that PRODUCE the errors — search upstream for the error sources.\n"
            "- When issue pseudocode shows the SAME pattern in multiple switch cases with "
            "'some code is omitted for brevity', grep for ALL call sites of the target "
            "function in the file and apply the fix at EVERY site — do not stop after the first.\n\n"
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
            "+  // check SyncFailedReason FIRST — counts not trustworthy when sync fails\n"
            "+  case condition != nil && condition.Status == metav1.ConditionFalse && len(condition.Message) > 0 && condition.Reason == policyv1.SyncFailedReason:\n"
            "+    msg = fmt.Sprintf(\"failed sync: %s\", condition.Message)\n"
            "+  case pdb.Status.CurrentHealthy <= pdb.Status.DesiredHealthy:\n"
            "+    msg = fmt.Sprintf(\"needs %d healthy, has %d\", pdb.Status.DesiredHealthy, pdb.Status.CurrentHealthy)\n"
            "+  case condition != nil && condition.Status == metav1.ConditionFalse && len(condition.Message) > 0:\n"
            "+    msg = fmt.Sprintf(\"does not allow evicting (%s): %s\", condition.Reason, condition.Message)\n"
            "+  default:\n"
            "+    msg = \"does not allow evicting pods currently\"\n"
            "+  }\n"
            "+  err.ErrStatus.Details.Causes = append(..., msg)\n"
            " }\n"
            "```\n\n"
            "### Example 4: Error type wrapping for transient failures (kubernetes)\n"
            "**Issue:** API server failures during volume operations cause volumes to be permanently "
            "marked failed. The issue points to operation_generator.go#L819 (decision point), "
            "but the fix is in csi_block.go (error sources).\n"
            "```diff\n"
            " if err != nil {\n"
            "-  return \"\", fmt.Errorf(\"failed to get NodeStageSecretRef: %v\", err)\n"
            "+  return \"\", volumetypes.NewTransientOperationFailure(log(\"failed to get NodeStageSecretRef: %v\", err))\n"
            " }\n"
            "```\n"
            "**Key insight:** When the issue points to a SYMPTOM location (line X has wrong behavior), "
            "the fix may be at the ERROR SOURCES — functions that return errors to that decision point. "
            "If line X is a switch/if routing on error type, search for ALL functions that produce errors "
            "it receives and apply the fix there.\n\n"
            "### Example 5: Multi-site identical fix (kubernetes)\n"
            "**Issue:** Issue pseudocode shows deleteObject() error handling added to BOTH switch cases.\n"
            "```diff\n"
            " // First call site\n"
            "-return gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)\n"
            "+err := gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)\n"
            "+if errors.IsNotFound(err) {\n"
            "+    gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)\n"
            "+    return enqueuedVirtualDeleteEventErr\n"
            "+}\n"
            "+return err\n"
            " // Second call site — SAME pattern applied\n"
            "-return gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)\n"
            "+err := gc.deleteObject(item.identity, latest.ResourceVersion, latest.OwnerReferences, &policy)\n"
            "+if errors.IsNotFound(err) {\n"
            "+    gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)\n"
            "+    return enqueuedVirtualDeleteEventErr\n"
            "+}\n"
            "+return err\n"
            "```\n"
            "**Key insight:** Apply the fix to ALL call sites in the function, not just the first match.\n\n"
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
