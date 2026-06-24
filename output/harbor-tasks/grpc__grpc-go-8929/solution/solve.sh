#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/internal/transport/client_stream.go b/internal/transport/client_stream.go
index cd8152ef13c7..ad382b0fda1c 100644
--- a/internal/transport/client_stream.go
+++ b/internal/transport/client_stream.go
@@ -19,6 +19,7 @@
 package transport
 
 import (
+	"fmt"
 	"sync/atomic"
 
 	"golang.org/x/net/http2"
@@ -28,6 +29,12 @@ import (
 	"google.golang.org/grpc/status"
 )
 
+// nonGRPCDataMaxLen is the maximum length of nonGRPCDataBuf.
+//
+// NOTE: If changed this value, you MUST update the corresponding test in:
+//   - /test/end2end_test.go:TestHTTPServerSendsNonGRPCHeaderSurfaceFurtherData
+const nonGRPCDataMaxLen = 1024
+
 // ClientStream implements streaming functionality for a gRPC client.
 type ClientStream struct {
 	Stream // Embed for common stream functionality.
@@ -46,7 +53,11 @@ type ClientStream struct {
 	// headerValid indicates whether a valid header was received.  Only
 	// meaningful after headerChan is closed (always call waitOnHeader() before
 	// reading its value).
-	headerValid      bool
+	headerValid bool
+
+	nonGRPCStatus  *status.Status // the initial status from the non-gRPC response header, finalized with collected data before closing.
+	nonGRPCDataBuf []byte         // stores the data of a non-gRPC response.
+
 	noHeaders        bool          // set if the client never received headers (set only after the stream is done).
 	headerChanClosed uint32        // set when headerChan is closed. Used to avoid closing headerChan multiple times.
 	bytesReceived    atomic.Bool   // indicates whether any bytes have been received on this stream
@@ -54,6 +65,29 @@ type ClientStream struct {
 	statsHandler     stats.Handler // nil for internal streams (e.g., health check, ORCA) where telemetry is not supported.
 }
 
+func (s *ClientStream) startNonGRPCDataCollection(st *status.Status) {
+	s.nonGRPCStatus = st
+	s.nonGRPCDataBuf = make([]byte, 0, nonGRPCDataMaxLen)
+}
+
+// finalizeNonGRPCStatus builds the terminal status by appending the collected
+// response body to the original non-gRPC status message.
+func (s *ClientStream) finalizeNonGRPCStatus() *status.Status {
+	msg := fmt.Sprintf("%s\ndata: %q", s.nonGRPCStatus.Message(), s.nonGRPCDataBuf)
+	return status.New(s.nonGRPCStatus.Code(), msg)
+}
+
+// handleNonGRPCData collects non-gRPC body from the given data frame.
+// It returns non-nil value when the stream should be closed with it.
+func (s *ClientStream) handleNonGRPCData(f *parsedDataFrame) *status.Status {
+	n := min(f.data.Len(), nonGRPCDataMaxLen-len(s.nonGRPCDataBuf))
+	s.nonGRPCDataBuf = append(s.nonGRPCDataBuf, f.data.ReadOnlyData()[0:n]...)
+	if len(s.nonGRPCDataBuf) >= nonGRPCDataMaxLen || f.StreamEnded() {
+		return s.finalizeNonGRPCStatus()
+	}
+	return nil
+}
+
 // Read reads an n byte message from the input stream.
 func (s *ClientStream) Read(n int) (mem.BufferSlice, error) {
 	b, err := s.Stream.read(n)
diff --git a/internal/transport/http2_client.go b/internal/transport/http2_client.go
index 0f4f3ef55764..133f5d706535 100644
--- a/internal/transport/http2_client.go
+++ b/internal/transport/http2_client.go
@@ -1231,6 +1231,23 @@ func (t *http2Client) handleData(f *parsedDataFrame) {
 			t.closeStream(s, io.EOF, true, http2.ErrCodeFlowControl, status.New(codes.Internal, err.Error()), nil, false)
 			return
 		}
+
+		if s.nonGRPCStatus != nil {
+			// The frame should be handled as a non-gRPC response body
+			st := s.handleNonGRPCData(f)
+			if st != nil {
+				t.closeStream(s, st.Err(), true, http2.ErrCodeProtocol, st, nil, true)
+				return
+			}
+			if w := s.fc.onRead(size); w > 0 {
+				t.controlBuf.put(&outgoingWindowUpdate{
+					streamID:  s.id,
+					increment: w,
+				})
+			}
+			return
+		}
+
 		dataLen := f.data.Len()
 		if f.Header().Flags.Has(http2.FlagDataPadded) {
 			if w := s.fc.onRead(size - uint32(dataLen)); w > 0 {
@@ -1475,6 +1492,17 @@ func (t *http2Client) operateHeaders(frame *http2.MetaHeadersFrame) {
 		return
 	}
 
+	// If we are collecting non-gRPC response data and receive a trailing
+	// HEADERS frame with END_STREAM, finalize the buffered data and close
+	// the stream.
+	if s.nonGRPCStatus != nil {
+		if endStream {
+			st := s.finalizeNonGRPCStatus()
+			t.closeStream(s, st.Err(), true, http2.ErrCodeProtocol, st, nil, true)
+		}
+		return
+	}
+
 	var (
 		// If a gRPC Response-Headers has already been received, then it means
 		// that the peer is speaking gRPC and we are in gRPC mode.
@@ -1575,7 +1603,12 @@ func (t *http2Client) operateHeaders(frame *http2.MetaHeadersFrame) {
 		}
 
 		se := status.New(grpcErrorCode, strings.Join(errs, "; "))
-		t.closeStream(s, se.Err(), true, http2.ErrCodeProtocol, se, nil, endStream)
+		if endStream {
+			t.closeStream(s, se.Err(), true, http2.ErrCodeProtocol, se, nil, true)
+			return
+		}
+
+		s.startNonGRPCDataCollection(se)
 		return
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
