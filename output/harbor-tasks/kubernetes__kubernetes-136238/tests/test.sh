#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/kubelet/status/status_manager_test.go b/pkg/kubelet/status/status_manager_test.go
index 0b3c7da275dc1..01c6c76d34c3c 100644
--- a/pkg/kubelet/status/status_manager_test.go
+++ b/pkg/kubelet/status/status_manager_test.go
@@ -52,6 +52,7 @@ import (
 	statustest "k8s.io/kubernetes/pkg/kubelet/status/testing"
 	kubetypes "k8s.io/kubernetes/pkg/kubelet/types"
 	"k8s.io/kubernetes/pkg/kubelet/util"
+	"k8s.io/utils/ptr"
 )
 
 type mutablePodManager interface {
@@ -511,6 +512,25 @@ func TestStatusEquality(t *testing.T) {
 	if !isPodStatusByKubeletEqual(&oldPodStatus, &podStatus) {
 		t.Fatalf("Differences in pod condition not owned by kubelet should not affect normalized equality.")
 	}
+
+	claimStatusA := v1.PodResourceClaimStatus{
+		Name:              "my-claim",
+		ResourceClaimName: ptr.To("claim"),
+	}
+	extendedClaimStatusA := &v1.PodExtendedResourceClaimStatus{
+		RequestMappings: []v1.ContainerExtendedResourceRequest{
+			{RequestName: "request", ContainerName: "c", ResourceName: "example.com/gpu"},
+		},
+		ResourceClaimName: "claim",
+	}
+	oldPodStatus.ResourceClaimStatuses = []v1.PodResourceClaimStatus{claimStatusA}
+	oldPodStatus.ExtendedResourceClaimStatus = extendedClaimStatusA
+
+	normalizeStatus(&pod, &oldPodStatus)
+	normalizeStatus(&pod, &podStatus)
+	if !isPodStatusByKubeletEqual(&oldPodStatus, &podStatus) {
+		t.Fatalf("Differences in pod resource claim statuses not owned by kubelet should not affect normalized equality.")
+	}
 }
 
 func TestStatusNormalizationEnforcesMaxBytes(t *testing.T) {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/kubelet/status/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["TestStatusEquality"]
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
