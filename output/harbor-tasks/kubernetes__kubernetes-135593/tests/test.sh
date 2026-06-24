#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/proxy/endpointschangetracker_test.go b/pkg/proxy/endpointschangetracker_test.go
index 0f1a408205d83..923c3ccf6e24e 100644
--- a/pkg/proxy/endpointschangetracker_test.go
+++ b/pkg/proxy/endpointschangetracker_test.go
@@ -1321,8 +1321,8 @@ func TestEndpointSliceUpdate(t *testing.T) {
 		// test additions to existing state with partially overlapping slices and ports
 		"add a slice that overlaps with existing state and partial ports": {
 			startingSlices: []*discovery.EndpointSlice{
-				generateEndpointSlice("svc1", "ns1", 1, 3, 999, 999, []string{"host1", "host2"}, []*int32{ptr.To[int32](80), ptr.To[int32](443)}),
-				generateEndpointSlice("svc1", "ns1", 2, 2, 999, 999, []string{"host1", "host2"}, []*int32{ptr.To[int32](80), ptr.To[int32](443)}),
+				generateEndpointSlice("svc1", "ns1", 1, 3, 999, 999, []string{"host1"}, []*int32{ptr.To[int32](80), ptr.To[int32](443)}),
+				generateEndpointSlice("svc1", "ns1", 2, 2, 999, 999, []string{"host1"}, []*int32{ptr.To[int32](80), ptr.To[int32](443)}),
 			},
 			endpointsChangeTracker: NewEndpointsChangeTracker(v1.IPv4Protocol, "host1", nil, nil),
 			namespacedName:         types.NamespacedName{Name: "svc1", Namespace: "ns1"},
@@ -1336,14 +1336,14 @@ func TestEndpointSliceUpdate(t *testing.T) {
 					&BaseEndpointInfo{ip: "10.0.1.3", port: 80, endpoint: "10.0.1.3:80", isLocal: true, ready: true, serving: true, terminating: false},
 					&BaseEndpointInfo{ip: "10.0.1.4", port: 80, endpoint: "10.0.1.4:80", isLocal: true, ready: true, serving: true, terminating: false},
 					&BaseEndpointInfo{ip: "10.0.1.5", port: 80, endpoint: "10.0.1.5:80", isLocal: true, ready: true, serving: true, terminating: false},
-					&BaseEndpointInfo{ip: "10.0.2.1", port: 80, endpoint: "10.0.2.1:80", isLocal: false, ready: true, serving: true, terminating: false},
+					&BaseEndpointInfo{ip: "10.0.2.1", port: 80, endpoint: "10.0.2.1:80", isLocal: true, ready: true, serving: true, terminating: false},
 					&BaseEndpointInfo{ip: "10.0.2.2", port: 80, endpoint: "10.0.2.2:80", isLocal: true, ready: true, serving: true, terminating: false},
 				},
 				makeServicePortName("ns1", "svc1", "port-1", v1.ProtocolTCP): {
-					&BaseEndpointInfo{ip: "10.0.1.1", port: 443, endpoint: "10.0.1.1:443", isLocal: false, ready: true, serving: true, terminating: false},
+					&BaseEndpointInfo{ip: "10.0.1.1", port: 443, endpoint: "10.0.1.1:443", isLocal: true, ready: true, serving: true, terminating: false},
 					&BaseEndpointInfo{ip: "10.0.1.2", port: 443, endpoint: "10.0.1.2:443", isLocal: true, ready: true, serving: true, terminating: false},
-					&BaseEndpointInfo{ip: "10.0.1.3", port: 443, endpoint: "10.0.1.3:443", isLocal: false, ready: true, serving: true, terminating: false},
-					&BaseEndpointInfo{ip: "10.0.2.1", port: 443, endpoint: "10.0.2.1:443", isLocal: false, ready: true, serving: true, terminating: false},
+					&BaseEndpointInfo{ip: "10.0.1.3", port: 443, endpoint: "10.0.1.3:443", isLocal: true, ready: true, serving: true, terminating: false},
+					&BaseEndpointInfo{ip: "10.0.2.1", port: 443, endpoint: "10.0.2.1:443", isLocal: true, ready: true, serving: true, terminating: false},
 					&BaseEndpointInfo{ip: "10.0.2.2", port: 443, endpoint: "10.0.2.2:443", isLocal: true, ready: true, serving: true, terminating: false},
 				},
 			},
diff --git a/pkg/proxy/endpointslicecache_test.go b/pkg/proxy/endpointslicecache_test.go
index 610bb271c16a7..54a37ec3baddc 100644
--- a/pkg/proxy/endpointslicecache_test.go
+++ b/pkg/proxy/endpointslicecache_test.go
@@ -311,6 +311,48 @@ func TestEndpointInfoByServicePort(t *testing.T) {
 				},
 			},
 		},
+		"with duplicate Endpoints, prefer non-terminating": {
+			namespacedName: types.NamespacedName{Name: "svc1", Namespace: "ns1"},
+			hostname:       "host1",
+			endpointSlices: []*discovery.EndpointSlice{
+				func() *discovery.EndpointSlice {
+					es := generateEndpointSliceWithOffset("svc1", "ns1", 1, 1, 1, 999, 999, []string{"host1"}, []*int32{ptr.To[int32](80)})
+
+					// Duplicate the endpoint
+					ep1 := es.Endpoints[0]
+					ep1.Conditions.Ready = ptr.To(false)
+					ep1.Conditions.Serving = ptr.To(true)
+					ep1.Conditions.Terminating = ptr.To(true)
+
+					ep2 := es.Endpoints[0]
+					ep2.Conditions.Ready = ptr.To(true)
+					ep2.Conditions.Serving = ptr.To(true)
+					ep2.Conditions.Terminating = ptr.To(false)
+
+					ep3 := es.Endpoints[0]
+					ep3.Conditions.Ready = ptr.To(false)
+					ep3.Conditions.Serving = ptr.To(false)
+					ep3.Conditions.Terminating = ptr.To(true)
+
+					//  ep2 should win since it'"'"'s the non-terminating one
+					es.Endpoints = []discovery.Endpoint{ep1, ep2, ep3}
+					return es
+				}(),
+			},
+			expectedMap: spToEndpointMap{
+				makeServicePortName("ns1", "svc1", "port-0", v1.ProtocolTCP): {
+					"10.0.1.1:80": &BaseEndpointInfo{
+						ip:          "10.0.1.1",
+						port:        80,
+						endpoint:    "10.0.1.1:80",
+						isLocal:     true,
+						ready:       true,
+						serving:     true,
+						terminating: false,
+					},
+				},
+			},
+		},
 	}
 
 	for name, tc := range testCases {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestEndpointInfoByServicePort"]

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

TEST_OUTPUT_FORMAT="go-json" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
