[cli-runtime] [client-go] ConfigFlags when set cert/key fields get validation error when merging with kubeconfig data
### What happened?

When using ConfigFlags with CertFile and KeyFile set to override a kubeconfig configuration that contains inline certificate data (ClientCertificateData and ClientKeyData), the configuration merge process fails with validation errors: 

```sh
invalid configuration: [client-cert-data and client-cert are both specified for <user>. client-cert-data will override., client-key-data and client-key are both specified for <user>; client-key-data will override]
```

Also ConfigFlags does not allow to set ClientCertificateData and ClientKeyData.

### What did you expect to happen?

When  user sets CertFile of ConfigFlags expects override value of `overrides.AuthInfo.ClientCertData` to be set nil.
When  user sets KeyFile of ConfigFlags expects override value of `overrides.AuthInfo.ClientKeyData` to be set nil.

And during merge process override value are both taken into account. 

### How can we reproduce it (as minimally and precisely as possible)?

1) prepare kubeconfig with ClientCertData and ClientKeyData
2) instantiate ConfigFlags with CertFile and KeyFile
3) call to configFlags.ToRESTConfig() -> receive validation error. 

<details>
<summary>go code to reproduce</summary>

```go
package main

import (
	"fmt"
	"os"
	"path/filepath"

	"k8s.io/cli-runtime/pkg/genericclioptions"
	"k8s.io/client-go/tools/clientcmd"
	clientcmdapi "k8s.io/client-go/tools/clientcmd/api"
)

func main() {
	// 1) Prepare kubeconfig with ClientCertificateData and ClientKeyData
	tmpDir, err := os.MkdirTemp("", "kubeconfig-test")
	if err != nil {
		fmt.Printf("Failed to create temp dir: %v\n", err)
		return
	}
	defer os.RemoveAll(tmpDir)

	kubeconfigPath := filepath.Join(tmpDir, "kubeconfig")

	baseConfig := &clientcmdapi.Config{
		Clusters: map[string]*clientcmdapi.Cluster{
			"test-cluster": {
				Server:                   "https://example.com:6443",
				CertificateAuthorityData: []byte("fake-ca-data"),
			},
		},
		AuthInfos: map[string]*clientcmdapi.AuthInfo{
			"test-user": {
				ClientCertificateData: []byte("base-config-cert-data"),
				ClientKeyData:         []byte("base-config-key-data"),
			},
		},
		Contexts: map[string]*clientcmdapi.Context{
			"test-context": {
				Cluster:  "test-cluster",
				AuthInfo: "test-user",
			},
		},
		CurrentContext: "test-context",
	}

	err = clientcmd.WriteToFile(*baseConfig, kubeconfigPath)
	if err != nil {
		fmt.Printf("Failed to write kubeconfig: %v\n", err)
		return
	}

	certFile := filepath.Join(tmpDir, "client.crt")
	keyFile := filepath.Join(tmpDir, "client.key")

	err = os.WriteFile(certFile, []byte("override-cert-content"), 0600)
	if err != nil {
		fmt.Printf("Failed to create cert file: %v\n", err)
		return
	}

	err = os.WriteFile(keyFile, []byte("override-key-content"), 0600)
	if err != nil {
		fmt.Printf("Failed to create key file: %v\n", err)
		return
	}

	err = os.Setenv("KUBECONFIG", kubeconfigPath)
	if err != nil {
		fmt.Printf("Failed to set KUBECONFIG env var: %v\n", err)
		return
	}
	defer os.Unsetenv("KUBECONFIG")

	// 2) Instantiate ConfigFlags with CertFile and KeyFile
	configFlags := &genericclioptions.ConfigFlags{
		CertFile: &certFile,
		KeyFile:  &keyFile,
	}

	// 3) Call configFlags.ToRESTConfig()
	_, err = configFlags.ToRESTConfig()
	if err != nil {
		fmt.Printf("ERROR: %v\n", err)
		return
	}
	fmt.Println("SUCCESS: ToRESTConfig() worked with no error!")
}

```

</details>

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
kubectl version
Client Version: v1.32.2
Server Version: v1.32.2
```

</details>


### Cloud provider

<details>

</details>


### OS version

<details>



```console
# On Linux:
$ cat /etc/os-release
# paste output here
$ uname -a
# paste output here

# On Windows:
C:\> wmic os get Caption, Version, BuildNumber, OSArchitecture
# paste output here
```

</details>


### Install tools

<details>

</details>


### Container runtime (CRI) and version (if applicable)

<details>

</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>

</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `7104c1e426b92025aa25083edcd3dac128f3e206`
