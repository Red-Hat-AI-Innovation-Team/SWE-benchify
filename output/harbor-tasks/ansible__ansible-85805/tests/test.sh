#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/handlers/runme.sh b/test/integration/targets/handlers/runme.sh
index 648eb87bb91e76..51097192aeb428 100755
--- a/test/integration/targets/handlers/runme.sh
+++ b/test/integration/targets/handlers/runme.sh
@@ -229,6 +229,13 @@ ansible-playbook handler_notify_earlier_handler.yml "$@" 2>&1 | tee out.txt
 
 ANSIBLE_DEBUG=1 ansible-playbook tagged_play.yml --skip-tags the_whole_play "$@" 2>&1 | tee out.txt
 [ "$(grep out.txt -ce '"'"'META: triggered running handlers'"'"')" = "0" ]
+[ "$(grep out.txt -ce '"'"'No handler notifications for'"'"')" = "0" ]
 [ "$(grep out.txt -ce '"'"'handler_ran'"'"')" = "0" ]
+[ "$(grep out.txt -ce '"'"'handler1_ran'"'"')" = "0" ]
 
 ansible-playbook rescue_flush_handlers.yml "$@"
+
+ANSIBLE_DEBUG=1 ansible-playbook tagged_play.yml --tags task_tag "$@" 2>&1 | tee out.txt
+[ "$(grep out.txt -ce '"'"'META: triggered running handlers'"'"')" = "1" ]
+[ "$(grep out.txt -ce '"'"'handler_ran'"'"')" = "0" ]
+[ "$(grep out.txt -ce '"'"'handler1_ran'"'"')" = "1" ]
diff --git a/test/integration/targets/handlers/tagged_play.yml b/test/integration/targets/handlers/tagged_play.yml
index e96348dcd12794..8c209faaef1e53 100644
--- a/test/integration/targets/handlers/tagged_play.yml
+++ b/test/integration/targets/handlers/tagged_play.yml
@@ -2,9 +2,19 @@
   gather_facts: false
   tags: the_whole_play
   tasks:
-    - command: echo
+    - debug:
+      changed_when: true
       notify: h
+
+    - debug:
+      changed_when: true
+      notify: h1
+      tags: task_tag
   handlers:
     - name: h
       debug:
         msg: handler_ran
+
+    - name: h1
+      debug:
+        msg: handler1_ran
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/handlers/runme.sh test/integration/targets/handlers/tagged_play.yml 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/integration/targets/handlers/runme.sh::tagged_play.yml --tags task_tag::META_triggered_running_handlers_eq_1", "test/integration/targets/handlers/runme.sh::tagged_play.yml --tags task_tag::handler1_ran_eq_1"]

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
