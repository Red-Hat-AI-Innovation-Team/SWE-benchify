#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/stats/opentelemetry/client_metrics.go b/stats/opentelemetry/client_metrics.go
index 420482b446cc..91bda9ac7b74 100644
--- a/stats/opentelemetry/client_metrics.go
+++ b/stats/opentelemetry/client_metrics.go
@@ -76,7 +76,7 @@ func getOrCreateCallInfo(ctx context.Context, cc *grpc.ClientConn, method string
 			target: cc.CanonicalTarget(),
 			method: determineMethod(method, opts...),
 		}
-		ctx = setCallInfo(ctx, ci)
+		ctx = context.WithValue(ctx, callInfoKey{}, ci)
 	}
 	return ctx, ci
 }
@@ -157,17 +157,6 @@ func (h *clientMetricsHandler) TagConn(ctx context.Context, _ *stats.ConnTagInfo
 // HandleConn exists to satisfy stats.Handler.
 func (h *clientMetricsHandler) HandleConn(context.Context, stats.ConnStats) {}
 
-// getOrCreateRPCAttemptInfo retrieves or creates an rpc attemptInfo object
-// and ensures it is set in the context along with the rpcInfo.
-func getOrCreateRPCAttemptInfo(ctx context.Context) (context.Context, *attemptInfo) {
-	ri := getRPCInfo(ctx)
-	if ri != nil {
-		return ctx, ri.ai
-	}
-	ri = &rpcInfo{ai: &attemptInfo{}}
-	return setRPCInfo(ctx, ri), ri.ai
-}
-
 // TagRPC implements per RPC attempt context management for metrics.
 func (h *clientMetricsHandler) TagRPC(ctx context.Context, info *stats.RPCTagInfo) context.Context {
 	// Numerous stats handlers can be used for the same channel. The cluster
@@ -187,17 +176,18 @@ func (h *clientMetricsHandler) TagRPC(ctx context.Context, info *stats.RPCTagInf
 		}
 		ctx = istats.SetLabels(ctx, labels)
 	}
-	ctx, ai := getOrCreateRPCAttemptInfo(ctx)
+	ctx, ri := getOrCreateClientRPCInfo(ctx)
+	ai := ri.ai
 	ai.startTime = time.Now()
 	ai.xdsLabels = labels.TelemetryLabels
 	ai.method = removeLeadingSlash(info.FullMethodName)
 
-	return setRPCInfo(ctx, &rpcInfo{ai: ai})
+	return ctx
 }
 
 // HandleRPC handles per RPC stats implementation.
 func (h *clientMetricsHandler) HandleRPC(ctx context.Context, rs stats.RPCStats) {
-	ri := getRPCInfo(ctx)
+	ri := clientRPCInfo(ctx)
 	if ri == nil {
 		logger.Error("ctx passed into client side stats handler metrics event handling has no client attempt data present")
 		return
diff --git a/stats/opentelemetry/client_tracing.go b/stats/opentelemetry/client_tracing.go
index 868d6a2fc9c1..718a634d7180 100644
--- a/stats/opentelemetry/client_tracing.go
+++ b/stats/opentelemetry/client_tracing.go
@@ -120,14 +120,14 @@ func (h *clientTracingHandler) HandleConn(context.Context, stats.ConnStats) {}
 
 // TagRPC implements per RPC attempt context management for traces.
 func (h *clientTracingHandler) TagRPC(ctx context.Context, info *stats.RPCTagInfo) context.Context {
-	ctx, ai := getOrCreateRPCAttemptInfo(ctx)
-	ctx, ai = h.traceTagRPC(ctx, ai, info.NameResolutionDelay)
-	return setRPCInfo(ctx, &rpcInfo{ai: ai})
+	ctx, ri := getOrCreateClientRPCInfo(ctx)
+	ctx, _ = h.traceTagRPC(ctx, ri.ai, info.NameResolutionDelay)
+	return ctx
 }
 
 // HandleRPC handles per RPC tracing implementation.
 func (h *clientTracingHandler) HandleRPC(ctx context.Context, rs stats.RPCStats) {
-	ri := getRPCInfo(ctx)
+	ri := clientRPCInfo(ctx)
 	if ri == nil {
 		logger.Error("ctx passed into client side tracing handler trace event handling has no client attempt data present")
 		return
diff --git a/stats/opentelemetry/opentelemetry.go b/stats/opentelemetry/opentelemetry.go
index 1031e9fa5647..d976e60c99f0 100644
--- a/stats/opentelemetry/opentelemetry.go
+++ b/stats/opentelemetry/opentelemetry.go
@@ -183,10 +183,6 @@ type callInfo struct {
 
 type callInfoKey struct{}
 
-func setCallInfo(ctx context.Context, ci *callInfo) context.Context {
-	return context.WithValue(ctx, callInfoKey{}, ci)
-}
-
 // getCallInfo returns the callInfo stored in the context, or nil
 // if there isn't one.
 func getCallInfo(ctx context.Context) *callInfo {
@@ -200,19 +196,41 @@ type rpcInfo struct {
 	ai *attemptInfo
 }
 
-type rpcInfoKey struct{}
+type clientRPCInfoKey struct{}
+type serverRPCInfoKey struct{}
 
-func setRPCInfo(ctx context.Context, ri *rpcInfo) context.Context {
-	return context.WithValue(ctx, rpcInfoKey{}, ri)
+// clientRPCInfo returns the rpcInfo stored in the context for client, or nil
+// if there isn't one.
+func clientRPCInfo(ctx context.Context) *rpcInfo {
+	ri, _ := ctx.Value(clientRPCInfoKey{}).(*rpcInfo)
+	return ri
 }
 
-// getRPCInfo returns the rpcInfo stored in the context, or nil
+// serverRPCInfo returns the rpcInfo stored in the context for server, or nil
 // if there isn't one.
-func getRPCInfo(ctx context.Context) *rpcInfo {
-	ri, _ := ctx.Value(rpcInfoKey{}).(*rpcInfo)
+func serverRPCInfo(ctx context.Context) *rpcInfo {
+	ri, _ := ctx.Value(serverRPCInfoKey{}).(*rpcInfo)
 	return ri
 }
 
+func getOrCreateClientRPCInfo(ctx context.Context) (context.Context, *rpcInfo) {
+	ri := clientRPCInfo(ctx)
+	if ri != nil {
+		return ctx, ri
+	}
+	ri = &rpcInfo{ai: &attemptInfo{}}
+	return context.WithValue(ctx, clientRPCInfoKey{}, ri), ri
+}
+
+func getOrCreateServerRPCInfo(ctx context.Context) (context.Context, *rpcInfo) {
+	ri := serverRPCInfo(ctx)
+	if ri != nil {
+		return ctx, ri
+	}
+	ri = &rpcInfo{ai: &attemptInfo{}}
+	return context.WithValue(ctx, serverRPCInfoKey{}, ri), ri
+}
+
 func removeLeadingSlash(mn string) string {
 	return strings.TrimLeft(mn, "/")
 }
diff --git a/stats/opentelemetry/server_metrics.go b/stats/opentelemetry/server_metrics.go
index 75d922e7974e..4db797803401 100644
--- a/stats/opentelemetry/server_metrics.go
+++ b/stats/opentelemetry/server_metrics.go
@@ -196,16 +196,17 @@ func (h *serverMetricsHandler) TagRPC(ctx context.Context, info *stats.RPCTagInf
 			method = "other"
 		}
 	}
-	ctx, ai := getOrCreateRPCAttemptInfo(ctx)
+	ctx, ri := getOrCreateServerRPCInfo(ctx)
+	ai := ri.ai
 	ai.startTime = time.Now()
 	ai.method = removeLeadingSlash(method)
 
-	return setRPCInfo(ctx, &rpcInfo{ai: ai})
+	return ctx
 }
 
 // HandleRPC handles per RPC stats implementation.
 func (h *serverMetricsHandler) HandleRPC(ctx context.Context, rs stats.RPCStats) {
-	ri := getRPCInfo(ctx)
+	ri := serverRPCInfo(ctx)
 	if ri == nil {
 		logger.Error("ctx passed into server side stats handler metrics event handling has no server call data present")
 		return
diff --git a/stats/opentelemetry/server_tracing.go b/stats/opentelemetry/server_tracing.go
index 0e2181bf114c..c267ba1ed0aa 100644
--- a/stats/opentelemetry/server_tracing.go
+++ b/stats/opentelemetry/server_tracing.go
@@ -40,9 +40,9 @@ func (h *serverTracingHandler) initializeTraces() {
 
 // TagRPC implements per RPC attempt context management for traces.
 func (h *serverTracingHandler) TagRPC(ctx context.Context, _ *stats.RPCTagInfo) context.Context {
-	ctx, ai := getOrCreateRPCAttemptInfo(ctx)
-	ctx, ai = h.traceTagRPC(ctx, ai)
-	return setRPCInfo(ctx, &rpcInfo{ai: ai})
+	ctx, ri := getOrCreateServerRPCInfo(ctx)
+	ctx, _ = h.traceTagRPC(ctx, ri.ai)
+	return ctx
 }
 
 // traceTagRPC populates context with new span data using the TextMapPropagator
@@ -67,7 +67,7 @@ func (h *serverTracingHandler) traceTagRPC(ctx context.Context, ai *attemptInfo)
 
 // HandleRPC handles per RPC tracing implementation.
 func (h *serverTracingHandler) HandleRPC(ctx context.Context, rs stats.RPCStats) {
-	ri := getRPCInfo(ctx)
+	ri := serverRPCInfo(ctx)
 	if ri == nil {
 		logger.Error("ctx passed into server side tracing handler trace event handling has no server call data present")
 		return
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
