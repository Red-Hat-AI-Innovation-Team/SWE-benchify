#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/copy/files/subdir_with_deep_single_file/dir/file.txt b/test/integration/targets/copy/files/subdir_with_deep_single_file/dir/file.txt
new file mode 100644
index 00000000000000..e69de29bb2d1d6
diff --git a/test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml b/test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml
new file mode 100644
index 00000000000000..e5ce4c6b20eb22
--- /dev/null
+++ b/test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml
@@ -0,0 +1,29 @@
+# Test copying to a source directory that contains only a single file in a deeper structure
+
+- name: Ensure that dest top directory doesn'"'"'t exist
+  file:
+    path: '"'"'{{ remote_dir }}/subdir_with_deep_single_file'"'"'
+    state: absent
+
+- name: Copy subdir_with_deep_single_file directory which contains a single file
+  copy:
+    src: subdir_with_deep_single_file
+    dest: '"'"'{{ remote_dir }}'"'"'
+  register: copy_result
+
+- name: Debug copy result
+  debug:
+    var: copy_result
+    verbosity: 1
+
+- name: Check the transferred file
+  stat:
+    path: '"'"'{{ remote_dir }}/subdir_with_deep_single_file/dir/file.txt'"'"'
+  register: stat_file
+
+- name: Assert that transferred file exists and copy_result is as expected for deeper structure
+  assert:
+    that:
+      - '"'"'stat_file.stat.exists'"'"'
+      - '"'"'copy_result.changed'"'"'
+      - '"'"'copy_result.dest == remote_dir + "/subdir_with_deep_single_file/dir/file.txt"'"'"'
diff --git a/test/integration/targets/copy/tasks/tests.yml b/test/integration/targets/copy/tasks/tests.yml
index 44067ae319ffc7..318db1ea2c36b3 100644
--- a/test/integration/targets/copy/tasks/tests.yml
+++ b/test/integration/targets/copy/tasks/tests.yml
@@ -2531,3 +2531,5 @@
         state: absent
       loop:
         - '"'"'{{ remote_file }}'"'"'
+
+- include_tasks: src_directory_contaning_one_single_file.yml
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml test/integration/targets/copy/tasks/tests.yml 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/integration/targets/copy/tasks/src_directory_contaning_one_single_file.yml::Assert that transferred file exists and copy_result is as expected for deeper structure"]

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
