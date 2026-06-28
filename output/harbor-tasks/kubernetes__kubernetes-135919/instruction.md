Kubelet cannot handle multiple ResourceClaims if one is already prepared
### What happened?

When using Dynamic Resource Allocation (DRA) with ResourceClaims, kubelet fails with:

    Error: internal error: unable to get claim info for ResourceClaim <name>

The error occurs when:
1. A first pod is created that references a single ResourceClaim.
2. A second pod is created that references the same ResourceClaim plus an additional one.

The failure happens during container creation, after scheduling succeeded.

The issue is reproducible using the dra-example-driver from kubernetes-sigs.

Potential spots where log may occurs:
https://github.com/kubernetes/kubernetes/blob/release-1.34/pkg/kubelet/cm/dra/manager.go#L417
https://github.com/kubernetes/kubernetes/blob/release-1.34/pkg/kubelet/cm/dra/manager.go#L442
https://github.com/kubernetes/kubernetes/blob/release-1.34/pkg/kubelet/cm/dra/manager.go#L498

### What did you expect to happen?

The second pod should successfully start with both ResourceClaims prepared.

Notably, the same set of ResourceClaims works correctly when requested in the opposite order:
- When the first pod uses both ResourceClaims, and the second pod uses only one - Works ✅ 
- When the first pod uses one ResourceClaim, and the second pod then uses both - Not working 🔴 

### How can we reproduce it (as minimally and precisely as possible)?

1. Deploy the dra-example-driver:
   https://github.com/kubernetes-sigs/dra-example-driver

2. Create two ResourceClaims:
```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaim
metadata:
  name: first-resource-claim
spec:
  devices:
    requests:
    - name: request
      exactly:
        deviceClassName: gpu.example.com
        allocationMode: ExactCount
        count: 1
---
apiVersion: resource.k8s.io/v1
kind: ResourceClaim
metadata:
  name: second-resource-claim
spec:
  devices:
    requests:
    - name: request
      exactly:
        deviceClassName: gpu.example.com
        allocationMode: ExactCount
        count: 1
```

3. Create a first pod that references only the first ResourceClaim:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pod-1
spec:
  containers:
  - name: container
    image: busybox
    command: ["sleep", "infinity"]
    resources:
      claims:
      - name: first
  resourceClaims:
  - name: first
    resourceClaimName: first-resource-claim
  restartPolicy: Never
```

4. Wait until the pod is running.
5. Create a second pod that references both ResourceClaims:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pod-2
spec:
  containers:
  - name: container
    image: busybox
    command: ["sleep", "infinity"]
    resources:
      claims:
      - name: first
      - name: second
  resourceClaims:
  - name: first
    resourceClaimName: first-resource-claim
  - name: second
    resourceClaimName: second-resource-claim
  restartPolicy: Never
```


### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
$ kubectl version
Version: v1.34.1+k3s1
```

</details>



### OS version

<details>

```console
# On Linux:
$ cat /etc/os-release
PRETTY_NAME="Ubuntu 24.04.3 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.3 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo
$ uname -a
Linux 6.11.0-17-generic #17~24.04.2-Ubuntu SMP PREEMPT_DYNAMIC Mon Jan 20 22:48:29 UTC 2 x86_64 x86_64 x86_64 GNU/Linux

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
**Base commit:** `cb077823fb053eb3dff39334f5d9d44d7512477e`

## Hints

/wg device-management

/sig node

/assign
