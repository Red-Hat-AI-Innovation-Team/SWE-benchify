#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go b/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go
index ac2e88c761411..cba79c0bc9aad 100644
--- a/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go
+++ b/pkg/controller/volume/attachdetach/reconciler/reconciler_test.go
@@ -1291,7 +1291,7 @@ func Test_Run_OneVolumeDetachOnUnhealthyNodeWithForceDetachOnUnmountDisabled(t *
 	testForceDetachMetric(t, int(initialForceDetachCountTimeout), metrics.ForceDetachReasonTimeout)
 }
 
-func Test_ReportMultiAttachError(t *testing.T) {
+func Test_ReportWaitingOnDetach(t *testing.T) {
 	type nodeWithPods struct {
 		name     k8stypes.NodeName
 		podNames []string
@@ -1306,7 +1306,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 			[]nodeWithPods{
 				{"node1", []string{"ns1/pod1"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already exclusively attached to one node and can'"'"'t be attached to another"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already exclusively attached to one node, waiting on detach before it can be attached to another node"},
 		},
 		{
 			"pods in the same namespace use the volume",
@@ -1314,7 +1314,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 				{"node1", []string{"ns1/pod1"}},
 				{"node2", []string{"ns1/pod2"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already used by pod(s) pod2"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already used by pod(s) pod2"},
 		},
 		{
 			"pods in another namespace use the volume",
@@ -1322,7 +1322,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 				{"node1", []string{"ns1/pod1"}},
 				{"node2", []string{"ns2/pod2"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already used by 1 pod(s) in different namespaces"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already used by 1 pod(s) in different namespaces"},
 		},
 		{
 			"pods both in the same and another namespace use the volume",
@@ -1331,7 +1331,7 @@ func Test_ReportMultiAttachError(t *testing.T) {
 				{"node2", []string{"ns2/pod2"}},
 				{"node3", []string{"ns1/pod3"}},
 			},
-			[]string{"Warning FailedAttachVolume Multi-Attach error for volume \"volume-name\" Volume is already used by pod(s) pod3 and 1 pod(s) in different namespaces"},
+			[]string{"Warning FailedAttachVolume Waiting for detach for volume \"volume-name\" Volume is already used by pod(s) pod3 and 1 pod(s) in different namespaces"},
 		},
 	}
 
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/controller/volume/attachdetach/reconciler/... 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = ["Test_ReportWaitingOnDetach"]
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
