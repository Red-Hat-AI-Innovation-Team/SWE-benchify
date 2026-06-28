#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/registry/core/service/ipallocator/ipallocator.go b/pkg/registry/core/service/ipallocator/ipallocator.go
index 1b47f6247e82a..d7d66b0744de8 100644
--- a/pkg/registry/core/service/ipallocator/ipallocator.go
+++ b/pkg/registry/core/service/ipallocator/ipallocator.go
@@ -424,12 +424,44 @@ func (a *Allocator) Used() int {
 	if err != nil {
 		return 0
 	}
-	return len(ips)
+
+	// Count only IPs that belong to this allocator's CIDR
+	count := 0
+	for _, ipAddress := range ips {
+		// Parse the IP address string to netip.Addr type
+		ip, err := netip.ParseAddr(ipAddress.Name)
+		if err != nil {
+			continue
+		}
+		// Only count valid IPs that fall within this allocator's CIDR range
+		if a.prefix.Contains(ip) {
+			count++
+		}
+	}
+	return count
 }
 
 // for testing, it assumes this is the allocator is unique for the ipFamily
 func (a *Allocator) Free() int {
-	return int(a.size) - a.Used()
+	used := a.Used()
+
+	// Prevent integer overflow: if a.size exceeds int max value, use MaxInt
+	if a.size > math.MaxInt {
+		// In this case, used is definitely less than MaxInt, so no negative values
+		return math.MaxInt - used
+	}
+
+	size := int(a.size)
+
+	// Prevent negative return values due to data inconsistency
+	if used > size {
+		// This usually indicates data inconsistency, log a warning and return 0
+		klog.Warningf("IP allocator inconsistency detected: used (%d) > size (%d) for CIDR %s",
+			used, size, a.cidr.String())
+		return 0
+	}
+
+	return size - used
 }
 
 // Destroy
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
