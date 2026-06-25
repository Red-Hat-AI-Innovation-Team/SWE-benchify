#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_file_utils.py b/test/test_file_utils.py
index ea6d34ccb7..87b0a0181d 100644
--- a/test/test_file_utils.py
+++ b/test/test_file_utils.py
@@ -18,6 +18,7 @@
     expand_path_vars,
     expand_paths_vars,
     find_project_root,
+    kind_from_path,
     normpath,
     normpath_path,
 )
@@ -543,3 +544,55 @@ def test_bug_2513(
         results = Runner(filename, rules=default_rules_collection).run()
         assert len(results) == 1
         assert results[0].rule.id == "name"
+
+
+def test_kind_from_path_parent_collision(tmp_path: Path) -> None:
+    """Verify that a parent directory named '"'"'tasks'"'"' doesn'"'"'t cause false positives.
+
+    See https://github.com/ansible/ansible-lint/issues/4763
+    """
+    tasks_parent = tmp_path / "tasks"
+    project_dir = tasks_parent / "my_project"
+    project_dir.mkdir(parents=True)
+
+    (project_dir / ".git").mkdir()
+
+    playbook_path = project_dir / "site.yml"
+    playbook_path.touch()
+
+    kind = kind_from_path(playbook_path)
+
+    assert kind != "tasks", f"File {playbook_path} should not be identified as '"'"'tasks'"'"'"
+
+
+def test_kind_from_path_valid_tasks(tmp_path: Path) -> None:
+    """Verify that legitimate tasks directories are still correctly identified."""
+    project_dir = tmp_path / "my_project"
+    project_dir.mkdir()
+    (project_dir / ".git").mkdir()
+
+    task_dir = project_dir / "tasks"
+    task_dir.mkdir()
+    task_path = task_dir / "main.yml"
+    task_path.touch()
+
+    kind = kind_from_path(task_path)
+
+    assert kind == "tasks", f"File {task_path} should be identified as '"'"'tasks'"'"'"
+
+
+def test_kind_from_path_outside_project_root(tmp_path: Path) -> None:
+    """Verify fallback to absolute path when file is outside the project root.
+
+    This triggers the except block in kind_from_path
+    """
+    project_dir = tmp_path / "actual_project"
+    project_dir.mkdir()
+    (project_dir / ".git").mkdir()
+
+    outside_file = tmp_path / "external_file.yml"
+    outside_file.touch()
+
+    kind = kind_from_path(outside_file)
+
+    assert kind == "yaml"
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/test_file_utils.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/test_file_utils.py::test_kind_from_path_parent_collision"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="pytest-verbose" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
