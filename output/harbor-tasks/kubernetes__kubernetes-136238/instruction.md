[kubelet] Unnecessary continuous reconciliation loop for DRA Pods due to non-kubelet-owned fields comparison
new: add test and log for kubelet (Kubernetes v1.35.0).

### What happened?

For Pods using Dynamic Resource Allocation (DRA), the kubelet status manager continuously logs "Pod status is inconsistent with cached status" and triggers a reconciliation loop (needsReconcile -> syncPod, every ~10s). This loop is unnecessary because no actual status changes are applied, but it adds avoidable load on kubelet, API server, and etcd.
kubelet log -v=4
```
I0115 16:58:36.998365  584662 status_manager.go:262] "Syncing all statuses"
I0115 16:58:36.999471  584662 status_manager.go:1175] "Pod status is inconsistent with cached status for pod, a reconciliation should be triggered" pod="default/dp-e7c13e09e5-5b4fd7bb6d-f95kc" statusDiff=<
	@@ -183,11 +183,5 @@
	    }
	   }
	  ],
	- "qosClass": "Guaranteed",
	- "resourceClaimStatuses": [
	-  {
	-   "name": "test-kubelet",
	-   "resourceClaimName": "dp-e7c13e09e5-5b4fd7bb6d-f95kc-test-kubelet-nh64j"
	-  }
	- ]
	+ "qosClass": "Guaranteed"
	 }
 >
I0115 16:58:36.999523  584662 kubelet_pods.go:1223] "Clean up pod workers for terminated pods"
......
I0115 16:58:37.002499  584662 status_manager.go:1065] "Patch status for pod" pod="default/dp-e7c13e09e5-5b4fd7bb6d-f95kc" podUID="d949fbdc-23b5-4a50-b57b-31ea53189032" patch="{\"metadata\":{\"uid\":\"d949fbdc-23b5-4a50-b57b-31ea53189032\"}}"
I0115 16:58:37.002510  584662 status_manager.go:1072] "Status for pod is up-to-date" pod="default/dp-e7c13e09e5-5b4fd7bb6d-f95kc" statusVersion=2
......
I0115 16:58:46.998609  584662 status_manager.go:262] "Syncing all statuses"
I0115 16:58:46.998627  584662 kubelet.go:2685] "SyncLoop (housekeeping)"
I0115 16:58:46.999152  584662 status_manager.go:1175] "Pod status is inconsistent with cached status for pod, a reconciliation should be triggered" pod="default/dp-e7c13e09e5-5b4fd7bb6d-f95kc" statusDiff=<
	@@ -183,11 +183,5 @@
	    }
	   }
	  ],
	- "qosClass": "Guaranteed",
	- "resourceClaimStatuses": [
	-  {
	-   "name": "test-kubelet",
	-   "resourceClaimName": "dp-e7c13e09e5-5b4fd7bb6d-f95kc-test-kubelet-nh64j"
	-  }
	- ]
	+ "qosClass": "Guaranteed"
	 }
 >
```


### What did you expect to happen?

The kubelet should ignore non-kubelet-owned fields (ResourceClaimStatuses, ExtendedResourceClaimStatus) during status comparison, and not trigger unnecessary reconciliation loops for DRA Pods.


### How can we reproduce it (as minimally and precisely as possible)?

1. Deploy a Kubernetes cluster with DRA enabled.
2. Create a Pod that uses DRA resources (with ResourceClaim).
3. Observe the kubelet logs and API server/etcd load.
4. Find the continuous "status inconsistent" logs and repeated reconciliation operations.

### Anything else we need to know?

This issue is caused by the `isPodStatusByKubeletEqual` function comparing the entire Pod status, including fields that are not managed by kubelet (populated by control plane components). A fix is provided in PR #136238.

### Kubernetes version

<details>
```console
$ ./kubelet --version
Kubernetes v1.35.0
```
</details>

$ ./kubelet --version
Kubernetes v1.35.0


### Cloud provider

<details>
self-hosted cluster
</details>
self-hosted cluster

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

Ubuntu 24.04.3 LTS

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
**Base commit:** `00bf52745a3cf864134ebb6551d7f79cf52794ee`
