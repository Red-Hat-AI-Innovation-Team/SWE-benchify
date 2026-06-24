kubelet: per-container ephemeral-storage limit not enforced for restartable init containers (sidecars)
### What happened?

The kubelet's local-storage eviction logic that enforces per-container `resources.limits.ephemeral-storage` only iterates `pod.Spec.Containers`. Restartable init containers (`initContainers[].restartPolicy: Always`, i.e. native sidecars) are never compared against their declared per-container limit, so a sidecar can exceed its `limits.ephemeral-storage` indefinitely without triggering pod eviction.

`pkg/kubelet/eviction/eviction_manager.go`, `containerEphemeralStorageLimitEviction()`:
```go
thresholdsMap := make(map[string]*resource.Quantity)
for _, container := range pod.Spec.Containers {
    ephemeralLimit := container.Resources.Limits.StorageEphemeral()
    if ephemeralLimit != nil && ephemeralLimit.Value() != 0 {
        thresholdsMap[container.Name] = ephemeralLimit
    }
}
```
`pod.Spec.InitContainers` is never added to `thresholdsMap`. The subsequent loop over `podStats.Containers` *does* receive sidecar stats from CRI, but the `thresholdsMap[containerStat.Name]` lookup misses, so no comparison happens.

Note: the pod-level check (`podEphemeralStorageLimitEviction`) is not a reliable backstop, since it will only fire when every regular container also sets an ephemeral-storage limit (otherwise `PodLimits()` returns no ephemeral-storage entry and the function returns early). Also, LimitRange *does* default/enforce ephemeral-storage limits onto init containers at admission (`plugin/pkg/admission/limitranger/admission.go`), so an operator who configures a LimitRange reasonably expects the kubelet to honor the limit it stamped on the sidecar.

### What did you expect to happen?

A restartable init container that exceeds its `resources.limits.ephemeral-storage` should cause the pod to be evicted with reason `Evicted` / message referencing ephemeral-storage, identical to the behavior for regular containers.

### How can we reproduce it (as minimally and precisely as possible)?

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sidecar-ephemeral-repro
spec:
  initContainers:
  - name: sidecar
    image: busybox:1.36
    restartPolicy: Always
    command: ["sh", "-c", "dd if=/dev/zero of=/tmp/fill bs=1M count=500; sleep 1d"]
    resources:
      limits:
        ephemeral-storage: 10Mi
  containers:
  - name: main
    image: busybox:1.36
    command: ["sleep", "1d"]
    # deliberately no ephemeral-storage limit, to also disable the pod-level check
```
Apply, wait >30s. Observe: pod stays `Running`; `kubectl get pod sidecar-ephemeral-repro -o jsonpath='{.status.phase}'` never transitions to `Failed`. Replacing the sidecar with an identical regular container under `spec.containers` causes eviction within one monitoring interval.

### Anything else we need to know?

- Node-level disk-pressure eviction and taints are unaffected, so this is a per-container limit-semantics bug, not a node-DoS vector. Filing publicly for that reason; happy to re-route via the security process if SIG Node disagrees.
- Proposed fix is small: also iterate `pod.Spec.InitContainers` when building `thresholdsMap`, optionally restricted to `podutil.IsRestartableInitContainer(&c)` so run-to-completion init containers are skipped. Willing to send a PR + unit test in `pkg/kubelet/eviction/eviction_manager_test.go`.

### Kubernetes version

<details>

```console
$ kubectl version
# master @ HEAD (verified by code inspection; logic unchanged since sidecar containers GA)
```

</details>


### Cloud provider

<details>
N/A, this code path is platform-independent...
</details>


### OS version

<details>

```console
# On Linux:
$ cat /etc/os-release
# N/A — reproduces with any CRI that reports container writable-layer stats
$ uname -a
# N/A

# On Windows:
C:\> wmic os get Caption, Version, BuildNumber, OSArchitecture
# N/A
```

</details>


### Install tools

<details>
N/A
</details>


### Container runtime (CRI) and version (if applicable)

<details>
N/A — reproduces with any CRI that reports container writable-layer stats (containerd, CRI-O).
</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>
N/A
</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `0fe8ee192270e99e222cf04fb6492a4c584690eb`

## Hints

/sig node 
/area kubelet

/triage accepted
This is a valid use case. A PR to fix this issue is welcome.
