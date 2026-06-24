#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_utils.py b/test/test_utils.py
index c16b6b921e..a721c2a7cc 100644
--- a/test/test_utils.py
+++ b/test/test_utils.py
@@ -300,7 +300,7 @@ def test_template(template: str, output: str) -> None:
             id="query_function_call",
         ),
         pytest.param(
-            "{{ q('"'"'file'"'"', '"'"'config.txt'"'"') }}",
+            "{{ q('"'"'env'"'"', '"'"'HOME'"'"') }}",
             True,
             id="q_function_call",
         ),
@@ -310,10 +310,48 @@ def test_template(template: str, output: str) -> None:
             True,
             id="query_function_with_whitespace",
         ),
+        pytest.param(
+            "{{ some_function(lookup('"'"'env'"'"', '"'"'USER'"'"')) }}",
+            True,
+            id="nested_with_function",
+        ),
+        pytest.param(
+            "{{ (query)('"'"'env'"'"', '"'"'HOME'"'"') }}",
+            True,
+            id="query_with_parentheses",
+        ),
+        pytest.param(
+            "{{ (q)('"'"'env'"'"', '"'"'HOME'"'"') }}",
+            True,
+            id="q_with_parentheses",
+        ),
+        pytest.param(
+            "{{ '"'"'This string contains lookup but not a call'"'"' }}",
+            False,
+            id="lookup_in_string",
+        ),
+        pytest.param(
+            "{{ query_result }}",
+            False,
+            id="query_variable_name",
+        ),
+        pytest.param(
+            "{{ my_dict.lookup }}",
+            False,
+            id="lookup_as_attribute",
+        ),
     ),
 )
 def test_template_lookup_behavior(template: str, has_lookup: bool) -> None:
     """Test template behavior for both ansible-core >= 2.19 and < 2.19."""
+    # Use the lookup detection function directly
+    detected_lookup = utils.has_lookup_function_calls(template)
+    assert detected_lookup == has_lookup, (
+        f"Expected has_lookup_function_calls({template!r}) to return {has_lookup}, "
+        f"but got {detected_lookup}"
+    )
+
+    # Then test template behavior
     result = utils.template(
         basedir=Path("/base/dir"),
         value=template,
@@ -331,11 +369,6 @@ def test_template_lookup_behavior(template: str, has_lookup: bool) -> None:
         assert result == template, (
             f"Expected lookup to be skipped for ansible-core >= 2.19, but got: {result}"
         )
-    elif not has_lookup:
-        # Normal templates should always be processed
-        assert result != template, (
-            f"Expected normal template to be processed, but got unchanged: {result}"
-        )
 
 
 def test_task_to_str_unicode() -> None:
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/test_utils.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/test_utils.py::test_template_lookup_behavior[file_lookup]", "test/test_utils.py::test_template_lookup_behavior[lookup_with_text]", "test/test_utils.py::test_template_lookup_behavior[query_function_call]", "test/test_utils.py::test_template_lookup_behavior[q_function_call]", "test/test_utils.py::test_template_lookup_behavior[query_function_with_whitespace]", "test/test_utils.py::test_template_lookup_behavior[nested_with_function]", "test/test_utils.py::test_template_lookup_behavior[query_with_parentheses]", "test/test_utils.py::test_template_lookup_behavior[q_with_parentheses]", "test/test_utils.py::test_template_lookup_behavior[lookup_in_string]", "test/test_utils.py::test_template_lookup_behavior[query_variable_name]", "test/test_utils.py::test_template_lookup_behavior[lookup_as_attribute]"]
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
