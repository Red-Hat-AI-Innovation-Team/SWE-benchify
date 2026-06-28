#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/xds/internal/clients/xdsclient/xdsclient.go b/xds/internal/clients/xdsclient/xdsclient.go
index e8138198f6ec..93d26217480d 100644
--- a/xds/internal/clients/xdsclient/xdsclient.go
+++ b/xds/internal/clients/xdsclient/xdsclient.go
@@ -101,8 +101,6 @@ type XDSClient struct {
 // New returns a new xDS Client configured with the provided config.
 func New(config Config) (*XDSClient, error) {
 	switch {
-	case config.Node.ID == "":
-		return nil, errors.New("xdsclient: node ID is empty")
 	case config.ResourceTypes == nil:
 		return nil, errors.New("xdsclient: resource types map is nil")
 	case config.TransportBuilder == nil:
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
