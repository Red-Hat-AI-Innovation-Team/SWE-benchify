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
go test -json -count=1 ./staging/src/k8s.io/kubectl/pkg/describe/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestDescribeService"]
passed = set()
with open("/tmp/test_output.txt") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action == "pass":
            passed.add(test)
            # Also add the bare test name (no subtest suffix)
            passed.add(test.split("/")[0])

all_pass = all(
    t in passed or t.split("/")[0] in passed
    for t in f2p
)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if t not in passed and t.split("/")[0] not in passed]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
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
