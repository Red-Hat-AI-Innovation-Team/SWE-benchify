#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/test_rules_collection.py b/test/test_rules_collection.py
index e43cb1a4cc..591ae10327 100644
--- a/test/test_rules_collection.py
+++ b/test/test_rules_collection.py
@@ -179,3 +179,48 @@ def test_rules_id_format(config_options: Options, app: App) -> None:
     assert "yaml" in keys, "yaml rule is missing"
     assert len(rules) == 51  # update this number when adding new rules!
     assert len(keys) == len(rules), "Duplicate rule ids?"
+
+
+def test_tag_inclusion(
+    test_rules_collection: RulesCollection,
+    ematchtestfile: Lintable,
+) -> None:
+    """Test that bracketed sub-tags are treated surgically for inclusion."""
+    all_matches = test_rules_collection.run(ematchtestfile)
+
+    if not all_matches:
+        pytest.fail("No matches found in ematchtestfile!")
+
+    target_tag = all_matches[0].tag
+    matches = test_rules_collection.run(ematchtestfile, tags={target_tag})
+
+    assert len(matches) > 0
+    for m in matches:
+        assert m.tag == target_tag
+
+
+def test_tag_exclusion(
+    test_rules_collection: RulesCollection,
+    ematchtestfile: Lintable,
+) -> None:
+    """Test that bracketed sub-tags are treated surgically for exclusion."""
+    target_tag = "TEST0001[BANNED]"
+
+    matches = test_rules_collection.run(ematchtestfile, skip_list=[target_tag])
+
+    tag_results = [m.tag for m in matches]
+    assert target_tag not in tag_results
+
+
+def test_category_tag_override(
+    test_rules_collection: RulesCollection,
+    ematchtestfile: Lintable,
+) -> None:
+    """Test that specific sub-tag requests override broad category inclusion."""
+    matches = test_rules_collection.run(
+        ematchtestfile, tags={"test1", "TEST0001[BANNED]"}
+    )
+
+    for m in matches:
+        if m.rule.id == "TEST0001":
+            assert m.tag == "TEST0001[BANNED]"
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/test_rules_collection.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/test_rules_collection.py::test_category_tag_override"]
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
