#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_with_skip_tagid.py b/test/test_with_skip_tagid.py
index fef50a0f82..61a40d99f7 100644
--- a/test/test_with_skip_tagid.py
+++ b/test/test_with_skip_tagid.py
@@ -71,3 +71,12 @@ def test_run_skip_rule() -> None:
     )
     assert result.returncode == 0
     assert not result.stdout
+
+
+def test_skip_specific_subrule(collection: RulesCollection) -> None:
+    """Verify skipping one yaml subrule does not skip others."""
+    lintable = "examples/playbooks/with-multiple-yaml-violations.yml"
+    errs = Runner(lintable, rules=collection, skip_list=["yaml[trailing-spaces]"]).run()
+    found_tags = {e.tag for e in errs}
+    assert "yaml[trailing-spaces]" not in found_tags
+    assert "yaml[colons]" in found_tags
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/test_with_skip_tagid.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/test_with_skip_tagid.py::test_skip_specific_subrule"]
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
