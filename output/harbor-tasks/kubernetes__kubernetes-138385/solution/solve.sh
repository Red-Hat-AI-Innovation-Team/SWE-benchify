#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/registry/core/service/ipallocator/ipallocator.go b/pkg/registry/core/service/ipallocator/ipallocator.go
index 6613523f4df93..1b47f6247e82a 100644
--- a/pkg/registry/core/service/ipallocator/ipallocator.go
+++ b/pkg/registry/core/service/ipallocator/ipallocator.go
@@ -73,7 +73,7 @@ type Allocator struct {
 var _ Interface = &Allocator{}
 
 // NewIPAllocator returns an IP allocator associated to a network range
-// that use the IPAddress objectto track the assigned IP addresses,
+// that use the IPAddress object to track the assigned IP addresses,
 // using an informer cache as storage.
 func NewIPAllocator(
 	cidr *net.IPNet,
@@ -253,7 +253,11 @@ func (a *Allocator) allocateNextService(svc *api.Service, dryRun bool) (net.IP,
 	var offset uint64
 	switch {
 	case rangeSize >= math.MaxInt64:
-		offset = rand.Uint64()
+		offset = a.rand.Uint64()
+		// a.offsetAddress + offset should not overflow a 64 bit CIDR.
+		if math.MaxUint64-offset < uint64(a.rangeOffset) {
+			offset -= uint64(a.rangeOffset)
+		}
 	case rangeSize == 0:
 		return net.IP{}, ErrFull
 	default:
@@ -493,7 +497,7 @@ func (dry dryRunAllocator) EnableMetrics() {
 func addOffsetAddress(address netip.Addr, offset uint64) (netip.Addr, error) {
 	addressBytes := address.AsSlice()
 	addressBig := big.NewInt(0).SetBytes(addressBytes)
-	r := big.NewInt(0).Add(addressBig, big.NewInt(int64(offset))).Bytes()
+	r := big.NewInt(0).Add(addressBig, big.NewInt(0).SetUint64(offset)).Bytes()
 	// r must be 4 or 16 bytes depending of the ip family
 	// bigInt conversion to bytes will not take this into consideration
 	// and drop the leading zeros, so we have to take this into account.
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
