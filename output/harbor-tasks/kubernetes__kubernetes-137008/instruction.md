Kubelet sets incorrect ownerReference apiVersion "core/v1" on PodCertificateRequest, breaking garbage collection
### What happened?

When the kubelet creates a `PodCertificateRequest` (KEP-4317, `certificates.k8s.io/v1alpha1`), it sets the owning Pod's `ownerReference.apiVersion` to `"core/v1"` instead of the correct `"v1"`. The Kubernetes garbage collector cannot resolve `"core/v1"` as a valid API group/version for Pods — Pods belong to the legacy core API group, which has no group prefix, so the correct `apiVersion` is simply `"v1"`.

This causes the GC controller in controller-manager to log errors like:

```
error syncing item" err="unable to get REST mapping for core/v1/Pod."
```

When a Pod is deleted, its associated `PodCertificateRequest` objects are never garbage collected.

### What did you expect to happen?

The `ownerReference` on `PodCertificateRequest` objects should use `apiVersion: "v1"` for Pod references, consistent with how all other core-group resources are referenced throughout Kubernetes. The garbage collector should be able to resolve the owner, and when a Pod is deleted, its `PodCertificateRequest` objects should be automatically cleaned up.

### How can we reproduce it (as minimally and precisely as possible)?

1. Enable the `PodCertificateRequest` feature gate (KEP-4317) on the kubelet and kube-apiserver.
2. Deploy a Pod that triggers creation of a `PodCertificateRequest` (e.g., a Pod configured to use pod-identity certificates).
3. Inspect the resulting `PodCertificateRequest` object:
   ```bash
   kubectl get podcertificaterequest -o json | jq '.items[].metadata.ownerReferences'
   ```
4. Observe that `apiVersion` is set to `"core/v1"` instead of `"v1"`.
5. Delete the owning Pod.
6. Observe that the `PodCertificateRequest` is **not** garbage collected.
7. Check the kube-controller-manager logs for GC errors:
   ```
   error syncing item" err="unable to get REST mapping for core/v1/Pod."
   ```

### Anything else we need to know?

**Workaround:** A external signer controller can patch the owner reference from `"core/v1"` to `"v1"` on every `PodCertificateRequest` it reconciles. This restores proper garbage collection behavior.

First bug report, not sure if this should be opened here or commented on https://github.com/kubernetes/enhancements/issues/4317

I am happy to submit the patch for this myself, after I figure out the contrib process. :) 

### Kubernetes version

Affects all versions implementing KEP-4317 (`PodCertificateRequest` / `certificates.k8s.io/v1alpha1` / `certificates.k8s.io/v1beta1`).

### Cloud provider

All

### OS version




### Install tools

_No response_

### Container runtime (CRI) and version (if applicable)




### Related plugins (CNI, CSI, ...) and versions (if applicable)

**Repository:** `kubernetes/kubernetes`
**Base commit:** `54241eea4dbdf1ac4bce83748f748a49488a70c1`

## Hints

There are no sig labels on this issue. Please add an appropriate label by using one of the following commands:
- `/sig <group-name>`
- `/wg <group-name>`
- `/committee <group-name>`

Please see the [group list](https://git.k8s.io/community/sig-list.md) for a listing of the SIGs, working groups, and committees available.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig auth

I can fix the Kubernetes node lifecycle management issue. Plan: Update the node controller to properly handle node registration, health checks, and termination. If **maintainer** thinks this needs fixing, please assign to me.

@mehrdadbn9 From my tests, all that needs to be fixed is https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/podcertificate/podcertificatemanager.go#L768 needs to be "v1" instead of "core/v1". Adding a test would be great as well. 

> [@mehrdadbn9](https://github.com/mehrdadbn9) From my tests, all that needs to be fixed is https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/podcertificate/podcertificatemanager.go#L768 needs to be "v1" instead of "core/v1". Adding a test would be great as well.

ok thanks if u needed any help i am  eager to help u with

/assign @mehrdadbn9 

/unassign @mehrdadbn9
