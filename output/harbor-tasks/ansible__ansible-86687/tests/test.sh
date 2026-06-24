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

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs test/integration/targets/uri/tasks/main.yml test/units/module_utils/urls/fixtures/multipart.txt test/units/module_utils/urls/test_prepare_multipart.py 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = ["test/units/module_utils/urls/test_prepare_multipart.py::test_prepare_multipart"]
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
