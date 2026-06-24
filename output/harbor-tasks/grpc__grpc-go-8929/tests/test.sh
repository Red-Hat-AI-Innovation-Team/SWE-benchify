#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/internal/transport/transport_test.go b/internal/transport/transport_test.go
index 66c80387c03c..e7b173cede2c 100644
--- a/internal/transport/transport_test.go
+++ b/internal/transport/transport_test.go
@@ -111,7 +111,9 @@ const (
 	notifyCall
 	misbehaved
 	encodingRequiredStatus
-	invalidHeaderField
+	invalidContentType
+	invalidContentTypeWithMultipleFrame
+	malformedHeader
 	delayRead
 	pingpong
 )
@@ -220,7 +222,21 @@ func (h *testStreamHandler) handleStreamEncodingRequiredStatus(s *ServerStream)
 	s.Read(math.MaxInt)
 }
 
-func (h *testStreamHandler) handleStreamInvalidHeaderField(s *ServerStream) {
+func (h *testStreamHandler) handleStreamInvalidContentType(s *ServerStream) {
+	headerFields := []hpack.HeaderField{}
+	headerFields = append(headerFields, hpack.HeaderField{Name: "content-type", Value: expectedInvalidHeaderField})
+	h.t.controlBuf.put(&headerFrame{
+		streamID:  s.id,
+		hf:        headerFields,
+		endStream: true,
+		cleanup: &cleanupStream{
+			streamID: s.id,
+			onWrite:  func() {},
+		},
+	})
+}
+
+func (h *testStreamHandler) handleStreamInvalidContentTypeWithMultipleFrame(s *ServerStream) {
 	headerFields := []hpack.HeaderField{}
 	headerFields = append(headerFields, hpack.HeaderField{Name: "content-type", Value: expectedInvalidHeaderField})
 	h.t.controlBuf.put(&headerFrame{
@@ -228,6 +244,38 @@ func (h *testStreamHandler) handleStreamInvalidHeaderField(s *ServerStream) {
 		hf:        headerFields,
 		endStream: false,
 	})
+	d1 := newBufferSlice([]byte("first"))
+	d1.Ref()
+	h.t.controlBuf.put(&dataFrame{
+		streamID:    s.id,
+		h:           nil,
+		data:        d1,
+		onEachWrite: func() {},
+	})
+	// Wait for the test to verify the first frame before sending the next frame.
+	<-h.notify
+	d2 := newBufferSlice([]byte(" second"))
+	d2.Ref()
+	h.t.controlBuf.put(&dataFrame{
+		streamID:    s.id,
+		h:           nil,
+		data:        d2,
+		onEachWrite: func() {},
+		endStream:   true,
+	})
+}
+
+func (h *testStreamHandler) handleStreamMalformedHeader(s *ServerStream) {
+	headerFields := []hpack.HeaderField{
+		{Name: ":status", Value: "200"},
+		{Name: "content-type", Value: "application/grpc"},
+		{Name: "x-bad-bin", Value: "!!!invalid-base64!!!"},
+	}
+	h.t.controlBuf.put(&headerFrame{
+		streamID:  s.id,
+		hf:        headerFields,
+		endStream: false,
+	})
 }
 
 // handleStreamDelayRead delays reads so that the other side has to halt on
@@ -425,12 +473,36 @@ func (s *server) start(t *testing.T, port int, serverConfig *ServerConfig, ht hT
 				})
 				wg.Done()
 			}()
-		case invalidHeaderField:
+		case invalidContentType:
+			go func() {
+				transport.HandleStreams(ctx, func(s *ServerStream) {
+					wg.Add(1)
+					go func() {
+						h.handleStreamInvalidContentType(s)
+						wg.Done()
+					}()
+				})
+				wg.Done()
+			}()
+		case invalidContentTypeWithMultipleFrame:
+			h.notify = make(chan struct{})
+			close(s.ready)
+			go func() {
+				transport.HandleStreams(ctx, func(s *ServerStream) {
+					wg.Add(1)
+					go func() {
+						h.handleStreamInvalidContentTypeWithMultipleFrame(s)
+						wg.Done()
+					}()
+				})
+				wg.Done()
+			}()
+		case malformedHeader:
 			go func() {
 				transport.HandleStreams(ctx, func(s *ServerStream) {
 					wg.Add(1)
 					go func() {
-						h.handleStreamInvalidHeaderField(s)
+						h.handleStreamMalformedHeader(s)
 						wg.Done()
 					}()
 				})
@@ -1638,8 +1710,8 @@ func (s) TestEncodingRequiredStatus(t *testing.T) {
 	s.Read(math.MaxInt)
 }
 
-func (s) TestInvalidHeaderField(t *testing.T) {
-	server, ct, cancel := setUp(t, 0, invalidHeaderField)
+func (s) TestInvalidContentType(t *testing.T) {
+	server, ct, cancel := setUp(t, 0, invalidContentType)
 	defer cancel()
 	callHdr := &CallHdr{
 		Host:   "localhost",
@@ -1660,8 +1732,53 @@ func (s) TestInvalidHeaderField(t *testing.T) {
 	server.stop()
 }
 
+func (s) TestNonGRPCDataCollectionAcrossMultipleFrames(t *testing.T) {
+	server, ct, cancel := setUp(t, 0, invalidContentTypeWithMultipleFrame)
+	defer cancel()
+	defer server.stop()
+	defer ct.Close(fmt.Errorf("closed manually by test"))
+	ctx, cancel := context.WithTimeout(context.Background(), defaultTestTimeout)
+	defer cancel()
+
+	select {
+	case <-server.ready:
+	case <-ctx.Done():
+		t.Fatal("timed out waiting for server handler to be initialized")
+	}
+
+	s, err := ct.NewStream(ctx, &CallHdr{Host: "localhost", Method: "foo"}, nil)
+	if err != nil {
+		t.Fatalf("failed to create the stream")
+	}
+
+	// After the first Data frame (without EOS), handleNonGRPCData returns
+	// nil so the stream stays open and continues collecting.
+	select {
+	case <-s.Done():
+		t.Fatal("stream closed after first DATA frame, want it to stay open")
+	case <-time.After(defaultTestShortTimeout):
+	}
+
+	// Signal the server to send the second Data frame with EOS.
+	close(server.h.notify)
+
+	_, err = s.readTo(make([]byte, 1))
+	if err == nil {
+		t.Fatal("Read succeeded, want error")
+	}
+	// Both frames should be collected: "first" + " second".
+	wantCode := codes.Internal
+	wantMsg := "first second"
+	if got := status.Code(err); got != wantCode {
+		t.Fatalf("Read error code = %v, want %v\nfull error: %v", got, wantCode, err)
+	}
+	if got := status.Convert(err).Message(); !strings.Contains(got, wantMsg) {
+		t.Fatalf("Read error message = %q, want it to contain %q", got, wantMsg)
+	}
+}
+
 func (s) TestHeaderChanClosedAfterReceivingAnInvalidHeader(t *testing.T) {
-	server, ct, cancel := setUp(t, 0, invalidHeaderField)
+	server, ct, cancel := setUp(t, 0, malformedHeader)
 	defer cancel()
 	defer server.stop()
 	defer ct.Close(fmt.Errorf("closed manually by test"))
@@ -2685,6 +2802,7 @@ func (s) TestClientDecodeHeader(t *testing.T) {
 		name            string
 		metaHeaderFrame *http2.MetaHeadersFrame
 		wantStatus      *status.Status
+		isNonGRPCStatus bool
 	}{
 		{
 			name: "valid_header",
@@ -2708,6 +2826,7 @@ func (s) TestClientDecodeHeader(t *testing.T) {
 				codes.Unknown,
 				"unexpected HTTP status code received from server: 200 (OK); malformed header: missing HTTP content-type",
 			),
+			isNonGRPCStatus: true,
 		},
 		{
 			name: "invalid_grpc_status",
@@ -2734,6 +2853,7 @@ func (s) TestClientDecodeHeader(t *testing.T) {
 				codes.Internal,
 				"malformed header: missing HTTP status; transport: received unexpected content-type \"application/json\"",
 			),
+			isNonGRPCStatus: true,
 		},
 		{
 			name: "invalid_content_type_with_http_status_504",
@@ -2747,6 +2867,7 @@ func (s) TestClientDecodeHeader(t *testing.T) {
 				codes.Unavailable,
 				"unexpected HTTP status code received from server: 504 (Gateway Timeout); transport: received unexpected content-type \"application/json\"",
 			),
+			isNonGRPCStatus: true,
 		},
 		{
 			name: "http_fallback_and_invalid_http_status",
@@ -2803,7 +2924,12 @@ func (s) TestClientDecodeHeader(t *testing.T) {
 			}
 
 			s.operateHeaders(tc.metaHeaderFrame)
-			got := cs.status
+			var got *status.Status
+			if tc.isNonGRPCStatus {
+				got = cs.nonGRPCStatus
+			} else {
+				got = cs.status
+			}
 			want := tc.wantStatus
 			if got.Code() != want.Code() || got.Message() != want.Message() {
 				t.Errorf("operateHeaders(%v) got status %q, want %q", tc.metaHeaderFrame, got, want)
diff --git a/test/end2end_test.go b/test/end2end_test.go
index 534c41672c25..c67f3cbd38d3 100644
--- a/test/end2end_test.go
+++ b/test/end2end_test.go
@@ -34,6 +34,7 @@ import (
 	"os"
 	"reflect"
 	"runtime"
+	"strconv"
 	"strings"
 	"sync"
 	"sync/atomic"
@@ -6373,8 +6374,8 @@ func (s *httpServer) writeHeader(framer *http2.Framer, sid uint32, headerFields
 	})
 }
 
-func (s *httpServer) writePayload(framer *http2.Framer, sid uint32, payload []byte) error {
-	return framer.WriteData(sid, false, payload)
+func (s *httpServer) writePayload(framer *http2.Framer, sid uint32, payload []byte, endStream bool) error {
+	return framer.WriteData(sid, endStream, payload)
 }
 
 func (s *httpServer) start(t *testing.T, lis net.Listener) {
@@ -6439,15 +6440,18 @@ func (s *httpServer) start(t *testing.T, lis net.Listener) {
 			}
 
 			response := s.responses[requestNum]
-			for _, header := range response.headers {
-				if err = s.writeHeader(framer, sid, header, false); err != nil {
+			hasPayload := response.payload != nil
+			hasTrailers := len(response.trailers) > 0
+			for i, header := range response.headers {
+				endStream := !hasPayload && !hasTrailers && i == len(response.headers)-1
+				if err = s.writeHeader(framer, sid, header, endStream); err != nil {
 					t.Errorf("Error at server-side while writing headers. Err: %v", err)
 					return
 				}
 				writer.Flush()
 			}
-			if response.payload != nil {
-				if err = s.writePayload(framer, sid, response.payload); err != nil {
+			if hasPayload {
+				if err = s.writePayload(framer, sid, response.payload, !hasTrailers); err != nil {
 					t.Errorf("Error at server-side while writing payload. Err: %v", err)
 					return
 				}
@@ -6815,6 +6819,117 @@ func (s) TestAuthorityHeader(t *testing.T) {
 	}
 }
 
+func (s) TestHTTPServerSendsNonGRPCHeaderSurfaceFurtherData(t *testing.T) {
+	const nonGRPCDataMaxLen = 1024
+	tests := []struct {
+		name      string
+		responses []httpServerResponse
+		wantCode  codes.Code
+		wantErr   string
+	}{
+		{
+			name: "non-gRPC content-type without payload",
+			responses: []httpServerResponse{
+				{
+					headers: [][]string{
+						{
+							":status", "200",
+							"content-type", "text/html",
+						},
+					},
+					// payload: nil
+				},
+			},
+			wantCode: codes.Unknown,
+			wantErr:  `unexpected HTTP status code received from server: 200 (OK); transport: received unexpected content-type "text/html"`,
+		},
+		{
+			name: "non-gRPC content-type with payload",
+			responses: []httpServerResponse{
+				{
+					headers: [][]string{
+						{
+							":status", "200",
+							"content-type", "text/html",
+						},
+					},
+					payload: []byte(`<html><body>Hello World</body></html>`),
+				},
+			},
+			wantCode: codes.Unknown,
+			wantErr: `unexpected HTTP status code received from server: 200 (OK); transport: received unexpected content-type "text/html"
+data: "<html><body>Hello World</body></html>"`,
+		},
+		{
+			name: "non-gRPC content-type with bytes payload length more than nonGRPCDataMaxLen",
+			responses: []httpServerResponse{
+				{
+					headers: [][]string{
+						{
+							":status", "200",
+							"content-type", "text/html",
+						},
+					},
+					payload: bytes.Repeat([]byte("a"), nonGRPCDataMaxLen+1),
+				},
+			},
+			wantCode: codes.Unknown,
+			wantErr: `unexpected HTTP status code received from server: 200 (OK); transport: received unexpected content-type "text/html"
+data: ` + strconv.Quote(strings.Repeat("a", nonGRPCDataMaxLen)),
+		},
+		{
+			name: "content-type not provided",
+			responses: []httpServerResponse{
+				{
+					headers: [][]string{{
+						":status", "502",
+					}},
+					payload: []byte("hello"),
+				},
+			},
+			wantCode: codes.Unavailable,
+			wantErr: `unexpected HTTP status code received from server: 502 (Bad Gateway); malformed header: missing HTTP content-type
+data: "hello"`,
+		},
+	}
+
+	for _, test := range tests {
+		t.Run(test.name, func(t *testing.T) {
+			lis, err := net.Listen("tcp", "localhost:0")
+			if err != nil {
+				t.Fatalf("net.Listen() failed: %v", err)
+			}
+			defer lis.Close()
+
+			hs := &httpServer{responses: test.responses}
+			hs.start(t, lis)
+
+			ctx, cancel := context.WithTimeout(context.Background(), defaultTestTimeout)
+			defer cancel()
+
+			cc, err := grpc.NewClient(lis.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
+			if err != nil {
+				t.Fatalf("grpc.NewClient() failed: %v", err)
+			}
+			defer cc.Close()
+
+			client := testgrpc.NewTestServiceClient(cc)
+			_, err = client.EmptyCall(ctx, &testpb.Empty{})
+			if err == nil {
+				t.Fatalf("EmptyCall() = nil; want non-nil error due to non-gRPC response")
+			}
+
+			if got, want := status.Code(err), test.wantCode; got != want {
+				t.Fatalf("Unexpected error code: got %v, want %v\nfull error:\n%v", got, want, err)
+			}
+
+			if got := status.Convert(err).Message(); got != test.wantErr {
+				t.Errorf("Unexpected error message: \ngot:\n%v\nwant:\n%v", got, test.wantErr)
+			}
+		})
+	}
+}
+
 // wrapCloseListener tracks Accepts/Closes and maintains a counter of the
 // number of open connections.
 type wrapCloseListener struct {
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -cpu 1,4 -timeout 7m google.golang.org/grpc/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["Test"]

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
