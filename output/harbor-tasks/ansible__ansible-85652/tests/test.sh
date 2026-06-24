#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/apt_repository/tasks/apt.yml b/test/integration/targets/apt_repository/tasks/apt.yml
index 9d51e16e4bdba7..f1706ea0302595 100644
--- a/test/integration/targets/apt_repository/tasks/apt.yml
+++ b/test/integration/targets/apt_repository/tasks/apt.yml
@@ -301,7 +301,7 @@
 - assert:
     that:
       - result is failed
-      - result.msg.startswith("argument '"'"'repo'"'"' is of type NoneType and we were unable to convert to str")
+      - result.msg == '"'"'Please set argument \'"'"'repo\'"'"' to a non-empty value'"'"'
 
 - name: Test apt_repository with an empty value for repo
   apt_repository:
diff --git a/test/integration/targets/roles_arg_spec/test.yml b/test/integration/targets/roles_arg_spec/test.yml
index 73f797140e4129..2c24fc481d3d69 100644
--- a/test/integration/targets/roles_arg_spec/test.yml
+++ b/test/integration/targets/roles_arg_spec/test.yml
@@ -188,29 +188,6 @@
     c_list: []
     c_raw: ~
   tasks:
-    - name: test type coercion fails on None for required str
-      block:
-        - name: "Test import_role of role C (missing a_str)"
-          import_role:
-            name: c
-          vars:
-            a_str: ~
-        - fail:
-            msg: "Should not get here"
-      rescue:
-        - debug:
-            var: ansible_failed_result
-        - name: "Validate import_role failure"
-          assert:
-            that:
-              # NOTE: a bug here that prevents us from getting ansible_failed_task
-              - ansible_failed_result.argument_errors == [error]
-              - ansible_failed_result.argument_spec_data == a_main_spec
-          vars:
-            error: >-
-              argument '"'"'a_str'"'"' is of type NoneType and we were unable to convert to str:
-              '"'"'None'"'"' is not a string and conversion is not allowed
-
     - name: test type coercion fails on None for required int
       block:
         - name: "Test import_role of role C (missing c_int)"
diff --git a/test/units/_internal/templating/test_templar.py b/test/units/_internal/templating/test_templar.py
index c062d3f6b53650..9d6a193c6f95be 100644
--- a/test/units/_internal/templating/test_templar.py
+++ b/test/units/_internal/templating/test_templar.py
@@ -1080,6 +1080,16 @@ def test_marker_from_test_plugin() -> None:
         assert TemplateEngine(variables=dict(something=TRUST.tag("{{ nope }}"))).template(TRUST.tag("{{ (something is eq {}) is undefined }}"))
 
 
+@pytest.mark.parametrize("template,expected", (
+    ("{{ none }}", None),  # concat sees one node, NoneType result is preserved
+    ("{% if False %}{% endif %}", None),  # concat sees one node, NoneType result is preserved
+    ("{{'"'"''"'"'}}{% if False %}{% endif %}", ""),  # multiple blocks with an embedded None result, concat is in play, the result is an empty string
+    ("hey {{ none }}", "hey "),  # composite template, the result is an empty string
+))
+def test_none_concat(template: str, expected: object) -> None:
+    assert TemplateEngine().template(TRUST.tag(template)) == expected
+
+
 def test_filter_generator() -> None:
     """Verify that filters which return a generator are converted to a list while under the filter'"'"'s JinjaCallContext."""
     variables = dict(
diff --git a/test/units/module_utils/common/validation/test_check_type_str.py b/test/units/module_utils/common/validation/test_check_type_str.py
index 4381ad1fd04fff..8ea8b23a0e079e 100644
--- a/test/units/module_utils/common/validation/test_check_type_str.py
+++ b/test/units/module_utils/common/validation/test_check_type_str.py
@@ -12,6 +12,7 @@
 
 TEST_CASES = (
     ('"'"'string'"'"', '"'"'string'"'"'),
+    (None, '"'"''"'"',),  # 2.19+ relaxed restriction on None<->empty for backward compatibility
     (100, '"'"'100'"'"'),
     (1.5, '"'"'1.5'"'"'),
     ({'"'"'k1'"'"': '"'"'v1'"'"'}, "{'"'"'k1'"'"': '"'"'v1'"'"'}"),
@@ -25,7 +26,7 @@ def test_check_type_str(value, expected):
     assert expected == check_type_str(value)
 
 
-@pytest.mark.parametrize('"'"'value, expected'"'"', TEST_CASES[1:])
+@pytest.mark.parametrize('"'"'value, expected'"'"', TEST_CASES[2:])
 def test_check_type_str_no_conversion(value, expected):
     with pytest.raises(TypeError) as e:
         _check_type_str_no_conversion(value)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/apt_repository/tasks/apt.yml test/integration/targets/roles_arg_spec/test.yml test/units/_internal/templating/test_templar.py test/units/module_utils/common/validation/test_check_type_str.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/_internal/templating/test_templar.py::test_none_concat[hey {{ none }}-hey ]", "test/units/module_utils/common/validation/test_check_type_str.py::test_check_type_str[None-]"]

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
