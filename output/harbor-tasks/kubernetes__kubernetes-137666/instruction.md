StatefulSet pod revisions not updated when MaxUnavailableStatefulSet enabled
### What happened?

I decided to open this issue after investigating https://github.com/stackabletech/trino-operator/issues/854.

The high level description of the problem is that the stateful set controller doesn't update the pods according to the latest STS revision and the pods are left crashlooping **if the first revision is faulty** and can never become available. This doesn't happen if the `MaxUnavailableStatefulSet` feature is disabled.

Unfortunately I cannot create a much simpler example, but I attach the relevant controller log messages below.

Based on these logs you can see that:

1. The Stackable Operator for Trino (`trino-op` from now on) creates two `StatefulSet` objects with a single replica. They both expose the same problem, so for simplicity, I will use only one of them from now on (`trino-coordinator-default`).
2. The initial revision of this sts is `trino-coordinator-default-5f5598d4c8`. This first STS  revision has a faulty command args  and can never become available.
3. The `trino-op` updates the sts rapidly to the revision `trino-coordinator-default-787556ff59`. Now the STS command args are correct and the pods should be able to become ready.
4. The pod created initially is never updated so it never becomes ready.

To summarize my understanding, the sts revision is never updated if the pod never becomes ready, and the pod doesn't become ready because it has an old revision.

In the logs you see that `currentRevision` is never the same as `updateRevision`:

```
I0304 15: 25:06.514308       1 stateful_set_control.go: 146]"StatefulSet revisions" statefulSet = "kuttl-test-distinct-turtle/trino-coordinator-default" currentRevision = "trino-coordinator-default-5f5598d4c8" updateRevision = "trino-coordinator-default-787556ff59"
```

### What did you expect to happen?

The pod should become ready according to the `updateRevision` of the sts.
Again, this was indeed the case until `MaxUnavailableStatefulSet` feature gate was enabled.

### How can we reproduce it (as minimally and precisely as possible)?

I can reproduce this bug using the `trino-op` but unfortunately I don't have a minimal example.

### Anything else we need to know?

Attached are the relevant kube controller logs.

[kobe-controller-logs.txt](https://github.com/user-attachments/files/25745670/kobe-controller-logs.txt)

### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.34.0
Kustomize Version: v5.7.1
Server Version: v1.35.1
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
NAME="Fedora Linux"
VERSION="43 (Workstation Edition)"
RELEASE_TYPE=stable
ID=fedora
VERSION_ID=43
VERSION_CODENAME=""
PRETTY_NAME="Fedora Linux 43 (Workstation Edition)"
ANSI_COLOR="0;38;2;60;110;180"
LOGO=fedora-logo-icon
CPE_NAME="cpe:/o:fedoraproject:fedora:43"
DEFAULT_HOSTNAME="fedora"
HOME_URL="https://fedoraproject.org/"
DOCUMENTATION_URL="https://docs.fedoraproject.org/en-US/fedora/f43/"
SUPPORT_URL="https://ask.fedoraproject.org/"
BUG_REPORT_URL="https://bugzilla.redhat.com/"
REDHAT_BUGZILLA_PRODUCT="Fedora"
REDHAT_BUGZILLA_PRODUCT_VERSION=43
REDHAT_SUPPORT_PRODUCT="Fedora"
REDHAT_SUPPORT_PRODUCT_VERSION=43
SUPPORT_END=2026-12-02
VARIANT="Workstation Edition"
VARIANT_ID=workstation

$ uname -a
Linux fedora.fritz.box 6.18.13-200.fc43.x86_64 #1 SMP PREEMPT_DYNAMIC Thu Feb 19 19:54:01 UTC 2026 x86_64 GNU/Linux
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
**Base commit:** `36e93204ed1c72b93cbfc6ae126e97cc0e4072ad`

## Hints

/sig apps

I diffed the controller logs between 1.34 (where the bug is not present) and 1.35 (where the bug is present) and what I see is that 1.35 just doesn't update the Pod between "StatefulSet has unavailable Pods" and "Updated Status" whereas 1.34 does.

In fact, I never see this entry in the (1.35) logs: https://github.com/kubernetes/kubernetes/blob/a0e5f1aba53a16db2c2cd0a2cb33c60f43e4d984/pkg/controller/statefulset/stateful_set_control.go#L732

Here are the relevant snippets:

On 1.34:

```
stateful_set_control.go:605] "StatefulSet has unavailable Pods" logger="statefulset-controller" statefulSet="kuttl-test-logical-bulldog/trino-coordinator-default" unavailableReplicas=1 pod="kuttl-test-logical-bulldog/trino-coordinator-default-0"
stateful_set_control.go:697] "StatefulSet is waiting for Pod to update" logger="statefulset-controller" statefulSet="kuttl-test-logical-bulldog/trino-coordinator-default" pod="kuttl-test-logical-bulldog/trino-coordinator-default-0"
stateful_set_control.go:121] "Updated status" logger="statefulset-controller" statefulSet="kuttl-test-logical-bulldog/trino-coordinator-default" replicas=1 readyReplicas=0 currentReplicas=0 updatedReplicas=1
```

On 1.35:

```
stateful_set_control.go:641] "StatefulSet has unavailable Pods" statefulSet="kuttl-test-logical-bulldog/trino-coordinator-default" unavailableReplicas=1 pod="kuttl-test-logical-bulldog/trino-coordinator-default-0"
stateful_set_control.go:129] "Updated status" statefulSet="kuttl-test-logical-bulldog/trino-coordinator-default" replicas=1 readyReplicas=0 currentReplicas=1 updatedReplicas=0
```

I'm not sure if this is the correct fix, but the patch below solves the problem for us.

The problem was two fold:

1. The pods are not updated when unavailablePods==maxUnavailable but they can also never become available in that revision.
2. Seems there is a corner case when the STS only has one replica, in which case the Pod is also not updated.

```diff
diff --git a/pkg/controller/statefulset/stateful_set_control.go b/pkg/controller/statefulset/stateful_set_control.go
index dd339cc7814..94eef25cb8d 100644
--- a/pkg/controller/statefulset/stateful_set_control.go
+++ b/pkg/controller/statefulset/stateful_set_control.go
@@ -772,21 +772,26 @@ func updateStatefulSetAfterInvariantEstablished(ctx context.Context, ssc *defaul
 	}
 	metrics.UnavailableReplicas.WithLabelValues(set.Namespace, set.Name, podManagementPolicy).Set(float64(unavailablePods))
 
-	if unavailablePods >= maxUnavailable {
-		// log only when a true violation occurs.
-		if unavailablePods > maxUnavailable {
-			logger.V(4).Info("StatefulSet found unavailablePods, more than the allowed maxUnavailable",
-				"statefulSet", klog.KObj(set),
-				"unavailablePods", unavailablePods,
-				"maxUnavailable", maxUnavailable)
-		}
+	logger.V(4).Info("StatefulSet update checking for unavailable Pods",
+		"statefulSet", klog.KObj(set),
+		"unavailablePods", unavailablePods,
+		"maxUnavailable", maxUnavailable)
 
-		return &status, nil
+	if unavailablePods > maxUnavailable {
+		logger.V(2).Info("StatefulSet found unavailablePods, more than the allowed maxUnavailable",
+			"statefulSet", klog.KObj(set),
+			"unavailablePods", unavailablePods,
+			"maxUnavailable", maxUnavailable)
 	}
 
 	// Now we need to delete MaxUnavailable- unavailablePods
 	// start deleting one by one starting from the highest ordinal first
+	// For STSs with only one replica, we should delete the pod if it is unavailable,
+	// even if maxUnavailable is 1, to make progress.
 	podsToDelete := maxUnavailable - unavailablePods
+	if unavailablePods == 1 && maxUnavailable == 1 {
+		podsToDelete = 1
+	}
 
 	deletedPods := 0
 	for target := len(replicas) - 1; target >= updateMin && deletedPods < podsToDelete; target-- {
```


cc @krmayankk for visibility

generally, to fix the regression in 1.35, we will revert the gate state to false and backport that reversion to 1.35

then, in master / 1.36, we will fix the bug, add test coverage, and re-enable for 1.36 if appropriate

/priority critical-urgent
/kind regression

/assign @krmayankk 

please confirm the issue as reported, and if you can reproduce the regression, open the PR to master to disable the gate and backport the disablement to release-1.35


@liggitt I haven't seen @krmayankk working on k8s in recent months. I'm aware of the problem and looking at it just now. 

/assign 
/unassign krmayankk
