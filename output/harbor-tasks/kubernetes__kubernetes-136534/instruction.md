panic: assignment to entry in nil map in pkg/util/resource.maxResourceList when pod container has nil Resources.Requests
## What happened?

When using `PodRequestsAndLimits()` to calculate pod resource requests, a panic occurs when comparing **spec** container resources with **status** container resources, and the spec has nil `Resources.Requests` while the status has populated values.

```
panic: assignment to entry in nil map

goroutine 586 [running]:
k8s.io/kubectl/pkg/util/resource.maxResourceList(0x0, 0x0?)
    /go/pkg/mod/k8s.io/kubectl@v0.34.0/pkg/util/resource/resource.go:179 +0x190
k8s.io/kubectl/pkg/util/resource.max(0x18?, {0x4003797b68, 0x2, 0x0?})
    /go/pkg/mod/k8s.io/kubectl@v0.34.0/pkg/util/resource/resource.go:157 +0x60
k8s.io/kubectl/pkg/util/resource.determineContainerReqs(...)
    /go/pkg/mod/k8s.io/kubectl@v0.34.0/pkg/util/resource/resource.go:149 +0x148
k8s.io/kubectl/pkg/util/resource.podRequests(...)
    /go/pkg/mod/k8s.io/kubectl@v0.34.0/pkg/util/resource/resource.go:57 +0x254
k8s.io/kubectl/pkg/util/resource.PodRequestsAndLimits(...)
    /go/pkg/mod/k8s.io/kubectl@v0.34.0/pkg/util/resource/resource.go:36 +0x20
```

## What did you expect to happen?

The function should handle nil `ResourceList` gracefully and return an empty or properly initialized `ResourceList` instead of panicking.

## How can we reproduce it?

The `determineContainerReqs` function compares spec and status resources:

```go
reqs := max(container.Resources.Requests,        // from pod.spec.containers[].resources.requests
            containerStatus.AllocatedResources,   // from pod.status.containerStatuses[].allocatedResources
            containerStatus.Resources.Requests)   // from pod.status.containerStatuses[].resources.requests
```

The panic occurs when:
1. `spec.containers[].resources.requests` is **nil** (pod doesn't define resource requests)
2. `status.containerStatuses[].resources.requests` has **values** (populated by kubelet or admission controllers)
3. Any code calls `PodRequestsAndLimits()` on that pod

This state can occur when:
- A LimitRange with `defaultRequest` applies defaults to pods without explicit requests
- The kubelet populates `status.containerStatuses[].resources` with actual values
- Virtual cluster (vcluster) syncers copy status back but don't modify spec

Example pod state that triggers the panic:
```json
{
  "spec": {
    "containers": [{
      "resources": {}
    }]
  },
  "status": {
    "containerStatuses": [{
      "resources": {
        "requests": {"cpu": "100m", "memory": "128Mi"}
      }
    }]
  }
}
```

## Root Cause Analysis

In `pkg/util/resource/resource.go`, the `max` function doesn't handle nil first argument:

```go
func max(a corev1.ResourceList, b ...corev1.ResourceList) corev1.ResourceList {
    result := a.DeepCopy()  // If 'a' is nil, result is nil
    for _, other := range b {
        maxResourceList(result, other)  // Passes nil to maxResourceList
    }
    return result
}
```

Then `maxResourceList` panics when trying to assign to the nil map:

```go
func maxResourceList(list, new corev1.ResourceList) {
    for name, quantity := range new {
        if value, ok := list[name]; !ok {
            list[name] = quantity.DeepCopy()  // PANIC: assignment to nil map
        }
        // ...
    }
}
```

## Suggested Fix

Add nil check in the `max` function:

```go
func max(a corev1.ResourceList, b ...corev1.ResourceList) corev1.ResourceList {
    result := a.DeepCopy()
    if result == nil {
        result = corev1.ResourceList{}
    }
    for _, other := range b {
        maxResourceList(result, other)
    }
    return result
}
```

## Environment

- Kubernetes version: v1.34.0 (kubectl v0.34.0)
- Discovered via: ArgoCD v3 using `k8s.io/kubectl@v0.34.0`

**Repository:** `kubernetes/kubernetes`
**Base commit:** `4ffc49fb3e4932b97b25450d8f4161cb1896f9f2`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig cli

/kind bug

Is this a duplicate of the issue fixed in https://github.com/kubernetes/kubernetes/pull/132895 ?

The stack trace shows v0.34.0, which had the issue. The fix in https://github.com/kubernetes/kubernetes/pull/132895 was backported to a later v0.34.x patch release… does this reproduce with the latest patch?

oh, https://github.com/kubernetes/kubernetes/pull/132895 fixed the method used by scheduler … looks like kubectl maybe has a copy of the same method that needs the same fix?

Yeah, seems like kubectl has a simplified copy of the scheduler’s resource helpers, and it needed the same nil-map guard

Actually I now noticed that in the scheduler fix (#132895): someone asked in review whether kubectl needed the same change, and the author said they’d follow up
