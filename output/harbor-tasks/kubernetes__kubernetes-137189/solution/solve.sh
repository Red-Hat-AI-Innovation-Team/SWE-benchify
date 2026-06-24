#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion.go b/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion.go
index 3fbb89ad43f5e..2b607298caca8 100644
--- a/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion.go
+++ b/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion.go
@@ -17,16 +17,17 @@ limitations under the License.
 package fake
 
 import (
+	"bytes"
 	"context"
 	"fmt"
 	"io"
 	"net/http"
-	"strings"
 
 	v1 "k8s.io/api/core/v1"
 	policyv1 "k8s.io/api/policy/v1"
 	policyv1beta1 "k8s.io/api/policy/v1beta1"
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
+	"k8s.io/apimachinery/pkg/runtime"
 	"k8s.io/client-go/kubernetes/scheme"
 	restclient "k8s.io/client-go/rest"
 	fakerest "k8s.io/client-go/rest/fake"
@@ -63,12 +64,26 @@ func (c *fakePods) GetLogs(name string, opts *v1.PodLogOptions) *restclient.Requ
 	action.Subresource = "log"
 	action.Value = opts
 
-	_, _ = c.Fake.Invokes(action, &v1.Pod{})
+	defaultLogResponse := &runtime.Unknown{Raw: []byte("fake logs")}
+	obj, err := c.Fake.Invokes(action, defaultLogResponse)
+	logs := defaultLogResponse.Raw
+	if err == nil {
+		unknown, ok := obj.(*runtime.Unknown)
+		if !ok || unknown == nil {
+			err = fmt.Errorf("fake Pods.GetLogs expected reactor to return *runtime.Unknown, got %T", obj)
+		} else {
+			logs = unknown.Raw
+		}
+	}
+
 	fakeClient := &fakerest.RESTClient{
 		Client: fakerest.CreateHTTPClient(func(request *http.Request) (*http.Response, error) {
+			if err != nil {
+				return nil, err
+			}
 			resp := &http.Response{
 				StatusCode: http.StatusOK,
-				Body:       io.NopCloser(strings.NewReader("fake logs")),
+				Body:       io.NopCloser(bytes.NewReader(logs)),
 			}
 			return resp, nil
 		}),
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
