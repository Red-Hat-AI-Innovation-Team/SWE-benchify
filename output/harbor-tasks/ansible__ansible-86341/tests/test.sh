#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/list.yml b/test/integration/targets/ansible-galaxy-collection/tasks/list.yml
index 159d139adf01dd..595323b7823acf 100644
--- a/test/integration/targets/ansible-galaxy-collection/tasks/list.yml
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/list.yml
@@ -152,14 +152,13 @@
 - name: test that no json is emitted when no collection paths are usable
   command: "ansible-galaxy collection list --format json"
   register: list_result_error
-  ignore_errors: True
   environment:
     ANSIBLE_COLLECTIONS_PATH: "i_dont_exist"
 
-- name: Ensure we get the expected error
+- name: Ensure we get the expected warning
   assert:
     that:
-      - "'"'"'{}'"'"' not in list_result_error.stdout"
+      - "'"'"'{}'"'"' in list_result_error.stdout"
       - "'"'"'None of the provided paths were usable'"'"' in list_result_error.stderr"
 
 - name: install an artifact to the second collections path
diff --git a/test/units/cli/galaxy/test_execute_list_collection.py b/test/units/cli/galaxy/test_execute_list_collection.py
index d7bc3cdeddc055..b468be6a8aae27 100644
--- a/test/units/cli/galaxy/test_execute_list_collection.py
+++ b/test/units/cli/galaxy/test_execute_list_collection.py
@@ -11,7 +11,7 @@
 from ansible import constants as C
 from ansible import context
 from ansible.cli.galaxy import GalaxyCLI
-from ansible.errors import AnsibleError, AnsibleOptionsError
+from ansible.errors import AnsibleError
 from ansible.galaxy import collection
 from ansible.galaxy.dependency_resolution.dataclasses import Requirement
 from ansible.module_utils.common.text.converters import to_native
@@ -201,12 +201,12 @@ def test_execute_list_collection_no_valid_paths(mocker, capsys, tmp_path_factory
     tmp_path = tmp_path_factory.mktemp('"'"'test-ÅÑŚÌβŁÈ Collections'"'"')
     concrete_artifact_cm = collection.concrete_artifact_manager.ConcreteArtifactsManager(tmp_path, validate_certs=False)
 
-    with pytest.raises(AnsibleOptionsError, match=r'"'"'None of the provided paths were usable.'"'"'):
-        gc.execute_list_collection(artifacts_manager=concrete_artifact_cm)
+    gc.execute_list_collection(artifacts_manager=concrete_artifact_cm)
 
     out, err = capsys.readouterr()
 
     assert '"'"'[WARNING]: - the configured path'"'"' in err
+    assert '"'"'[WARNING]: None of the provided paths were usable'"'"' in err
     assert '"'"'exists, but it is not a directory.'"'"' in err
 
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/ansible-galaxy-collection/tasks/list.yml test/units/cli/galaxy/test_execute_list_collection.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/cli/galaxy/test_execute_list_collection.py::test_execute_list_collection_no_valid_paths"]
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
