kube-apiserver removes all managedFields if conversion webhook is not available
### What happened?

The apiserver removes all managedFields of an object under the following circumstances:
* object has managedField entries of multiple apiVersions
* conversion webhook is (potentially temporarily) not available/reachable
* there's a write on the object (via label, or client-side apply, SSA just returns an appropriate error, more details below)

### What did you expect to happen?

I would expect to get an error back from the apiserver in cases like this.
Removing all managedFields can have a big impact on the results of subsequent writes.

### How can we reproduce it (as minimally and precisely as possible)?

Required files:
[cr_cluster.yaml](https://github.com/user-attachments/files/25218546/cr_cluster.yaml)
[cr_cluster_ssa.yaml](https://github.com/user-attachments/files/25218545/cr_cluster_ssa.yaml)
[crd_cluster.yaml](https://github.com/user-attachments/files/25218548/crd_cluster.yaml)
[crd_cluster_no_conversion.yaml](https://github.com/user-attachments/files/25218547/crd_cluster_no_conversion.yaml)

Create a kind cluster (I was using kindest/node:v1.35.0)
```bash
kind create cluster
```

Deploy the CRD (without conversion configured for now so we are able to prepare managedFields with v1beta1 & v1beta2)
```bash
kubectl apply -f ./crd_cluster_no_conversion.yaml
```

Deploy and prepare the cluster
```bash
kubectl apply -f ./cr_cluster.yaml
kubectl label clusters.v1beta1.cluster.x-k8s.io cluster-1  def=ghi --overwrite
kubectl label clusters.v1beta2.cluster.x-k8s.io cluster-1  abc=def --overwrite
kubectl get cluster cluster-1 -o json --show-managed-fields | jq '.metadata.managedFields' | grep apiVersion
```

Update the CRD to configure an unreachable conversion webhook
```bash
kubectl apply -f ./crd_cluster.yaml
```

Try to update the cluster with SSA:
```
kubectl apply -f ./cr_cluster_ssa.yaml --server-side --field-manager=kubectl-ssa-test --show-managed-fields -o yaml
```
Output
```
Error from server: conversion webhook for cluster.x-k8s.io/v1beta2, Kind=Cluster failed: Post "https://webhook-service.system.svc:443/convert?timeout=30s": service "webhook-service" not found
```

Try to update the cluster with client-side apply
```
kubectl apply -f ./cr_cluster_ssa.yaml --show-managed-fields -o yaml
```
Output (managedFields are gone)
```
apiVersion: cluster.x-k8s.io/v1beta2
kind: Cluster
metadata:
  annotations:
    kubectl.kubernetes.io/last-applied-configuration: |
      {"apiVersion":"cluster.x-k8s.io/v1beta2","kind":"Cluster","metadata":{"annotations":{},"name":"cluster-1","namespace":"default"}}
  creationTimestamp: "2026-02-10T19:15:47Z"
  generation: 1
  labels:
    abc: def
    def: ghi
    jkl: def
  name: cluster-1
  namespace: default
  resourceVersion: "632"
  uid: 4d46d2ab-ab60-4164-86a3-2c5f45576c02
```

Check apiserver logs:
```
kubectl -n kube-system logs -f kube-apiserver-kind-control-plane | grep "SHOULD NOT"
```
Output
```
E0210 19:17:25.150030       1 fieldmanager.go:155] "[SHOULD NOT HAPPEN] failed to update managedFields" err="failed to update ManagedFields (default/cluster-1; cluster.x-k8s.io/v1beta2, Kind=Cluster): conversion webhook for cluster.x-k8s.io/v1beta2, Kind=Cluster failed: Post \"https://webhook-service.system.svc:443/convert?timeout=30s\": service \"webhook-service\" not found" versionKind="cluster.x-k8s.io/v1beta2, Kind=Cluster" namespace="default" name="cluster-1"
```



### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.35.0
Kustomize Version: v5.7.1
Server Version: v1.35.0
```

</details>


### Cloud provider

<details>
-
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
**Base commit:** `4f39ba34ffac132fbcc2743b9d8ae9d70ddb0010`

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

/cc @jpbetz 

The code the drops the managedFields is:

https://github.com/kubernetes/kubernetes/blob/f42571572d241a2cdeffa3962c0ccf1f59180113/staging/src/k8s.io/apimachinery/pkg/util/managedfields/internal/fieldmanager.go#L160

If we instead preserve the managedFields here from the live object the specific update's field changes won't be tracked, but at least the existing field ownership data will be preserved.

I fix along the lines of:

```diff
  func (f *FieldManager) UpdateNoErrors(liveObj, newObj runtime.Object, manager string) runtime.Object {
      obj, err := f.Update(liveObj, newObj, manager)
      if err != nil {
          atMostEverySecond.Do(func() {
              ns, name := "unknown", "unknown"
              if accessor, err := meta.Accessor(newObj); err == nil {
                  ns = accessor.GetNamespace()
                  name = accessor.GetName()
              }
              klog.ErrorS(err, "[SHOULD NOT HAPPEN] failed to update managedFields", "versionKind",
                  newObj.GetObjectKind().GroupVersionKind(), "namespace", ns, "name", name)
          })
+          // Preserve the managedFields from the live object rather than
+          // stripping them entirely, to avoid silent data loss when the
+          // managedFields update fails (e.g. due to an unavailable
+          // conversion webhook).
+          if liveAccessor, err := meta.Accessor(liveObj); err == nil {
+              if newAccessor, err := meta.Accessor(newObj); err == nil {
+                  newAccessor.SetManagedFields(liveAccessor.GetManagedFields())
+                  return newObj
+              }
+          }
          // Fall back to removing managedFields if we can't access the live object.
          RemoveObjectManagedFields(newObj)
          return newObj
      }
      return obj
  }
```

This fix would preserve the existing managed fields, which is I think the best option given that the conversion webhook is unavailable.
