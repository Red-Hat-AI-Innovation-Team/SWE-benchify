#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/integration/targets/uri/tasks/main.yml b/test/integration/targets/uri/tasks/main.yml
index 62748d7591f28f..dacb81b5d28eb1 100644
--- a/test/integration/targets/uri/tasks/main.yml
+++ b/test/integration/targets/uri/tasks/main.yml
@@ -444,6 +444,7 @@
     body:
       file1:
         filename: formdata.txt
+        multipart_encoding: base64
       file2:
         content: text based file content
         filename: fake.txt
@@ -451,6 +452,8 @@
       file3:
         filename: formdata.txt
         multipart_encoding: '"'"'7or8bit'"'"'
+      file4:
+        filename: formdata.txt
       text_form_field1: value1
       text_form_field2:
         content: value2
@@ -462,7 +465,8 @@
     that:
       - multipart.json.files.file1 | b64decode == '"'"'_multipart/form-data_\n'"'"'
       - multipart.json.files.file2 == '"'"'text based file content'"'"'
-      - multipart.json.files.file3 == '"'"'_multipart/form-data_\r\n'"'"'
+      - multipart.json.files.file3 == '"'"'_multipart/form-data_\n'"'"'
+      - multipart.json.files.file4 == '"'"'_multipart/form-data_\n'"'"'
       - multipart.json.form.text_form_field1 == '"'"'value1'"'"'
       - multipart.json.form.text_form_field2 == '"'"'value2'"'"'
 
@@ -493,7 +497,7 @@
 - name: Assert multipart/form-data with file and retry
   assert:
     that:
-      - result.json.files.file | b64decode == '"'"'_multipart/form-data_\n'"'"'
+      - result.json.files.file == '"'"'_multipart/form-data_\n'"'"'
       - result.attempts == 2
 
 - name: Validate invalid method
diff --git a/test/units/module_utils/urls/fixtures/multipart.txt b/test/units/module_utils/urls/fixtures/multipart.txt
index fc2e9a80a9c064..25a953a83c891f 100644
--- a/test/units/module_utils/urls/fixtures/multipart.txt
+++ b/test/units/module_utils/urls/fixtures/multipart.txt
@@ -97,7 +97,6 @@ V2N4OXhzcnpYbkNLRTNaaUdiV2YxWk1TemZSUGFqWlNtdEZIVTJuRXA4cGQycFZ3YlVkRHFXNQpU
 emdXUEgyRnJ2OGpOTWNzOWhRUFZlKzRBSW54c29wMUZVR0JjdEJEcG9iUkJ1Yk9nWDVmTStiMEdk
 WndBTHBJCmJnWDlURHpEVVJ1OVF4b2t4WG5xZXZDRnBVQVFoZWtqQ1FtQU9KMjhnVjVaakZwTldG
 YTVjY0o0emZPdwotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg==
-
 --===============3996062709511591449==
 Content-Transfer-Encoding: base64
 Content-Type: application/octet-stream
@@ -133,7 +132,6 @@ dWV0SS9pSS9vM3dPekx2ekFvR0FJck9oMzBySHQ4d2l0N0VMQVJ5eAp3UGtwMkFSWVhyS2ZYM05F
 UzRjNjd6U0FpKzNkQ2p4UnF5d3FUSTBnTGljeU1sajh6RXU5WUU5SXgvcmw4bFJaCm5ROUxabXF2
 N1FIemhMVFVDUEdnWlluZW12QnpvN3IwZVc4T2FnNTJkYmNKTzZGQnN6ZldyeHNrbS9mWDI1UmIK
 V1B4aWgydmRSeTgxNGROUFcyNXJnZHc9Ci0tLS0tRU5EIFBSSVZBVEUgS0VZLS0tLS0K
-
 --===============3996062709511591449==
 Content-Transfer-Encoding: base64
 Content-Type: text/plain
@@ -142,15 +140,22 @@ Content-Disposition: form-data; name="file6"; filename="client.txt"
 Y2xpZW50LnBlbSBhbmQgY2xpZW50LmtleSB3ZXJlIHJldHJpZXZlZCBmcm9tIGh0dHB0ZXN0ZXIg
 ZG9ja2VyIGltYWdlOgoKYW5zaWJsZS9hbnNpYmxlQHNoYTI1NjpmYTVkZWY4YzI5NGZjNTA4MTNh
 ZjEzMWMwYjU3Mzc1OTRkODUyYWJhYzljYmU3YmEzOGUxN2JmMWM4NDc2ZjNmCg==
-
 --===============3996062709511591449==
 Content-Transfer-Encoding: 7bit
 Content-Type: text/plain
 Content-Disposition: form-data; name="file7"; filename="client.txt"
 
-client.pem and client.key were retrieved from httptester docker image:
+client.pem and client.key were retrieved from httptester docker image:
+
+ansible/ansible@sha256:fa5def8c294fc50813af131c0b5737594d852abac9cbe7ba38e17bf1c8476f3f
+
+--===============3996062709511591449==
+Content-Type: text/plain
+Content-Disposition: form-data; name="file8"; filename="client.txt"
 
-ansible/ansible@sha256:fa5def8c294fc50813af131c0b5737594d852abac9cbe7ba38e17bf1c8476f3f
+client.pem and client.key were retrieved from httptester docker image:
+
+ansible/ansible@sha256:fa5def8c294fc50813af131c0b5737594d852abac9cbe7ba38e17bf1c8476f3f
 
 --===============3996062709511591449==
 Content-Type: text/plain
diff --git a/test/units/module_utils/urls/test_prepare_multipart.py b/test/units/module_utils/urls/test_prepare_multipart.py
index 10afdd0eb5e56e..9454fd2f678b31 100644
--- a/test/units/module_utils/urls/test_prepare_multipart.py
+++ b/test/units/module_utils/urls/test_prepare_multipart.py
@@ -52,18 +52,23 @@ def test_prepare_multipart():
         '"'"'file4'"'"': {
             '"'"'filename'"'"': client_cert,
             '"'"'mime_type'"'"': '"'"'text/plain'"'"',
+            '"'"'multipart_encoding'"'"': '"'"'base64'"'"',
         },
         '"'"'file5'"'"': {
             '"'"'filename'"'"': client_key,
-            '"'"'mime_type'"'"': '"'"'application/octet-stream'"'"'
+            '"'"'mime_type'"'"': '"'"'application/octet-stream'"'"',
+            '"'"'multipart_encoding'"'"': '"'"'base64'"'"',
         },
         '"'"'file6'"'"': {
             '"'"'filename'"'"': client_txt,
-            '"'"'multipart_encoding'"'"': '"'"'base64'"'"'
+            '"'"'multipart_encoding'"'"': '"'"'base64'"'"',
         },
         '"'"'file7'"'"': {
             '"'"'filename'"'"': client_txt,
-            '"'"'multipart_encoding'"'"': '"'"'7or8bit'"'"'
+            '"'"'multipart_encoding'"'"': '"'"'7or8bit'"'"',
+        },
+        '"'"'file8'"'"': {
+            '"'"'filename'"'"': client_txt,
         },
     }
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/integration/targets/uri/tasks/main.yml test/units/module_utils/urls/fixtures/multipart.txt test/units/module_utils/urls/test_prepare_multipart.py 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/module_utils/urls/test_prepare_multipart.py::test_prepare_multipart"]

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
