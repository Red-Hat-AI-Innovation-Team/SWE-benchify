#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/registry/core/service/ipallocator/cidrallocator_test.go b/pkg/registry/core/service/ipallocator/cidrallocator_test.go
index 38aec78e256c8..8f20661215981 100644
--- a/pkg/registry/core/service/ipallocator/cidrallocator_test.go
+++ b/pkg/registry/core/service/ipallocator/cidrallocator_test.go
@@ -18,6 +18,7 @@ package ipallocator
 
 import (
 	"context"
+	"errors"
 	"fmt"
 	"net/netip"
 	"testing"
@@ -34,6 +35,7 @@ import (
 	"k8s.io/client-go/kubernetes/fake"
 	k8stesting "k8s.io/client-go/testing"
 	featuregatetesting "k8s.io/component-base/featuregate/testing"
+	"k8s.io/component-base/metrics/testutil"
 	"k8s.io/kubernetes/pkg/features"
 	netutils "k8s.io/utils/net"
 )
@@ -658,3 +660,192 @@ func Test_isNotContained(t *testing.T) {
 		})
 	}
 }
+
+func TestCIDRAllocatorClusterIPAllocatedMetrics(t *testing.T) {
+	featuregatetesting.SetFeatureGateDuringTest(t, utilfeature.DefaultFeatureGate, features.DisableAllocatorDualWrite, true)
+	clearMetrics()
+
+	r, err := newTestMetaAllocator()
+	if err != nil {
+		t.Fatal(err)
+	}
+	defer r.Destroy()
+
+	// Enable metrics for the meta allocator
+	r.EnableMetrics()
+
+	// Create first CIDR - small /30 network (only 2 usable IPs)
+	cidr1 := newServiceCIDR("test1", "192.168.1.0/30")
+	_, err = r.client.ServiceCIDRs().Create(context.Background(), cidr1, metav1.CreateOptions{})
+	if err != nil {
+		t.Fatal(err)
+	}
+	r.enqueueServiceCIDR(cidr1)
+
+	// Wait for the first CIDR to be processed
+	err = wait.PollUntilContextTimeout(context.Background(), 100*time.Millisecond, 5*time.Second, true, func(ctx context.Context) (bool, error) {
+		allocator, err := r.getAllocator(netutils.ParseIPSloppy("192.168.1.1"), true)
+		if err != nil {
+			t.Logf("unexpected error %v", err)
+			return false, nil
+		}
+		allocator.ipAddressSynced = func() bool { return true }
+		return allocator.ready.Load(), nil
+	})
+	if err != nil {
+		t.Fatal(err)
+	}
+
+	// Check initial metrics for first CIDR
+	em1 := testMetrics{
+		free:      0,
+		used:      0,
+		allocated: 0,
+		errors:    0,
+	}
+	expectMetrics(t, "192.168.1.0/30", em1)
+
+	// Allocate all IPs from first CIDR (should be 2 usable IPs: .1 and .2)
+	found := sets.NewString()
+	allocatedFromCIDR1 := 0
+	for r.Free() > 0 && allocatedFromCIDR1 < 2 {
+		ip, err := r.AllocateNext()
+		if err != nil {
+			t.Fatalf("error allocating from first CIDR @ allocated: %d: %v", allocatedFromCIDR1, err)
+		}
+		allocatedFromCIDR1++
+		if found.Has(ip.String()) {
+			t.Fatalf("allocated %s twice", ip)
+		}
+		found.Insert(ip.String())
+	}
+
+	// Verify we allocated 2 IPs from first CIDR
+	if allocatedFromCIDR1 != 2 {
+		t.Fatalf("expected 2 IPs from first CIDR, got %d", allocatedFromCIDR1)
+	}
+
+	// Check metrics after filling first CIDR
+	dynamicAllocatedCidr1, err := testutil.GetCounterMetricValue(clusterIPAllocations.WithLabelValues("192.168.1.0/30", "dynamic"))
+	if err != nil {
+		t.Errorf("failed to get %s value, err: %v", clusterIPAllocations.Name, err)
+	}
+	if dynamicAllocatedCidr1 != 2 {
+		t.Fatalf("Expected 2 dynamic allocations from first CIDR, received %f", dynamicAllocatedCidr1)
+	}
+
+	// Create second CIDR - small /29 network (6 usable IPs)
+	cidr2 := newServiceCIDR("test2", "10.0.0.0/29")
+	_, err = r.client.ServiceCIDRs().Create(context.Background(), cidr2, metav1.CreateOptions{})
+	if err != nil {
+		t.Fatal(err)
+	}
+	r.enqueueServiceCIDR(cidr2)
+
+	// Wait for the second CIDR to be processed
+	err = wait.PollUntilContextTimeout(context.Background(), 100*time.Millisecond, 5*time.Second, true, func(ctx context.Context) (bool, error) {
+		allocator, err := r.getAllocator(netutils.ParseIPSloppy("10.0.0.1"), true)
+		if err != nil {
+			return false, nil
+		}
+		allocator.ipAddressSynced = func() bool { return true }
+		return allocator.ready.Load(), nil
+	})
+	if err != nil {
+		t.Fatal(err)
+	}
+
+	// Check initial metrics for second CIDR
+	em2 := testMetrics{
+		free:      0,
+		used:      0,
+		allocated: 0,
+		errors:    0,
+	}
+	expectMetrics(t, "10.0.0.0/29", em2)
+
+	// Allocate all remaining IPs from second CIDR (should be 6 usable IPs)
+	allocatedFromCIDR2 := 0
+	for r.Free() > 0 && allocatedFromCIDR2 < 6 {
+		ip, err := r.AllocateNext()
+		if err != nil {
+			t.Fatalf("error allocating from second CIDR @ allocated: %d: %v", allocatedFromCIDR2, err)
+		}
+		allocatedFromCIDR2++
+		if found.Has(ip.String()) {
+			t.Fatalf("allocated %s twice", ip)
+		}
+		found.Insert(ip.String())
+	}
+
+	// Verify we allocated 6 IPs from second CIDR
+	if allocatedFromCIDR2 != 6 {
+		t.Fatalf("expected 6 IPs from second CIDR, got %d", allocatedFromCIDR2)
+	}
+
+	// Check total allocated IPs
+	totalAllocated := allocatedFromCIDR1 + allocatedFromCIDR2
+	if totalAllocated != 8 {
+		t.Fatalf("expected 8 total IPs allocated, got %d", totalAllocated)
+	}
+
+	// Check metrics after filling second CIDR
+	dynamicAllocatedCidr2, err := testutil.GetCounterMetricValue(clusterIPAllocations.WithLabelValues("10.0.0.0/29", "dynamic"))
+	if err != nil {
+		t.Errorf("failed to get %s value, err: %v", clusterIPAllocations.Name, err)
+	}
+	if dynamicAllocatedCidr2 != 6 {
+		t.Fatalf("Expected 6 dynamic allocations from second CIDR, received %f", dynamicAllocatedCidr2)
+	}
+
+	// Try to allocate more IPs - should fail since both CIDRs are exhausted
+	if _, err := r.AllocateNext(); err == nil {
+		t.Fatal("expected error when trying to allocate from exhausted CIDRs")
+	}
+
+	// Parse the CIDRs for proper IP containment checking
+	_, cidr1Net, err := netutils.ParseCIDRSloppy("192.168.1.0/30")
+	if err != nil {
+		t.Fatalf("failed to parse CIDR1: %v", err)
+	}
+	_, cidr2Net, err := netutils.ParseCIDRSloppy("10.0.0.0/29")
+	if err != nil {
+		t.Fatalf("failed to parse CIDR2: %v", err)
+	}
+
+	// Try to allocate the same IP addresses to generate static allocation errors
+	errorCount1 := 0
+	errorCount2 := 0
+	for s := range found {
+		ip := netutils.ParseIPSloppy(s)
+		if err := r.Allocate(ip); !errors.Is(err, ErrAllocated) {
+			t.Fatalf("expected ErrAllocated when trying to allocate existing IP %s, got: %v", s, err)
+		}
+		// Count which CIDR the error belongs to using proper CIDR containment
+		if cidr1Net.Contains(ip) {
+			errorCount1++
+		} else if cidr2Net.Contains(ip) {
+			errorCount2++
+		} else {
+			t.Fatalf("IP %s does not belong to any expected CIDR", ip.String())
+		}
+	}
+
+	// Check static allocation errors for first CIDR
+	staticErrorsCidr1, err := testutil.GetCounterMetricValue(clusterIPAllocationErrors.WithLabelValues("192.168.1.0/30", "static"))
+	if err != nil {
+		t.Errorf("failed to get %s value, err: %v", clusterIPAllocationErrors.Name, err)
+	}
+	if staticErrorsCidr1 != float64(errorCount1) {
+		t.Fatalf("Expected %d static allocation errors from first CIDR, received %f", errorCount1, staticErrorsCidr1)
+	}
+
+	// Check static allocation errors for second CIDR
+	staticErrorsCidr2, err := testutil.GetCounterMetricValue(clusterIPAllocationErrors.WithLabelValues("10.0.0.0/29", "static"))
+	if err != nil {
+		t.Errorf("failed to get %s value, err: %v", clusterIPAllocationErrors.Name, err)
+	}
+	if staticErrorsCidr2 != float64(errorCount2) {
+		t.Fatalf("Expected %d static allocation errors from second CIDR, received %f", errorCount2, staticErrorsCidr2)
+	}
+}
diff --git a/pkg/registry/core/service/ipallocator/ipallocator_test.go b/pkg/registry/core/service/ipallocator/ipallocator_test.go
index 9a3d5bfd7bfc2..4f030bcd7377a 100644
--- a/pkg/registry/core/service/ipallocator/ipallocator_test.go
+++ b/pkg/registry/core/service/ipallocator/ipallocator_test.go
@@ -26,6 +26,7 @@ import (
 	"time"
 
 	networkingv1 "k8s.io/api/networking/v1"
+	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
 	"k8s.io/apimachinery/pkg/runtime"
 	"k8s.io/apimachinery/pkg/util/sets"
 	"k8s.io/client-go/informers"
@@ -1012,3 +1013,218 @@ func BenchmarkIPAllocatorAllocateNextIPv6Size65535(b *testing.B) {
 		r.AllocateNext()
 	}
 }
+
+// TestUsedWithCIDRFiltering tests that Used() method only counts IPs within the allocator'"'"'s CIDR
+func TestUsedWithCIDRFiltering(t *testing.T) {
+	// Create an allocator for 192.168.1.0/24
+	_, cidr, err := netutils.ParseCIDRSloppy("192.168.1.0/24")
+	if err != nil {
+		t.Fatal(err)
+	}
+
+	// Create test components
+	client := fake.NewClientset()
+	informerFactory := informers.NewSharedInformerFactory(client, 0*time.Second)
+	ipInformer := informerFactory.Networking().V1().IPAddresses()
+	ipStore := ipInformer.Informer().GetIndexer()
+
+	r, err := NewIPAllocator(cidr, client.NetworkingV1(), ipInformer)
+	if err != nil {
+		t.Fatal(err)
+	}
+	r.ipAddressSynced = func() bool { return true }
+	defer r.Destroy()
+
+	// Add valid IPs (within CIDR) with correct labels
+	validIPAddr1 := &networkingv1.IPAddress{
+		ObjectMeta: metav1.ObjectMeta{
+			Name: "192.168.1.10",
+			Labels: map[string]string{
+				networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+				networkingv1.LabelManagedBy:       ControllerName,
+			},
+		},
+	}
+	validIPAddr2 := &networkingv1.IPAddress{
+		ObjectMeta: metav1.ObjectMeta{
+			Name: "192.168.1.20",
+			Labels: map[string]string{
+				networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+				networkingv1.LabelManagedBy:       ControllerName,
+			},
+		},
+	}
+	if err := ipStore.Add(validIPAddr1); err != nil {
+		t.Fatal(err)
+	}
+	if err := ipStore.Add(validIPAddr2); err != nil {
+		t.Fatal(err)
+	}
+
+	// Add invalid IPs (outside CIDR) with correct labels - these should not be counted
+	invalidIP1 := &networkingv1.IPAddress{
+		ObjectMeta: metav1.ObjectMeta{
+			Name: "192.168.2.10", // different subnet
+			Labels: map[string]string{
+				networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+				networkingv1.LabelManagedBy:       ControllerName,
+			},
+		},
+	}
+	invalidIP2 := &networkingv1.IPAddress{
+		ObjectMeta: metav1.ObjectMeta{
+			Name: "10.0.0.1", // completely different network
+			Labels: map[string]string{
+				networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+				networkingv1.LabelManagedBy:       ControllerName,
+			},
+		},
+	}
+	if err := ipStore.Add(invalidIP1); err != nil {
+		t.Fatal(err)
+	}
+	if err := ipStore.Add(invalidIP2); err != nil {
+		t.Fatal(err)
+	}
+
+	// Used() should only count valid IPs (2), not all IPs (4)
+	used := r.Used()
+	if used != 2 {
+		t.Errorf("Expected Used() to return 2 (only IPs in CIDR), got %d", used)
+	}
+}
+
+// TestFreeWithOverflowProtection tests the overflow protection in Free() method
+func TestFreeWithOverflowProtection(t *testing.T) {
+	testCases := []struct {
+		name         string
+		cidr         string
+		simulateSize uint64
+		simulateUsed int
+		expectedFree int
+	}{
+		{
+			name:         "normal case",
+			cidr:         "192.168.1.0/30", // size = 2 (4 total - 2 reserved)
+			simulateSize: 2,
+			simulateUsed: 1,
+			expectedFree: 1,
+		},
+		{
+			name:         "size exceeds MaxInt",
+			cidr:         "192.168.1.0/24",
+			simulateSize: uint64(math.MaxInt) + 1,
+			simulateUsed: 100,
+			expectedFree: math.MaxInt - 100,
+		},
+		{
+			name:         "used exceeds size (data inconsistency)",
+			cidr:         "192.168.1.0/30",
+			simulateSize: 2,
+			simulateUsed: 5, // More than size
+			expectedFree: 0,
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			_, cidr, err := netutils.ParseCIDRSloppy(tc.cidr)
+			if err != nil {
+				t.Fatal(err)
+			}
+
+			// Create test components
+			client := fake.NewClientset()
+			informerFactory := informers.NewSharedInformerFactory(client, 0*time.Second)
+			ipInformer := informerFactory.Networking().V1().IPAddresses()
+			ipStore := ipInformer.Informer().GetIndexer()
+
+			r, err := NewIPAllocator(cidr, client.NetworkingV1(), ipInformer)
+			if err != nil {
+				t.Fatal(err)
+			}
+			r.ipAddressSynced = func() bool { return true }
+			defer r.Destroy()
+
+			// Override the size for testing overflow scenarios
+			r.size = tc.simulateSize
+
+			// Mock the Used() method by adding IP addresses to simulate usage
+			for i := 0; i < tc.simulateUsed; i++ {
+				// Add valid IPs within the CIDR with correct labels
+				ip := &networkingv1.IPAddress{
+					ObjectMeta: metav1.ObjectMeta{
+						Name: fmt.Sprintf("192.168.1.%d", i+1),
+						Labels: map[string]string{
+							networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+							networkingv1.LabelManagedBy:       ControllerName,
+						},
+					},
+				}
+				if err := ipStore.Add(ip); err != nil {
+					t.Fatal(err)
+				}
+			}
+
+			free := r.Free()
+			if free != tc.expectedFree {
+				t.Errorf("Expected Free() to return %d, got %d", tc.expectedFree, free)
+			}
+		})
+	}
+}
+
+// TestUsedWithInvalidIPs tests that Used() handles invalid IP addresses gracefully
+func TestUsedWithInvalidIPs(t *testing.T) {
+	_, cidr, err := netutils.ParseCIDRSloppy("192.168.1.0/24")
+	if err != nil {
+		t.Fatal(err)
+	}
+
+	// Create test components
+	client := fake.NewClientset()
+	informerFactory := informers.NewSharedInformerFactory(client, 0*time.Second)
+	ipInformer := informerFactory.Networking().V1().IPAddresses()
+	ipStore := ipInformer.Informer().GetIndexer()
+
+	r, err := NewIPAllocator(cidr, client.NetworkingV1(), ipInformer)
+	if err != nil {
+		t.Fatal(err)
+	}
+	r.ipAddressSynced = func() bool { return true }
+	defer r.Destroy()
+
+	// Add valid IP with correct labels
+	validIP := &networkingv1.IPAddress{
+		ObjectMeta: metav1.ObjectMeta{
+			Name: "192.168.1.10",
+			Labels: map[string]string{
+				networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+				networkingv1.LabelManagedBy:       ControllerName,
+			},
+		},
+	}
+	if err := ipStore.Add(validIP); err != nil {
+		t.Fatal(err)
+	}
+
+	// Add invalid IP address (malformed) with correct labels
+	invalidIP := &networkingv1.IPAddress{
+		ObjectMeta: metav1.ObjectMeta{
+			Name: "invalid-ip-address",
+			Labels: map[string]string{
+				networkingv1.LabelIPAddressFamily: string(r.IPFamily()),
+				networkingv1.LabelManagedBy:       ControllerName,
+			},
+		},
+	}
+	if err := ipStore.Add(invalidIP); err != nil {
+		t.Fatal(err)
+	}
+
+	// Used() should only count the valid IP
+	used := r.Used()
+	if used != 1 {
+		t.Errorf("Expected Used() to return 1 (only valid IPs), got %d", used)
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestFreeWithOverflowProtection", "TestUsedWithCIDRFiltering", "TestUsedWithInvalidIPs"]

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
