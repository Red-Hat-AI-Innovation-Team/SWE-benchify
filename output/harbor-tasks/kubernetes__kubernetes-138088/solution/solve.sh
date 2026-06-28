#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/kubelet/kubelet_server_journal.go b/pkg/kubelet/kubelet_server_journal.go
index d85817a042a33..201edeefdea00 100644
--- a/pkg/kubelet/kubelet_server_journal.go
+++ b/pkg/kubelet/kubelet_server_journal.go
@@ -63,6 +63,13 @@ type journalServer struct{}
 // to journalctl on the current system. It supports content-encoding of
 // gzip to reduce total content size.
 func (journalServer) ServeHTTP(w http.ResponseWriter, req *http.Request) {
+	if req.Method != http.MethodGet && req.Method != http.MethodPost {
+		// Only GET and POST are supported for journal log queries.
+		w.Header().Set("Allow", "GET, POST")
+		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
+		return
+	}
+
 	var out io.Writer = w
 
 	nlq, errs := newNodeLogQuery(req.URL.Query())
diff --git a/pkg/kubelet/server/server.go b/pkg/kubelet/server/server.go
index fe96a4ab366ef..1d9b77a057564 100644
--- a/pkg/kubelet/server/server.go
+++ b/pkg/kubelet/server/server.go
@@ -482,6 +482,7 @@ func (s *Server) InstallAuthNotRequiredHandlers(ctx context.Context) {
 
 	s.addMetricsBucketMatcher("pods")
 	ws := new(restful.WebService)
+	ws.Filter(GETOnlyRestfulFilter())
 	ws.
 		Path(podsPath).
 		Produces(restful.MIME_JSON)
@@ -636,6 +637,7 @@ func (s *Server) InstallAuthRequiredHandlers(ctx context.Context) {
 
 	s.addMetricsBucketMatcher("containerLogs")
 	ws = new(restful.WebService)
+	ws.Filter(GETOnlyRestfulFilter())
 	ws.
 		Path("/containerLogs")
 	ws.Route(ws.GET("/{podNamespace}/{podID}/{containerName}").
@@ -649,6 +651,7 @@ func (s *Server) InstallAuthRequiredHandlers(ctx context.Context) {
 	// The /runningpods endpoint is used for testing only.
 	s.addMetricsBucketMatcher("runningpods")
 	ws = new(restful.WebService)
+	ws.Filter(GETOnlyRestfulFilter())
 	ws.
 		Path(runningPodsPath).
 		Produces(restful.MIME_JSON)
@@ -699,6 +702,7 @@ func (s *Server) InstallSystemLogHandler(enableSystemLogHandler bool, enableSyst
 	s.addMetricsBucketMatcher("logs")
 	if enableSystemLogHandler {
 		ws := new(restful.WebService)
+		ws.Filter(GETOnlyRestfulFilter())
 		ws.Path(logsPath)
 		ws.Route(ws.GET("").
 			To(s.getLogs).
@@ -770,6 +774,7 @@ func (s *Server) InstallProfilingHandler(enableProfilingLogHandler bool, enableC
 
 	// Setup pprof handlers.
 	ws := new(restful.WebService).Path(pprofBasePath)
+	ws.Filter(GETOnlyRestfulFilter())
 	ws.Route(ws.GET("/{subpath:*}").To(handlePprofEndpoint)).Doc("pprof endpoint")
 	s.restfulCont.Add(ws)
 
@@ -933,6 +938,32 @@ func (s *Server) getLogs(request *restful.Request, response *restful.Response) {
 	s.host.ServeLogs(response, request.Request)
 }
 
+// GETOnlyRestfulFilter allows only GET. Use on WebServices that register read-only
+// kubelet APIs.
+func GETOnlyRestfulFilter() restful.FilterFunction {
+	return AllowedMethodsRestfulFilter(http.MethodGet)
+}
+
+// AllowedMethodsRestfulFilter returns a restful.FilterFunction that rejects requests
+// whose HTTP method is not listed in allowed. It responds with 405 Method Not Allowed
+// and an Allow header listing the permitted methods (RFC 9110).
+func AllowedMethodsRestfulFilter(allowed ...string) restful.FilterFunction {
+	allowedSet := make(map[string]struct{}, len(allowed))
+	for _, m := range allowed {
+		allowedSet[m] = struct{}{}
+	}
+	allowHeader := strings.Join(allowed, ", ")
+
+	return func(req *restful.Request, resp *restful.Response, chain *restful.FilterChain) {
+		if _, ok := allowedSet[req.Request.Method]; ok {
+			chain.ProcessFilter(req, resp)
+			return
+		}
+		resp.Header().Set("Allow", allowHeader)
+		_ = resp.WriteErrorString(http.StatusMethodNotAllowed, "Method Not Allowed")
+	}
+}
+
 type execRequestParams struct {
 	podNamespace  string
 	podName       string
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
