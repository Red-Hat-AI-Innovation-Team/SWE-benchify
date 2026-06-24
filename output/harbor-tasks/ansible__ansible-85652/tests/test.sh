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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/apt_repository/tasks/apt.yml test/integration/targets/roles_arg_spec/test.yml test/units/_internal/templating/test_templar.py test/units/module_utils/common/validation/test_check_type_str.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/_internal/templating/test_templar.py::test_none_concat[hey {{ none }}-hey ]", "test/units/module_utils/common/validation/test_check_type_str.py::test_check_type_str[None-]"]
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
