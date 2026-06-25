#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uel20.json b/test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uel20.json
new file mode 100644
index 00000000000000..124c090944a63b
--- /dev/null
+++ b/test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uel20.json
@@ -0,0 +1,29 @@
+{
+    "name": "UnionTech OS Server 20 (uel20)",
+    "distro": {
+        "codename": "fuyu",
+        "id": "uos",
+        "name": "UnionTech OS Server 20",
+        "version": "20",
+        "version_best": "20",
+        "os_release_info": {},
+        "lsb_release_info": {}
+    },
+    "input": {
+        "/etc/os-release": "PRETTY_NAME=\"UnionTech OS Server 20\"\nNAME=\"UnionTech OS Server 20\"\nVERSION_ID=\"20\"\nVERSION=\"20\"\nID=\"uos\"\nPLATFORM_ID=\"platform:uel20\"\nHOME_URL=\"https://www.chinauos.com/\"\nBUG_REPORT_URL=\"https://bbs.chinauos.com/\"\nVERSION_CODENAME=\"fuyu\"\n",
+        "/etc/lsb-release": "DISTRIB_ID=\"Uos\"\nDISTRIB_RELEASE=\"20\"\nDISTRIB_DESCRIPTION=\"UnionTech OS Server 20\"\nDISTRIB_CODENAME=\"fuyu\"\n",
+        "/etc/system-release": "uos release 20 (fuyu)\n"
+    },
+    "platform.dist": [
+        "uos",
+        "20",
+        "fuyu"
+    ],
+    "result": {
+        "distribution": "UnionTech",
+        "distribution_version": "20",
+        "distribution_release": "fuyu",
+        "distribution_major_version": "20",
+        "os_family": "RedHat"
+    }
+}
diff --git a/test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uelc20.json b/test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uelc20.json
new file mode 100644
index 00000000000000..b8255129637149
--- /dev/null
+++ b/test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uelc20.json
@@ -0,0 +1,30 @@
+{
+    "name": "UnionTech OS Server 20 (uelc20)",
+    "distro": {
+        "codename": "kongzi",
+        "id": "uos",
+        "name": "UnionTech OS Server 20",
+        "version": "20",
+        "version_best": "20",
+        "os_release_info": {},
+        "lsb_release_info": {}
+    },
+    "input": {
+        "/etc/os-release": "PRETTY_NAME=\"UnionTech OS Server 20\"\nNAME=\"UnionTech OS Server 20\"\nVERSION_ID=\"20\"\nVERSION=\"20\"\nID=uos\nHOME_URL=\"https://www.chinauos.com/\"\nBUG_REPORT_URL=\"https://bbs.chinauos.com/\"\nVERSION_CODENAME=kongzi\nPLATFORM_ID=\"platform:uelc20\"\n",
+        "/etc/lsb-release": "DISTRIB_ID=Uos\nDISTRIB_RELEASE=20\nDISTRIB_DESCRIPTION=\"UnionTech OS Server 20\"\nDISTRIB_CODENAME=kongzi\n",
+        "/etc/system-release": "UnionTech OS Server release 20 (kongzi)\n",
+        "/etc/redhat-release": "UnionTech OS Server release 20 (kongzi)\n"
+    },
+    "platform.dist": [
+        "uos",
+        "20",
+        "kongzi"
+    ],
+    "result": {
+        "distribution": "UnionTech",
+        "distribution_version": "20",
+        "distribution_release": "kongzi",
+        "distribution_major_version": "20",
+        "os_family": "RedHat"
+    }
+}
diff --git a/test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uel20.json b/test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uel20.json
new file mode 100644
index 00000000000000..12b68a556c11dd
--- /dev/null
+++ b/test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uel20.json
@@ -0,0 +1,29 @@
+{
+    "name": "UOS Server 20 (uel20)",
+    "distro": {
+        "codename": "fuyu",
+        "id": "uos",
+        "name": "UOS Server 20",
+        "version": "20",
+        "version_best": "20",
+        "os_release_info": {},
+        "lsb_release_info": {}
+    },
+    "input": {
+        "/etc/os-release": "PRETTY_NAME=\"UOS Server 20\"\nNAME=\"UOS Server 20\"\nVERSION_ID=\"20\"\nVERSION=\"20\"\nID=uos\nHOME_URL=\"https://www.chinauos.com/\"\nBUG_REPORT_URL=\"https://bbs.chinauos.com/\"\nVERSION_CODENAME=fuyu\nPLATFORM_ID=\"platform:uel20\"\n",
+        "/etc/lsb-release": "DISTRIB_ID=Uos\nDISTRIB_RELEASE=20\nDISTRIB_DESCRIPTION=\"UOS Server 20\"\nDISTRIB_CODENAME=fuyu\n",
+        "/etc/system-release": "uos release 20 (fuyu)\n"
+    },
+    "platform.dist": [
+        "uos",
+        "20",
+        "fuyu"
+    ],
+    "result": {
+        "distribution": "UnionTech",
+        "distribution_version": "20",
+        "distribution_release": "fuyu",
+        "distribution_major_version": "20",
+        "os_family": "RedHat"
+    }
+}
diff --git a/test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uelc20.json b/test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uelc20.json
new file mode 100644
index 00000000000000..0401b8a75c451a
--- /dev/null
+++ b/test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uelc20.json
@@ -0,0 +1,30 @@
+{
+    "name": "UOS Server 20 (uelc20)",
+    "distro": {
+        "codename": "kongzi",
+        "id": "uos",
+        "name": "UOS Server 20",
+        "version": "20",
+        "version_best": "20",
+        "os_release_info": {},
+        "lsb_release_info": {}
+    },
+    "input": {
+        "/etc/os-release": "PRETTY_NAME=\"UOS Server 20\"\nNAME=\"UOS Server 20\"\nVERSION_ID=\"20\"\nVERSION=\"20\"\nID=uos\nHOME_URL=\"https://www.chinauos.com/\"\nBUG_REPORT_URL=\"https://bbs.chinauos.com/\"\nVERSION_CODENAME=kongzi\nPLATFORM_ID=\"platform:uelc20\"\n",
+        "/etc/lsb-release": "DISTRIB_ID=Uos\nDISTRIB_RELEASE=20\nDISTRIB_DESCRIPTION=\"UOS Server 20\"\nDISTRIB_CODENAME=kongzi\n",
+        "/etc/system-release": "UOS Server release 20 (kongzi)\n",
+        "/etc/redhat-release": "UOS Server release 20 (kongzi)\n"
+    },
+    "platform.dist": [
+        "uos",
+        "20",
+        "kongzi"
+    ],
+    "result": {
+        "distribution": "UnionTech",
+        "distribution_version": "20",
+        "distribution_release": "kongzi",
+        "distribution_major_version": "20",
+        "os_family": "RedHat"
+    }
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Install project
pip install -e . 2>/dev/null || pip install . 2>/dev/null || true

# Run tests and capture output
python -m pytest -xvs test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uel20.json test/units/module_utils/facts/system/distribution/fixtures/uniontech_os_server_20_uelc20.json test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uel20.json test/units/module_utils/facts/system/distribution/fixtures/uos_server_20_uelc20.json 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "pytest-verbose")
f2p = ["test/units/module_utils/facts/system/distribution/test_distribution_version.py::test_distribution_version[stdin30-UnionTech OS Server 20 (uelc20)]", "test/units/module_utils/facts/system/distribution/test_distribution_version.py::test_distribution_version[stdin64-UnionTech OS Server 20 (uel20)]", "test/units/module_utils/facts/system/distribution/test_distribution_version.py::test_distribution_version[stdin73-UOS Server 20 (uelc20)]", "test/units/module_utils/facts/system/distribution/test_distribution_version.py::test_distribution_version[stdin75-UOS Server 20 (uel20)]"]

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
