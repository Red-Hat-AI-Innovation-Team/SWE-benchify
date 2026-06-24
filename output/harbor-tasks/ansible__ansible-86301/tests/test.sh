#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/deprecations/injectfacts.yml b/test/integration/targets/deprecations/injectfacts.yml
index 7e356e2e3a2b6b..d5110dfe106814 100644
--- a/test/integration/targets/deprecations/injectfacts.yml
+++ b/test/integration/targets/deprecations/injectfacts.yml
@@ -3,3 +3,6 @@
   tasks:
   - debug:
       msg: '"'"'{{ansible_distribution}}'"'"'
+  - debug:
+      msg: '"'"'{{ansible_local}}'"'"'
+    tags: alocal
diff --git a/test/integration/targets/deprecations/runme.sh b/test/integration/targets/deprecations/runme.sh
index 97857102564bfc..4f8a74f1561f38 100755
--- a/test/integration/targets/deprecations/runme.sh
+++ b/test/integration/targets/deprecations/runme.sh
@@ -59,3 +59,6 @@ export ANSIBLE_CACHE_PLUGIN=notjsonfile
 
 # Injection default is deprecated
 [ "$(ANSIBLE_INJECT_FACT_VARS=1 ansible-playbook injectfacts.yml 2>&1 | grep -c '"'"'INJECT_FACTS_AS_VARS'"'"')" -eq "0" ]
+
+# Injection default is deprecated but not ansible_local
+[ "$(ansible-playbook injectfacts.yml --tags alocal 2>&1 | grep -c '"'"'INJECT_FACTS_AS_VARS'"'"')" -eq "0" ]
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/deprecations/injectfacts.yml test/integration/targets/deprecations/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/integration/targets/deprecations/runme.sh::ansible_local_no_inject_facts_deprecation"]
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
