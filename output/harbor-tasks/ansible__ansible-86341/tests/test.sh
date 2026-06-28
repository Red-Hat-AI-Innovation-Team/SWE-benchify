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

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/ansible-galaxy-collection/tasks/list.yml test/units/cli/galaxy/test_execute_list_collection.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/cli/galaxy/test_execute_list_collection.py::test_execute_list_collection_no_valid_paths"]

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
