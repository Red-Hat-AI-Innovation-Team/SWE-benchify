#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/filter_core/tasks/main.yml b/test/integration/targets/filter_core/tasks/main.yml
index c11b21c40c6330..0d982a7736d0d3 100644
--- a/test/integration/targets/filter_core/tasks/main.yml
+++ b/test/integration/targets/filter_core/tasks/main.yml
@@ -430,6 +430,13 @@
       - '"'"'123|ternary("seven", "eight") == "seven"'"'"'
       - '"'"'"haha"|ternary("seven", "eight") == "seven"'"'"'
 
+- name: Verify ternary does not evaluate unused values
+  assert:
+    that:
+      - (false | ternary(undefined_variable, '"'"'seven'"'"')) == (false | ternary(d.no_such_key, '"'"'seven'"'"'))
+  vars:
+    d: {}
+
 - name: Verify regex_escape raises on posix_extended (failure expected)
   set_fact:
     foo: '"'"'{{"]]^"|regex_escape(re_type="posix_extended")}}'"'"'
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/filter_core/tasks/main.yml 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/_internal/templating/test_ternary_lazy.py::TestTernaryLazyEvaluation::test_ternary_false_with_undefined_true_val", "test/units/_internal/templating/test_ternary_lazy.py::TestTernaryLazyEvaluation::test_ternary_true_with_undefined_false_val", "test/units/_internal/templating/test_ternary_lazy.py::TestTernaryLazyEvaluation::test_ternary_false_with_undefined_dict_key_true_val"]
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
