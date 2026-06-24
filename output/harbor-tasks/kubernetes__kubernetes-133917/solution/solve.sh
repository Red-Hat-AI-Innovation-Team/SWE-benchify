#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/cli-runtime/pkg/genericclioptions/config_flags.go b/staging/src/k8s.io/cli-runtime/pkg/genericclioptions/config_flags.go
index 8dba84e34206f..b1fa9f9cf8208 100644
--- a/staging/src/k8s.io/cli-runtime/pkg/genericclioptions/config_flags.go
+++ b/staging/src/k8s.io/cli-runtime/pkg/genericclioptions/config_flags.go
@@ -170,12 +170,15 @@ func (f *ConfigFlags) toRawKubeConfigLoader() clientcmd.ClientConfig {
 	// bind auth info flag values to overrides
 	if f.CertFile != nil {
 		overrides.AuthInfo.ClientCertificate = *f.CertFile
+		overrides.AuthInfo.ClientCertificateData = nil
 	}
 	if f.KeyFile != nil {
 		overrides.AuthInfo.ClientKey = *f.KeyFile
+		overrides.AuthInfo.ClientKeyData = nil
 	}
 	if f.BearerToken != nil {
 		overrides.AuthInfo.Token = *f.BearerToken
+		overrides.AuthInfo.TokenFile = ""
 	}
 	if f.Impersonate != nil {
 		overrides.AuthInfo.Impersonate = *f.Impersonate
diff --git a/staging/src/k8s.io/client-go/tools/clientcmd/client_config.go b/staging/src/k8s.io/client-go/tools/clientcmd/client_config.go
index cd0a8649b187d..ed35891e5a1f9 100644
--- a/staging/src/k8s.io/client-go/tools/clientcmd/client_config.go
+++ b/staging/src/k8s.io/client-go/tools/clientcmd/client_config.go
@@ -533,6 +533,21 @@ func (config *DirectClientConfig) getAuthInfo() (clientcmdapi.AuthInfo, error) {
 		if err := merge(mergedAuthInfo, &config.overrides.AuthInfo); err != nil {
 			return clientcmdapi.AuthInfo{}, err
 		}
+
+		// Handle ClientKey/ClientKeyData conflict: if override sets ClientKey, also use override's ClientKeyData
+		// otherwise if original config has ClientKeyData set,
+		// validation returns error "client-key-data and client-key are both specified <user-name>"
+		if len(config.overrides.AuthInfo.ClientKey) > 0 || len(config.overrides.AuthInfo.ClientKeyData) > 0 {
+			mergedAuthInfo.ClientKey = config.overrides.AuthInfo.ClientKey
+			mergedAuthInfo.ClientKeyData = config.overrides.AuthInfo.ClientKeyData
+		}
+		// Handle ClientCertificate/ClientCertificateData conflict, if override sets ClientCertificate, also use override's ClientCertificateData
+		// otherwise if original config has ClientCertificateData set,
+		// validation returns error "client-cert-data and client-cert are both specified <user-name>"
+		if len(config.overrides.AuthInfo.ClientCertificate) > 0 || len(config.overrides.AuthInfo.ClientCertificateData) > 0 {
+			mergedAuthInfo.ClientCertificate = config.overrides.AuthInfo.ClientCertificate
+			mergedAuthInfo.ClientCertificateData = config.overrides.AuthInfo.ClientCertificateData
+		}
 	}
 
 	return *mergedAuthInfo, nil
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
