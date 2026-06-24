#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/kube-aggregator/pkg/apiserver/handler_proxy.go b/staging/src/k8s.io/kube-aggregator/pkg/apiserver/handler_proxy.go
index d95a271af76ee..ecf1800e05b13 100644
--- a/staging/src/k8s.io/kube-aggregator/pkg/apiserver/handler_proxy.go
+++ b/staging/src/k8s.io/kube-aggregator/pkg/apiserver/handler_proxy.go
@@ -37,6 +37,7 @@ import (
 	"k8s.io/klog/v2"
 	apiregistrationv1api "k8s.io/kube-aggregator/pkg/apis/apiregistration/v1"
 	apiregistrationv1apihelper "k8s.io/kube-aggregator/pkg/apis/apiregistration/v1/helper"
+	"k8s.io/kube-aggregator/pkg/controllers/status/remote"
 )
 
 const (
@@ -219,16 +220,7 @@ func (r *proxyHandler) updateAPIService(apiService *apiregistrationv1api.APIServ
 
 	proxyClientCert, proxyClientKey := r.proxyCurrentCertKeyContent()
 
-	transportConfig := &transport.Config{
-		TLS: transport.TLSConfig{
-			Insecure:   apiService.Spec.InsecureSkipTLSVerify,
-			ServerName: apiService.Spec.Service.Name + "." + apiService.Spec.Service.Namespace + ".svc",
-			CertData:   proxyClientCert,
-			KeyData:    proxyClientKey,
-			CAData:     apiService.Spec.CABundle,
-		},
-		DialHolder: r.proxyTransportDial,
-	}
+	transportConfig := remote.BuildTransportConfig(r.proxyTransportDial, proxyClientCert, proxyClientKey, apiService)
 	transportConfig.Wrap(x509metrics.NewDeprecatedCertificateRoundTripperWrapperConstructor(
 		x509MissingSANCounter,
 		x509InsecureSHA1Counter,
diff --git a/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller.go b/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller.go
index 22e78b3b9d879..c31ec33254bbd 100644
--- a/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller.go
+++ b/staging/src/k8s.io/kube-aggregator/pkg/controllers/status/remote/remote_available_controller.go
@@ -32,6 +32,7 @@ import (
 	apierrors "k8s.io/apimachinery/pkg/api/errors"
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
 	"k8s.io/apimachinery/pkg/labels"
+	utilnet "k8s.io/apimachinery/pkg/util/net"
 	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
 	"k8s.io/apimachinery/pkg/util/wait"
 	"k8s.io/apiserver/pkg/util/proxy"
@@ -157,6 +158,25 @@ func New(
 	return c, nil
 }
 
+// BuildTransportConfig builds a transport.Config for an APIService.
+// It ignores TLS verification if InsecureSkipTLSVerify is true.
+func BuildTransportConfig(
+	proxyTransportDial *transport.DialHolder,
+	proxyClientCert, proxyClientKey []byte,
+	apiService *apiregistrationv1.APIService,
+) *transport.Config {
+	return &transport.Config{
+		TLS: transport.TLSConfig{
+			Insecure:   apiService.Spec.InsecureSkipTLSVerify,
+			ServerName: apiService.Spec.Service.Name + "." + apiService.Spec.Service.Namespace + ".svc",
+			CertData:   proxyClientCert,
+			KeyData:    proxyClientKey,
+			CAData:     apiService.Spec.CABundle,
+		},
+		DialHolder: proxyTransportDial,
+	}
+}
+
 func (c *AvailableConditionController) sync(key string) error {
 	originalAPIService, err := c.apiServiceLister.Get(key)
 	if apierrors.IsNotFound(err) {
@@ -247,21 +267,12 @@ func (c *AvailableConditionController) sync(key string) error {
 	// actually try to hit the discovery endpoint when it isn't local and when we're routing as a service.
 	if apiService.Spec.Service != nil && c.serviceResolver != nil {
 		// if a particular transport was specified, use that otherwise build one
-		// construct an http client that will ignore TLS verification (if someone owns the network and messes with your status
-		// that's not so bad) and sets a very short timeout.  This is a best effort GET that provides no additional information
-		transportConfig := &transport.Config{
-			TLS: transport.TLSConfig{
-				Insecure: true,
-			},
-			DialHolder: c.proxyTransportDial,
-		}
-
+		var proxyClientCert, proxyClientKey []byte
 		if c.proxyCurrentCertKeyContent != nil {
-			proxyClientCert, proxyClientKey := c.proxyCurrentCertKeyContent()
-
-			transportConfig.TLS.CertData = proxyClientCert
-			transportConfig.TLS.KeyData = proxyClientKey
+			proxyClientCert, proxyClientKey = c.proxyCurrentCertKeyContent()
 		}
+
+		transportConfig := BuildTransportConfig(c.proxyTransportDial, proxyClientCert, proxyClientKey, apiService)
 		restTransport, err := transport.New(transportConfig)
 		if err != nil {
 			return err
@@ -318,6 +329,7 @@ func (c *AvailableConditionController) sync(key string) error {
 				select {
 				case err = <-errCh:
 					if err != nil {
+						utilnet.CloseIdleConnectionsFor(restTransport)
 						results <- fmt.Errorf("failing or missing response from %v: %w", discoveryURL, err)
 						return
 					}
@@ -325,6 +337,7 @@ func (c *AvailableConditionController) sync(key string) error {
 					// we had trouble with slow dial and DNS responses causing us to wait too long.
 					// we added this as insurance
 				case <-time.After(6 * time.Second):
+					utilnet.CloseIdleConnectionsFor(restTransport)
 					results <- fmt.Errorf("timed out waiting for %v", discoveryURL)
 					return
 				}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
