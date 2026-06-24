#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/ansible-galaxy-collection-scm/tasks/download.yml b/test/integration/targets/ansible-galaxy-collection-scm/tasks/download.yml
index 6b52bd1dd2187f..6cad21c121a4b1 100644
--- a/test/integration/targets/ansible-galaxy-collection-scm/tasks/download.yml
+++ b/test/integration/targets/ansible-galaxy-collection-scm/tasks/download.yml
@@ -12,11 +12,16 @@
   args:
     chdir: '"'"'{{ galaxy_dir }}/download'"'"'
   register: download_collection
+  # TODO: remove external dependencies and define requires_ansible based on the current version
+  environment:
+    ANSIBLE_COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH: ignore
 
 - name: check that the amazon.aws collection was downloaded
   stat:
     path: '"'"'{{ galaxy_dir }}/download/collections/amazon-aws-1.0.0.tar.gz'"'"'
   register: download_collection_amazon_actual
+  environment:
+    ANSIBLE_COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH: ignore
 
 - name: check that the awx.awx collection was downloaded
   stat:
@@ -34,6 +39,8 @@
   command: '"'"'ansible-galaxy collection install -r requirements.yml --no-deps'"'"'
   args:
     chdir: '"'"'{{ galaxy_dir }}/download/collections/'"'"'
+  environment:
+    ANSIBLE_COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH: ignore
 
 - name: list installed collections
   command: '"'"'ansible-galaxy collection list'"'"'
diff --git a/test/integration/targets/ansible-galaxy-collection/library/setup_collections.py b/test/integration/targets/ansible-galaxy-collection/library/setup_collections.py
index 1a075798023bb5..9d94f1c09fbaa2 100644
--- a/test/integration/targets/ansible-galaxy-collection/library/setup_collections.py
+++ b/test/integration/targets/ansible-galaxy-collection/library/setup_collections.py
@@ -55,6 +55,16 @@
         - The dependencies of the collection.
         type: dict
         default: '"'"'{}'"'"'
+      use_symlink:
+        description:
+        - Create a symlink in the collection.
+        type: bool
+        default: False
+      runtime:
+        description:
+        - File content for meta/runtime.yml.
+        type: str
+        default: '"'"'requires_ansible: ">=2.9"'"'"'
 author:
 - Jordan Borean (@jborean93)
 """
@@ -100,6 +110,7 @@ def publish_collection(module, collection):
     version = collection['"'"'version'"'"']
     dependencies = collection['"'"'dependencies'"'"']
     use_symlink = collection['"'"'use_symlink'"'"']
+    runtime = collection['"'"'runtime'"'"']
 
     result = {}
     collection_dir = os.path.join(module.tmpdir, "%s-%s-%s" % (namespace, name, version))
@@ -123,7 +134,7 @@ def publish_collection(module, collection):
     with open(os.path.join(b_collection_dir, b'"'"'galaxy.yml'"'"'), mode='"'"'wb'"'"') as fd:
         fd.write(to_bytes(yaml.safe_dump(galaxy_meta), errors='"'"'surrogate_or_strict'"'"'))
     with open(os.path.join(b_collection_dir, b'"'"'meta/runtime.yml'"'"'), mode='"'"'wb'"'"') as fd:
-        fd.write(b'"'"'requires_ansible: ">=1.0.0"'"'"')
+        fd.write(to_bytes(runtime))
 
     with tempfile.NamedTemporaryFile(mode='"'"'wb'"'"') as temp_fd:
         temp_fd.write(b"data")
@@ -238,6 +249,7 @@ def run_module():
                 version=dict(type='"'"'str'"'"', default='"'"'1.0.0'"'"'),
                 dependencies=dict(type='"'"'dict'"'"', default={}),
                 use_symlink=dict(type='"'"'bool'"'"', default=False),
+                runtime=dict(type='"'"'str'"'"', default='"'"'requires_ansible: ">=2.9"'"'"'),
             ),
         ),
         signature_dir=dict(type='"'"'path'"'"', default=None),
diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/check_requires_ansible.yml b/test/integration/targets/ansible-galaxy-collection/tasks/check_requires_ansible.yml
new file mode 100644
index 00000000000000..7c180381aa6db1
--- /dev/null
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/check_requires_ansible.yml
@@ -0,0 +1,138 @@
+- environment:
+    ANSIBLE_NOCOLOR: True
+    ANSIBLE_FORCE_COLOR: false
+  vars:
+    test_base_dir: "{{ [remote_tmp_dir, '"'"'requires_ansible_'"'"' ~ subcommand] | path_join }}"
+    temp1: "{{ [test_base_dir, '"'"'collections'"'"'] | path_join }}"
+    temp2: "{{ [test_base_dir, '"'"'other_collections'"'"'] | path_join }}"
+    install_or_download: "ansible-galaxy collection {{ subcommand }}{{ (subcommand == '"'"'install'"'"') | ternary('"'"' --force-with-deps'"'"', '"'"''"'"')}}"
+    failed_error: |
+        \[ERROR\]: Failed to resolve the requested dependencies map\. Could not satisfy the following requirements:
+        \* ns_requires_ansible\.name_requires_ansible:1\.0\.0 \(direct request\) requires ansible-core <1\.1
+    hint: >-
+        Hint: To disregard whether the collection supports the current version
+        of ansible-core, configure COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH as "ignore"
+    undocumented_warning: >-
+      \[WARNING\]: ns_requires_ansible\.name_requires_ansible:.* does not have requires_ansible metadata.
+  block:
+  - name: "{{ subcommand }} incompatible collection"
+    command: "{{ install_or_download }} -p {{ temp1 }} ns_requires_ansible.name_requires_ansible"
+    register: expected_fail
+    failed_when: expected_fail is success
+
+  - assert:
+      that:
+        - expected_fail.stderr is search(failed_error, multiline=True)
+        - expected_fail.stderr is search(hint)
+
+  - name: "{{ subcommand }} specific version of incompatible collection"
+    command: "{{ install_or_download }} -p {{ temp1 }} '"'"'ns_requires_ansible.name_requires_ansible:1.0.0'"'"'"
+    register: expected_fail
+    failed_when: expected_fail is success
+
+  - assert:
+      that:
+        - expected_fail.stderr is search(failed_error, multiline=True)
+        - expected_fail.stderr is search(hint)
+
+  - name: Download incompatible tarfile for tarfile tests
+    command: ansible-galaxy collection download -p {{ temp1 }} ns_requires_ansible.name_requires_ansible
+    environment:
+      ANSIBLE_COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH: ignore
+
+  - name: "{{ subcommand }} incompatible tarfile"
+    command: "{{ install_or_download }} -p {{ temp2 }} {{ temp1 }}/ns_requires_ansible-name_requires_ansible-1.0.0.tar.gz"
+    register: expected_fail
+    failed_when: expected_fail is success
+
+  - assert:
+      that:
+        - expected_fail.stderr is search(failed_error, multiline=True)
+        - expected_fail.stderr is search(hint)
+
+  - name: "{{ subcommand }} tarfile and allow mismatched version"
+    command: "{{ install_or_download }} -p {{ temp2 }} {{ temp1 }}/ns_requires_ansible-name_requires_ansible-1.0.0.tar.gz"
+    environment:
+      ANSIBLE_COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH: ignore
+
+  - name: setup - {{ subcommand }} build directory
+    block:
+      - name: setup - init collection build directory
+        command: ansible-galaxy collection init ns_requires_ansible.name_requires_ansible --init-path {{ temp2 }}/ansible_collections
+
+      - name: setup - add  requires_ansible in the runtime file
+        shell: >-
+          echo '"'"'requires_ansible: "<1.1"'"'"' > {{ temp2 }}/ansible_collections/ns_requires_ansible/name_requires_ansible/meta/runtime.yml
+    when: subcommand == '"'"'download'"'"'
+
+  - name: "{{ subcommand }} incompatible directory"
+    command: "{{ install_or_download }} -p {{ temp1 }} {{ temp2 }}/ansible_collections/ns_requires_ansible/name_requires_ansible"
+    register: expected_fail
+    failed_when: expected_fail is success
+
+  - assert:
+      that:
+        - expected_fail.stderr is search(failed_error, multiline=True)
+        - expected_fail.stderr is search(hint)
+
+  - name: "{{ subcommand }} directory and allow mismatched version"
+    command: "{{ install_or_download }} -p {{ temp1 }} {{ temp2 }}/ansible_collections/ns_requires_ansible/name_requires_ansible"
+    environment:
+      ANSIBLE_COLLECTIONS_ON_ANSIBLE_VERSION_MISMATCH: ignore
+
+  - name: setup - {{ subcommand }} remove requires_ansible metadata
+    file:
+      path: "{{ temp2 }}/ansible_collections/ns_requires_ansible/name_requires_ansible/meta/runtime.yml"
+      state: absent
+
+  - name: "{{ subcommand }} directory with undocumented, optional requires_ansible metadata"
+    command: "{{ install_or_download }} -p {{ temp1 }} {{ temp2 }}/ansible_collections/ns_requires_ansible/name_requires_ansible"
+    register: expected_success
+
+  - assert:
+      that:
+        - expected_success.stderr is search(undocumented_warning)
+
+  - name: "{{ subcommand }} collection with incompatible dependency"
+    command: "{{ install_or_download }} -p {{ temp1 }} '"'"'ns_requires_ansible.dependency:2.0.0'"'"'"
+    register: expected_error
+    failed_when: expected_error is not failed
+
+  - assert:
+      that:
+        - expected_error.stderr is search(expected_message, multiline=True)
+    vars:
+      expected_message: |
+        \[ERROR\]: Failed to resolve the requested dependencies map\. Could not satisfy the following requirements:
+        \* ns_requires_ansible\.name_requires_ansible:1\.0\.0 \(dependency of ns_requires_ansible\.dependency:2\.0\.0\) requires ansible-core <1\.1
+
+  - name: "{{ subcommand }} collection version without incompatible dependency"
+    command: "{{ install_or_download }} -p {{ temp1 }} ns_requires_ansible.dependency"
+    register: expected_success
+
+  - assert:
+      that:
+        - expected_success.stdout is search(expected_message)
+    vars:
+      expected_message: >-
+        '"'"'?ns_requires_ansible\.dependency:1\.0\.0'"'"'? was {{ subcommand }}ed successfully
+
+  - name: "{{ subcommand }} collection with unsuccessful backtracking"
+    command: "{{ install_or_download }} ns_requires_ansible.backtracking_error"
+    register: expected_fail
+    failed_when: expected_fail is success
+
+  - assert:
+      that:
+        - expected_fail.stderr is search(expected_message, multiline=True)
+        - expected_fail.stderr is search(hint)
+    vars:
+      expected_message: |
+        \[ERROR\]: Failed to resolve the requested dependencies map\. Could not satisfy the following requirements:
+        \* ns_requires_ansible\.name_requires_ansible:1\.0\.0 \(dependency of ns_requires_ansible\.dependency_incompat:1\.0\.0\) requires ansible-core <1\.1
+
+  always:
+  - name: Clean up test dir
+    file:
+      path: "{{ test_base_dir }}"
+      state: absent
diff --git a/test/integration/targets/ansible-galaxy-collection/tasks/main.yml b/test/integration/targets/ansible-galaxy-collection/tasks/main.yml
index 7bcc38286d88df..b5bf60b9480141 100644
--- a/test/integration/targets/ansible-galaxy-collection/tasks/main.yml
+++ b/test/integration/targets/ansible-galaxy-collection/tasks/main.yml
@@ -210,9 +210,15 @@
 - name: run ansible-galaxy collection list tests
   include_tasks: list.yml
 
-- include_tasks: upgrade.yml
-  args:
-    apply:
-      environment:
-        ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}'"'"'
-        ANSIBLE_CONFIG: '"'"'{{ galaxy_dir }}/ansible.cfg'"'"'
+- environment:
+    ANSIBLE_CONFIG: '"'"'{{ galaxy_dir }}/ansible.cfg'"'"'
+    ANSIBLE_COLLECTIONS_PATH: '"'"'{{ galaxy_dir }}'"'"'
+  block:
+  - include_tasks: upgrade.yml
+
+  - include_tasks: check_requires_ansible.yml
+    loop:
+      - install
+      - download
+    loop_control:
+      loop_var: subcommand
diff --git a/test/integration/targets/ansible-galaxy-collection/vars/main.yml b/test/integration/targets/ansible-galaxy-collection/vars/main.yml
index 855b382e5ca39a..a7cc78caa7d8d2 100644
--- a/test/integration/targets/ansible-galaxy-collection/vars/main.yml
+++ b/test/integration/targets/ansible-galaxy-collection/vars/main.yml
@@ -201,3 +201,43 @@ collection_list:
     version: 4.5.6
     dependencies:
       ns_with_wildcard_dep.name_with_wildcard_dep: 5.6.7-beta.3
+
+  - namespace: ns_requires_ansible
+    name: name_requires_ansible
+    version: 1.0.0
+    runtime: |-
+      requires_ansible: "<1.1"
+
+  - namespace: ns_requires_ansible
+    name: dependency
+    version: 1.0.0
+
+  - namespace: ns_requires_ansible
+    name: dependency
+    version: 2.0.0
+    dependencies:
+      ns_requires_ansible.name_requires_ansible: 1.0.0
+
+  - namespace: ns_requires_ansible
+    name: dependency_incompat
+    version: 1.0.0
+    dependencies:
+      ns_requires_ansible.name_requires_ansible: 1.0.0
+
+  - namespace: ns_requires_ansible
+    name: dependency_incompat
+    version: 2.0.0
+    dependencies:
+      ns_requires_ansible.dependency: 2.0.0  # pinned incompatible version
+
+  - namespace: ns_requires_ansible
+    name: dependency_incompat
+    version: 3.0.0
+    dependencies:
+      ns_requires_ansible.name_requires_ansible: 1.0.0
+
+  - namespace: ns_requires_ansible
+    name: backtracking_error
+    version: 1.0.0
+    dependencies:
+      ns_requires_ansible.dependency_incompat: "*"
diff --git a/test/units/galaxy/test_collection_install.py b/test/units/galaxy/test_collection_install.py
index dc6dbe5b6f35a5..ed3eb23e8e0e81 100644
--- a/test/units/galaxy/test_collection_install.py
+++ b/test/units/galaxy/test_collection_install.py
@@ -897,10 +897,11 @@ def test_install_collections_from_tar(collection_artifact, monkeypatch):
 
     # Filter out the progress cursor display calls.
     display_msgs = [m[1][0] for m in mock_display.mock_calls if '"'"'newline'"'"' not in m[2] and len(m[1]) == 1]
-    assert len(display_msgs) == 4
+    assert len(display_msgs) == 5
     assert display_msgs[0] == "Process install dependency map"
-    assert display_msgs[1] == "Starting collection install process"
-    assert display_msgs[2] == "Installing '"'"'ansible_namespace.collection:0.1.0'"'"' to '"'"'%s'"'"'" % to_text(collection_path)
+    assert display_msgs[1] == "[WARNING]: ansible_namespace.collection:0.1.0 does not have requires_ansible metadata.\n"
+    assert display_msgs[2] == "Starting collection install process"
+    assert display_msgs[3] == "Installing '"'"'ansible_namespace.collection:0.1.0'"'"' to '"'"'%s'"'"'" % to_text(collection_path)
 
 
 # Makes sure we don'"'"'t get stuck in some recursive loop
@@ -937,11 +938,12 @@ def test_install_collection_with_circular_dependency(collection_artifact, monkey
 
     # Filter out the progress cursor display calls.
     display_msgs = [m[1][0] for m in mock_display.mock_calls if '"'"'newline'"'"' not in m[2] and len(m[1]) == 1]
-    assert len(display_msgs) == 4
+    assert len(display_msgs) == 5
     assert display_msgs[0] == "Process install dependency map"
-    assert display_msgs[1] == "Starting collection install process"
-    assert display_msgs[2] == "Installing '"'"'ansible_namespace.collection:0.1.0'"'"' to '"'"'%s'"'"'" % to_text(collection_path)
-    assert display_msgs[3] == "ansible_namespace.collection:0.1.0 was installed successfully"
+    assert display_msgs[1] == "[WARNING]: ansible_namespace.collection:0.1.0 does not have requires_ansible metadata.\n"
+    assert display_msgs[2] == "Starting collection install process"
+    assert display_msgs[3] == "Installing '"'"'ansible_namespace.collection:0.1.0'"'"' to '"'"'%s'"'"'" % to_text(collection_path)
+    assert display_msgs[4] == "ansible_namespace.collection:0.1.0 was installed successfully"
 
 
 @pytest.mark.parametrize('"'"'collection_artifact'"'"', [
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/ansible-galaxy-collection-scm/tasks/download.yml test/integration/targets/ansible-galaxy-collection/library/setup_collections.py test/integration/targets/ansible-galaxy-collection/tasks/check_requires_ansible.yml test/integration/targets/ansible-galaxy-collection/tasks/main.yml test/integration/targets/ansible-galaxy-collection/vars/main.yml test/units/galaxy/test_collection_install.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/galaxy/test_collection_install.py::test_install_collections_from_tar", "test/units/galaxy/test_collection_install.py::test_install_collection_with_circular_dependency[collection_artifact0]"]

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
