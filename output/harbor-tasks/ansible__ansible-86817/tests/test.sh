#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/play_arg_spec/tasks/main.yml b/test/integration/targets/play_arg_spec/tasks/main.yml
index 2d49cf6af4e9f3..6afca13080c74d 100644
--- a/test/integration/targets/play_arg_spec/tasks/main.yml
+++ b/test/integration/targets/play_arg_spec/tasks/main.yml
@@ -186,12 +186,12 @@
   vars:
     playbook_name: tagged_play
 
-- name: Test validation always runs otherwise
-  command: ansible-playbook {{ playbook }} --tags task_level_tag -e '"'"'required_str="success"'"'"'
+- name: Test validation only runs when the play tag runs
+  command: ansible-playbook {{ playbook }} --tags mismatch
   vars:
     playbook_name: tagged_play
   register: result
 
 - assert:
     that:
-      - result.stdout is search("Validating arguments against arg spec Tagged Play")
+      - result.stdout is not search("Validating arguments against arg spec Tagged Play")
diff --git a/test/integration/targets/play_iterator/playbook.meta.yml b/test/integration/targets/play_iterator/playbook.meta.yml
new file mode 100644
index 00000000000000..4f0a847feee763
--- /dev/null
+++ b/test/integration/targets/play_iterator/playbook.meta.yml
@@ -0,0 +1,3 @@
+argument_specs:
+  test:
+    options: {}
diff --git a/test/integration/targets/play_iterator/playbook.yml b/test/integration/targets/play_iterator/playbook.yml
index 76100c6089c896..3a4449c4c7800b 100644
--- a/test/integration/targets/play_iterator/playbook.yml
+++ b/test/integration/targets/play_iterator/playbook.yml
@@ -1,10 +1,15 @@
 ---
 - hosts: localhost
-  gather_facts: false
+  gather_facts: "{{ setup | default(False) }}"
+  validate_argspec: "{{ spec | default(omit) }}"
   tasks:
-    - name:
-      debug:
-        msg: foo
+    - name: "task 1"
+      fail:
+
     - name: "task 2"
       debug:
         msg: bar
+
+    - assert:
+        that: ansible_facts.gather_subset == ["all"]
+      when: setup | default(False)
diff --git a/test/integration/targets/play_iterator/runme.sh b/test/integration/targets/play_iterator/runme.sh
index 9f30d9e7a2f5f0..318ffd5e571ea2 100755
--- a/test/integration/targets/play_iterator/runme.sh
+++ b/test/integration/targets/play_iterator/runme.sh
@@ -3,3 +3,10 @@
 set -eux
 
 ansible-playbook playbook.yml --start-at-task '"'"'task 2'"'"' "$@"
+
+ansible-playbook playbook.yml --start-at-task '"'"'task 2'"'"' \
+    --extra-vars '"'"'setup="{{ True }}" spec="test"'"'"' "$@" | tee out.txt
+
+grep "TASK \[Gathering Facts\]" out.txt
+grep "TASK \[Validating arguments against arg spec test\]" out.txt
+grep "TASK \[task 2\]" out.txt
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/play_arg_spec/tasks/main.yml test/integration/targets/play_iterator/playbook.meta.yml test/integration/targets/play_iterator/playbook.yml test/integration/targets/play_iterator/runme.sh 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/integration/targets/play_iterator/runme.sh::start_at_task_with_setup_and_argspec", "test/integration/targets/play_arg_spec::tagged_play_validation_skipped_on_tag_mismatch"]

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

def parse_junit_xml(text):
    # Minimal XML parser for JUnit format (no lxml dependency)
    results = {}
    for m in re.finditer(r'<testcase[^>]*name="([^"]*)"[^>]*classname="([^"]*)"[^>]*(/?>)', text):
        name, classname, close = m.groups()
        test_id = f"{classname}.{name}"
        # Check for failure/error child elements
        if close == "/>":
            results[test_id] = "passed"
        else:
            # Find the matching </testcase> and check contents
            start = m.end()
            end = text.find("</testcase>", start)
            block = text[start:end] if end != -1 else ""
            if "<failure" in block or "<error" in block:
                results[test_id] = "failed"
            elif "<skipped" in block:
                results[test_id] = "skipped"
            else:
                results[test_id] = "passed"
    return results

def parse_cargo_test(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"test (\S+) \.\.\. (ok|FAILED|ignored)", line)
        if m:
            test_id = m.group(1)
            status = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

def parse_tap(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"(ok|not ok)\s+\d+\s*-?\s*(.*)", line)
        if m:
            status = "passed" if m.group(1) == "ok" else "failed"
            desc = m.group(2).strip()
            if "# SKIP" in desc:
                status = "skipped"
                desc = desc.split("# SKIP")[0].strip()
            results[desc] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
    "junit-xml": parse_junit_xml,
    "cargo-test": parse_cargo_test,
    "tap": parse_tap,
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
