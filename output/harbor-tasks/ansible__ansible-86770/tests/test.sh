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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/ansible-galaxy-collection/tasks/build.yml test/units/galaxy/test_collection.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/galaxy/test_collection.py::test_build_files_manifest_sorted_by_name"]
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
