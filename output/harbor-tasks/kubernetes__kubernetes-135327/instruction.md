Alpha API warnings printed to apiserver logs on startup
### What happened?

After upgrading from 1.34.0 to 1.34.1, warnings about alpha APIs are being printed to the kube-apiserver log on startup:

```
2025-09-11T18:33:21.480458234Z stderr F I0911 18:33:21.479712       1 options.go:263] external host was not specified, using 172.17.0.4
2025-09-11T18:33:21.482567291Z stderr F I0911 18:33:21.482464       1 server.go:150] Version: v1.34.1
2025-09-11T18:33:21.482583037Z stderr F I0911 18:33:21.482494       1 server.go:152] "Golang settings" GOGC="" GOMAXPROCS="" GOTRACEBACK=""
2025-09-11T18:33:22.518763498Z stderr F W0911 18:33:22.518574       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=rbac.authorization.k8s.io/v1alpha1
2025-09-11T18:33:22.518788514Z stderr F W0911 18:33:22.518603       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=storage.k8s.io/v1alpha1
2025-09-11T18:33:22.518792838Z stderr F W0911 18:33:22.518612       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=admissionregistration.k8s.io/v1alpha1
2025-09-11T18:33:22.518795242Z stderr F W0911 18:33:22.518623       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=coordination.k8s.io/v1alpha2
2025-09-11T18:33:22.518798181Z stderr F W0911 18:33:22.518629       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=storagemigration.k8s.io/v1alpha1
2025-09-11T18:33:22.518800411Z stderr F W0911 18:33:22.518642       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=imagepolicy.k8s.io/v1alpha1
2025-09-11T18:33:22.518803122Z stderr F W0911 18:33:22.518648       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=scheduling.k8s.io/v1alpha1
2025-09-11T18:33:22.518805327Z stderr F W0911 18:33:22.518652       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=internal.apiserver.k8s.io/v1alpha1
2025-09-11T18:33:22.518807747Z stderr F W0911 18:33:22.518657       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=authentication.k8s.io/v1alpha1
2025-09-11T18:33:22.518813631Z stderr F W0911 18:33:22.518663       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=certificates.k8s.io/v1alpha1
2025-09-11T18:33:22.518816398Z stderr F W0911 18:33:22.518668       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=resource.k8s.io/v1alpha3
2025-09-11T18:33:22.518818657Z stderr F W0911 18:33:22.518673       1 api_enablement.go:112] alpha api enabled with emulated version 1.34 instead of the binary's version 1.34.1, this is unsupported, proceed at your own risk: api=node.k8s.io/v1alpha1
```

### What did you expect to happen?

No spurious logs

### How can we reproduce it (as minimally and precisely as possible)?

Run Kubernetes 1.34.1, look at apiserver logs

### Anything else we need to know?

Appears to be related to https://github.com/kubernetes/kubernetes/pull/133058, which should be checking major+minor versions only, not patch version - as the emulated version will never have a patch version set.

### Kubernetes version

<details>

```console
root@rke2-server-001:/# kubectl version
Client Version: v1.34.1+rke2r1
Kustomize Version: v5.7.1
Server Version: v1.34.1
```

</details>


### Cloud provider

n/a


### OS version

<details>

```console
root@rke2-server-001:/# cat /etc/os-release
PRETTY_NAME="Ubuntu 22.04.5 LTS"
NAME="Ubuntu"
VERSION_ID="22.04"
VERSION="22.04.5 LTS (Jammy Jellyfish)"
VERSION_CODENAME=jammy
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=jammy
```

</details>


### Install tools

<details>
rke2
</details>


### Container runtime (CRI) and version (if applicable)

<details>
containerd 2.1.4
</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

n/a

**Repository:** `kubernetes/kubernetes`
**Base commit:** `8d450ef773127374148abad4daaf28dac6cb2625`

## Hints

/sig api-machinery

cc @michaelasp @liggitt @Jefftree 

Thanks for the report, agree that bounding the check to just major/minor is the correct fix

We'd pick that narrow fix to 1.34 to resolve the log spam

/assign @michaelasp 

/triage accepted

Yep, should be a simple fix of stripping the patch version. I'll get on it once I get back from OOO in ~1 week. If it's needed more urgently than that someone can take it up. Sorry about that!
