DRA: mixing shared multi-node and per-node claims can result in stuck pods
### What happened?

I found this while experimenting with PodGroup and Pod level claims, but it applies even when not using those alpha features. If a Pod enters the scoring phase with a mix of allocated and unallocated claims, it will get stuck in pending, with the unallocated claims never getting allocated. This is because the computeScore method does not properly handle claims that are already allocated along with ones allocated during the Filter phase.

### What did you expect to happen?

I expect it to allocate all claims and schedule the pod.

### How can we reproduce it (as minimally and precisely as possible)?

The easiest way is to have two pods that each have a per-pod claim, and share a multi-node claim. It must be a multi-node claim, because scoring is skipped if the pod can only run on one node. Thus, a node-local shared claim does not trigger this bug.

The manifest below creates a fake ResourceSlice with `allNodes`, and then uses a GPU claim per-node. You'll need a cluster with at least two GPU nodes, but what you will see is that the first pod schedules and the second pod gets stuck with the event message "running Score plugins: plugin "DynamicResources" failed with: number of allocations 1 is smaller than number of claims".

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceSlice
metadata:
  name: allnodes
spec:
  driver: allnodes.example.com
  pool:
    name: allnodes.example.com
    generation: 1
    resourceSliceCount: 1
  allNodes: true
  devices:
  - name: allnodes-example
---
apiVersion: resource.k8s.io/v1
kind: DeviceClass
metadata:
  name: allnodes.example.com
spec:
  selectors:
  - cel:
      expression: 'device.driver == "allnodes.example.com"'
---
apiVersion: resource.k8s.io/v1
kind: ResourceClaim
metadata:
  name: shared
spec:
  devices:
    requests:
    - name: shared
      exactly:
        deviceClassName: allnodes.example.com
---
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: gpu
spec:
  spec:
    devices:
      requests:
      - name: gpu
        exactly:
          deviceClassName: gpu.nvidia.com
---
apiVersion: v1
kind: Pod
metadata:
  name: pod0
spec:
  tolerations:
  - key: "cloud.google.com/compute-class"
    operator: "Exists"
    effect: "NoSchedule"
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
  containers:
  - name: smi
    image: ubuntu:22.04
    command: ["bash", "-c"]
    args: ["while [ 1 ]; do date; if ! nvidia-smi -L ; then echo Waiting...; sleep 30; fi ; done"]
    resources:
      claims:
      - name: shared
      - name: gpu
  restartPolicy: Never
  resourceClaims:
  - name: shared
    resourceClaimName: shared
  - name: gpu
    resourceClaimTemplateName: gpu
---
apiVersion: v1
kind: Pod
metadata:
  name: pod1
spec:
  tolerations:
  - key: "cloud.google.com/compute-class"
    operator: "Exists"
    effect: "NoSchedule"
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
  containers:
  - name: smi
    image: ubuntu:22.04
    command: ["bash", "-c"]
    args: ["while [ 1 ]; do date; if ! nvidia-smi -L ; then echo Waiting...; sleep 30; fi ; done"]
    resources:
      claims:
      - name: shared
      - name: gpu
  restartPolicy: Never
  resourceClaims:
  - name: shared
    resourceClaimName: shared
  - name: gpu
    resourceClaimTemplateName: gpu
```

### Anything else we need to know?

/wg device-management
/sig scheduling

/assign @johnbelamaric 

### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.35.3-dispatcher
Kustomize Version: v5.7.1
Server Version: v1.36.0-gke.1379000
```

</details>


### Cloud provider

<details>
GKEos
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
**Base commit:** `602860417ec6ddcac997745958dbacf412c73c65`
