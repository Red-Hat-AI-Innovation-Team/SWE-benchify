#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/build.yml b/test/integration/targets/ansible-galaxy-collection/tasks/build.yml
index 83e9acc934f8ab..33709d75d8d136 100644
--- a/test/integration/targets/ansible-galaxy-collection/tasks/build.yml
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/build.yml
@@ -69,7 +69,9 @@
   command: ansible-galaxy collection build scratch/ansible_test/my_collection --force {{ galaxy_verbosity }}
   args:
     chdir: '"'"'{{ galaxy_dir }}'"'"'
-  register: build_existing_force
+  register:
+    build_existing_force: _task.result
+    artifact_path: build_existing_force.stdout_lines | select('"'"'search'"'"', '"'"'Created collection for ansible_test.my_collection at '"'"') | map('"'"'regex_replace'"'"', '"'"'.* at (.*)$'"'"', '"'"'\\1'"'"') | first
 
 - name: assert build existing collection
   assert:
@@ -77,6 +79,45 @@
     - '"'"'"use --force to re-create the collection artifact" in build_existing_no_force.stderr'"'"'
     - '"'"'"Created collection for ansible_test.my_collection" in build_existing_force.stdout'"'"'
 
+- name: Define extraction path
+  set_fact:
+    extraction_path: "{{ remote_tmp_dir }}/new_ansible_collections_extraction"
+
+- name: Ensure extraction directory exists
+  file:
+    path: "{{ extraction_path }}"
+    state: directory
+    mode: '"'"'0755'"'"'
+
+- name: Extract collection artifact
+  unarchive:
+    src: "{{ artifact_path }}"
+    dest: "{{ extraction_path }}"
+    remote_src: yes
+
+- name: Slurp FILES.json content
+  slurp:
+    src: "{{ extraction_path }}/FILES.json"
+  register:
+    decoded_files_json: _task.result.content | b64decode | from_json
+    files_names: decoded_files_json.files | map(attribute='"'"'name'"'"') | list
+
+- name: Assert that files are sorted in the predefined ASCII order
+  assert:
+    that:
+      - files_names == expected_files_order
+  vars:
+    expected_files_order: [
+      ".",
+      "README.md",
+      "docs",
+      "meta",
+      "meta/runtime.yml",
+      "plugins",
+      "plugins/README.md",
+      "roles"
+    ]
+
 - name: build collection containing ignored files
   command: ansible-galaxy collection build
   args:
@@ -97,3 +138,114 @@
     that:
     - item not in tar_output.stdout_lines
   loop: '"'"'{{ collection_ignored_directories }}'"'"'
+
+# Additional comprehensive tests for FILES.json sorting robustness
+- name: Clean up previous extraction for new tests
+  file:
+    path: "{{ extraction_path }}"
+    state: absent
+
+- name: Test multiple builds produce identical FILES.json - Build 1
+  command: ansible-galaxy collection build scratch/ansible_test/my_collection --force {{ galaxy_verbosity }}
+  args:
+    chdir: '"'"'{{ galaxy_dir }}'"'"'
+  register:
+    first_artifact: _task.result.stdout_lines | select('"'"'search'"'"', '"'"'Created collection for ansible_test.my_collection at '"'"') | map('"'"'regex_replace'"'"', '"'"'.* at (.*)$'"'"', '"'"'\\1'"'"') | first
+
+- name: Create directory for first extraction
+  file:
+    path: "{{ extraction_path }}_1"
+    state: directory
+    mode: '"'"'0755'"'"'
+
+- name: Extract first build
+  unarchive:
+    src: "{{ first_artifact }}"
+    dest: "{{ extraction_path }}_1"
+    remote_src: yes
+
+- name: Read FILES.json from first build
+  slurp:
+    src: "{{ extraction_path }}_1/FILES.json"
+  register:
+    first_files_content: _task.result.content | b64decode | from_json
+    first_order: first_files_content.files | map(attribute='"'"'name'"'"') | list
+
+- name: Remove first build artifact to ensure clean build
+  file:
+    path: "{{ first_artifact }}"
+    state: absent
+
+- name: Test multiple builds produce identical FILES.json - Build 2
+  command: ansible-galaxy collection build scratch/ansible_test/my_collection --force {{ galaxy_verbosity }}
+  args:
+    chdir: '"'"'{{ galaxy_dir }}'"'"'
+  register:
+    second_artifact: _task.result.stdout_lines | select('"'"'search'"'"', '"'"'Created collection for ansible_test.my_collection at '"'"') | map('"'"'regex_replace'"'"', '"'"'.* at (.*)$'"'"', '"'"'\\1'"'"') | first
+
+- name: Create directory for second extraction
+  file:
+    path: "{{ extraction_path }}_2"
+    state: directory
+    mode: '"'"'0755'"'"'
+
+- name: Extract second build
+  unarchive:
+    src: "{{ second_artifact }}"
+    dest: "{{ extraction_path }}_2"
+    remote_src: yes
+
+- name: Read FILES.json from second build
+  slurp:
+    src: "{{ extraction_path }}_2/FILES.json"
+  register:
+    second_files_content: _task.result.content | b64decode | from_json
+    second_order: second_files_content.files | map(attribute='"'"'name'"'"') | list
+
+- name: Verify FILES.json is reproducible across builds
+  assert:
+    that:
+      - first_files_content == second_files_content
+      - first_order == second_order
+
+- debug: var=first_order
+- debug:
+    var: "{{ item }}"
+  loop:
+    - first_order
+    - first_order | sort(case_sensitive=True)
+
+- name: Verify all files in order are ASCII sorted
+  assert:
+    that:
+      - first_order == (first_order | sort(case_sensitive=True))
+      - second_order == (second_order | sort(case_sensitive=True))
+
+- name: Validate FILES.json format and keys
+  assert:
+    that:
+      - first_files_content['"'"'format'"'"'] == 1
+      - second_files_content['"'"'format'"'"'] == 1
+      - first_files_content['"'"'files'"'"'] | length > 0
+      - second_files_content['"'"'files'"'"'] | length > 0
+
+- name: Verify each file entry has required fields
+  assert:
+    that:
+      - item | dict2items | map(attribute='"'"'key'"'"') | list | sort == [
+        '"'"'chksum_sha256'"'"',
+        '"'"'chksum_type'"'"',
+        '"'"'ftype'"'"',
+        '"'"'format'"'"',
+        '"'"'name'"'"'] | sort
+  loop: "{{ first_files_content['"'"'files'"'"'][1:] }}"  # Skip root directory entry
+  loop_control:
+    label: "{{ item.name }}"
+
+- name: Clean up extraction directories
+  file:
+    path: "{{ item }}"
+    state: absent
+  loop:
+    - "{{ extraction_path }}_1"
+    - "{{ extraction_path }}_2"
diff --git a/test/units/galaxy/test_collection.py b/test/units/galaxy/test_collection.py
index 8da860da28485f..13cf5bfe947cc8 100644
--- a/test/units/galaxy/test_collection.py
+++ b/test/units/galaxy/test_collection.py
@@ -841,6 +841,20 @@ def test_build_with_symlink_inside_collection(collection_input):
         assert actual_file == '"'"'08f24200b9fbe18903e7a50930c9d0df0b8d7da3'"'"'  # shasum test/units/cli/test_data/collection_skeleton/README.md
 
 
+def test_build_files_manifest_sorted_by_name(collection_input):
+    """Verify _build_files_manifest returns files sorted by name."""
+    input_dir = collection_input[0]
+
+    for filename in ['"'"'z.txt'"'"', '"'"'a.txt'"'"', '"'"'m.txt'"'"']:
+        with open(os.path.join(input_dir, filename), '"'"'w'"'"') as f:
+            f.write('"'"'test'"'"')
+
+    manifest = collection._build_files_manifest(to_bytes(input_dir), '"'"'namespace'"'"', '"'"'collection'"'"', [], Sentinel, None)
+    names = [entry['"'"'name'"'"'] for entry in manifest['"'"'files'"'"']]
+
+    assert names == sorted(names)
+
+
 def test_publish_no_wait(galaxy_server, collection_artifact, monkeypatch):
     mock_display = MagicMock()
     monkeypatch.setattr(Display, '"'"'display'"'"', mock_display)
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/ansible-galaxy-collection/tasks/build.yml test/units/galaxy/test_collection.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/galaxy/test_collection.py::test_build_files_manifest_sorted_by_name"]

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
