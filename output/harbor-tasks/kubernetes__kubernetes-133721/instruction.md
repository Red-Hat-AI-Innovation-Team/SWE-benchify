the crd has meet panic error when upgrade cluster to 1.33
### What happened?

After upgrade cluster to 1.33, we have meet a panic error log in the apiserver.

It seems old crd manifest can not adapter to 1.33.

The apiserver panic logs:
`
E0822 16:43:46.174528       1 wrap.go:57] "apiserver panic'd" method="PUT" URI="/apis/acrd.abc.com/v1beta2/namespaces/abc/acrd/test-aaa/status" auditID="af0187f8-b518-4523-9c4d-aebd8039655b"
http2: panic serving 7.0.0.31:2139: runtime error: invalid memory address or nil pointer dereference
goroutine 10581195070 [running]:
k8s.io/apiserver/pkg/endpoints/handlers/finisher.finishRequest.func1.1()
  k8s.io/apiserver/pkg/endpoints/handlers/finisher/finisher.go:105 +0xa5
panic({0x343d580?, 0x61817f0?})
  runtime/panic.go:792 +0x132
k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/model.(*Structural).Properties(0xc0008ee0a8?)
  k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/model/adaptor.go:72 +0x20
k8s.io/apiserver/pkg/cel/common.(*CorrelatedObject).Key(0xc00b9ab140, {0x3a1d1e5, 0x6})
  k8s.io/apiserver/pkg/cel/common/equality.go:266 +0x216
k8s.io/apiextensions-apiserver/pkg/registry/customresource.statusStrategy.ValidateUpdate({{{0x409d8d0, 0xc0a3af6260}, {0x4096720, 0x62071a0}, 0x1, {0x1, {{...}, {...}, {...}}, {0x40a2958, ...}, ...}, ...}}, ...)
  k8s.io/apiextensions-apiserver/pkg/registry/customresource/status_strategy.go:108 +0x1f2
k8s.io/apiserver/pkg/registry/rest.BeforeUpdate({0x40e82c0, 0xc0a3147590}, {0x40d06c0, 0xc0fff2a7e0}, {0x409d808, 0xc02116daa8}, {0x409d808, 0xc02116da58})
  k8s.io/apiserver/pkg/registry/rest/update.go:154 +0x4a2
k8s.io/apiserver/pkg/registry/generic/registry.(*Store).Update.func1({0x409d808, 0xc02116da58}, {0xc0d5416ea0?, 0x3a436a2?})
  k8s.io/apiserver/pkg/registry/generic/registry/store.go:755 +0x585`

It caused by this code:

<img width="2004" height="362" alt="Image" src="https://github.com/user-attachments/assets/20696318-f309-40bf-88d3-5ae46596c61f" />

### What did you expect to happen?

It should not panic when crd manifest miss schema.

### How can we reproduce it (as minimally and precisely as possible)?

The crd spec:
`
spec:
  conversion:
    strategy: None
  group: acrd.abc.com
  names:
    kind: Acrd
    listKind: AcrdList
    plural: acrds
    shortNames:
    - etcd
    singular: acrd
  preserveUnknownFields: true
  scope: Namespaced
  versions:
  - name: v1beta1
    served: false
    storage: false
  - name: v1beta2
    served: true
    storage: true
    subresources:
      status: {}
`

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
$ kubectl version
# paste output here
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
**Base commit:** `9630ab9581afbac9835d53f9e620a1240a1d2d91`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

Please fill out the rest of the bug template including the specific version and install tools.
/sig api-machinery

cc @JoelSpeed ref https://github.com/kubernetes/kubernetes/pull/129506

@BenTheElder 1.33.1, and it occuer when there does not have schema.openAPIV3Schema field

/assign @JoelSpeed
