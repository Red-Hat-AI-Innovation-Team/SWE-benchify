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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/test_file_utils.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/test_file_utils.py::test_kind_from_path_parent_collision"]
passed = set()

with open("/tmp/test_output.txt") as f:
    for line in f:
        # pytest output: "PASSED" or "FAILED" after the test ID
        m = re.match(r"^(.+?)\s+PASSED", line)
        if m:
            passed.add(m.group(1).strip())

# Also check for the short form "test_name PASSED"
# and pytest's "X passed" summary
all_pass = True
for t in f2p:
    # Check exact match or suffix match
    if t not in passed:
        # Try matching just the test function part
        found = any(t.endswith(p.split("::")[-1]) or p.endswith(t.split("::")[-1]) for p in passed)
        if not found:
            all_pass = False

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    print(f"NOT RESOLVED: some FAIL_TO_PASS tests still failing")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
