#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_app.py b/test/test_app.py
index 1a34458fef..a9a2ada805 100644
--- a/test/test_app.py
+++ b/test/test_app.py
@@ -75,3 +75,63 @@ def test_app_fixed_violations_coverage(tmp_path: Path) -> None:
     exit_code = app.report_outcome(result)
 
     assert exit_code == RC.FIXED_VIOLATIONS
+
+
+def test_ignore_file_with_skip_and_strict(tmp_path: Path) -> None:
+    """Test that .ansible-lint-ignore with skip qualifier returns exit code 0 with --strict.
+
+    When all violations are skipped using '"'"'skip'"'"' in .ansible-lint-ignore,
+    the exit code should be 0, even with --strict flag.
+    """
+    lintable = Lintable(tmp_path / "test.yml")
+    lintable.content = "bad_indentation:\n- blah: plop\n  zz: 42\n"
+    lintable.write(force=True)
+
+    # Create ignore file with skip qualifier
+    ignore_file = tmp_path / ".ansible-lint-ignore"
+    ignore_file.write_text("test.yml yaml[indentation] skip")
+
+    result = run_ansible_lint(lintable.filename, "--strict", cwd=tmp_path)
+
+    # Should return 0 because all violations are skipped
+    assert result.returncode == RC.SUCCESS
+
+
+def test_ignore_file_without_skip_and_strict(tmp_path: Path) -> None:
+    """Test that .ansible-lint-ignore without skip qualifier returns exit code 2 with --strict.
+
+    When violations are ignored (but not skipped) in .ansible-lint-ignore,
+    they should be treated as warnings, and --strict should cause exit code 2.
+    """
+    lintable = Lintable(tmp_path / "test.yml")
+    lintable.content = "bad_indentation:\n- blah: plop\n  zz: 42\n"
+    lintable.write(force=True)
+
+    # Create ignore file without skip qualifier
+    ignore_file = tmp_path / ".ansible-lint-ignore"
+    ignore_file.write_text("test.yml yaml[indentation]")
+
+    result = run_ansible_lint(lintable.filename, "--strict", cwd=tmp_path)
+
+    # Should return 2 because there'"'"'s a warning and we'"'"'re in strict mode
+    assert result.returncode == RC.VIOLATIONS_FOUND
+
+
+def test_skip_list_and_strict(tmp_path: Path) -> None:
+    """Test that skip_list returns exit code 0 with --strict.
+
+    When all rules generating violations are skipped using '"'"'skip_list'"'"',
+    the exit code should be 0, even with --strict flag.
+    """
+    lintable = Lintable(tmp_path / "test.yml")
+    lintable.content = "bad_indentation:\n- blah: plop\n  zz: 42\n"
+    lintable.write(force=True)
+
+    # Create config file with skip_list
+    config_file = tmp_path / ".ansible-lint"
+    config_file.write_text("skip_list:\n  - yaml[indentation]\n")
+
+    result = run_ansible_lint(lintable.filename, "--strict", cwd=tmp_path)
+
+    # Should return 0 because rule is in skip_list
+    assert result.returncode == RC.SUCCESS
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/test_app.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/test_app.py::test_ignore_file_with_skip_and_strict"]
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
