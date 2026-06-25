#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/kubectl/pkg/describe/describe_test.go b/staging/src/k8s.io/kubectl/pkg/describe/describe_test.go
index bee1f11f3e9e7..a3bf0c581b233 100644
--- a/staging/src/k8s.io/kubectl/pkg/describe/describe_test.go
+++ b/staging/src/k8s.io/kubectl/pkg/describe/describe_test.go
@@ -1270,6 +1270,86 @@ func TestDescribeService(t *testing.T) {
 				Events:                   <none>
 			`)[1:],
 		},
+		{
+			name: "test-AppProtocol",
+			service: &corev1.Service{
+				ObjectMeta: metav1.ObjectMeta{
+					Name:      "bar",
+					Namespace: "foo",
+				},
+				Spec: corev1.ServiceSpec{
+					Type: corev1.ServiceTypeLoadBalancer,
+					Ports: []corev1.ServicePort{{
+						Name:        "port-tcp",
+						Port:        8080,
+						Protocol:    corev1.ProtocolTCP,
+						AppProtocol: ptr.To("example.com/custom-protocol"),
+						TargetPort:  intstr.FromInt32(9527),
+						NodePort:    31111,
+					}},
+					Selector:              map[string]string{"blah": "heh"},
+					ClusterIP:             "1.2.3.4",
+					IPFamilies:            []corev1.IPFamily{corev1.IPv4Protocol},
+					LoadBalancerIP:        "5.6.7.8",
+					SessionAffinity:       corev1.ServiceAffinityNone,
+					ExternalTrafficPolicy: corev1.ServiceExternalTrafficPolicyLocal,
+					InternalTrafficPolicy: ptr.To(corev1.ServiceInternalTrafficPolicyCluster),
+					HealthCheckNodePort:   32222,
+				},
+				Status: corev1.ServiceStatus{
+					LoadBalancer: corev1.LoadBalancerStatus{
+						Ingress: []corev1.LoadBalancerIngress{
+							{
+								IP:     "5.6.7.8",
+								IPMode: ptr.To(corev1.LoadBalancerIPModeVIP),
+							},
+						},
+					},
+				},
+			},
+			endpointSlices: []*discoveryv1.EndpointSlice{{
+				ObjectMeta: metav1.ObjectMeta{
+					Name:      "bar-abcde",
+					Namespace: "foo",
+					Labels: map[string]string{
+						"kubernetes.io/service-name": "bar",
+					},
+				},
+				Endpoints: []discoveryv1.Endpoint{
+					{Addresses: []string{"10.244.0.1"}, Conditions: discoveryv1.EndpointConditions{Ready: ptr.To(true)}},
+					{Addresses: []string{"10.244.0.2"}, Conditions: discoveryv1.EndpointConditions{Ready: ptr.To(true)}},
+					{Addresses: []string{"10.244.0.3"}, Conditions: discoveryv1.EndpointConditions{Ready: ptr.To(true)}},
+				},
+				Ports: []discoveryv1.EndpointPort{{
+					Name:     ptr.To("port-tcp"),
+					Port:     ptr.To[int32](9527),
+					Protocol: ptr.To(corev1.ProtocolTCP),
+				}},
+			}},
+			expected: dedent.Dedent(`
+				Name:                     bar
+				Namespace:                foo
+				Labels:                   <none>
+				Annotations:              <none>
+				Selector:                 blah=heh
+				Type:                     LoadBalancer
+				IP Families:              IPv4
+				IP:                       1.2.3.4
+				IPs:                      <none>
+				Desired LoadBalancer IP:  5.6.7.8
+				LoadBalancer Ingress:     5.6.7.8 (VIP)
+				Port:                     port-tcp  8080/TCP
+				TargetPort:               9527/TCP
+				AppProtocol:              example.com/custom-protocol
+				NodePort:                 port-tcp  31111/TCP
+				Endpoints:                10.244.0.1:9527,10.244.0.2:9527,10.244.0.3:9527
+				Session Affinity:         None
+				External Traffic Policy:  Local
+				Internal Traffic Policy:  Cluster
+				HealthCheck NodePort:     32222
+				Events:                   <none>
+			`)[1:],
+		},
 	}
 	for _, tc := range testCases {
 		t.Run(tc.name, func(t *testing.T) {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestDescribeService"]

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
