kubectl events --for does not show events where involvedObject.apiVersion is missing
### What happened?

When running `kubectl events --for Node/<node-name>`, some events (such as OOMKilling events from kernel-monitor node-problem-detector) do not appear, even though they are visible in `kubectl get events`. Upon investigation, these missing events have an `involvedObject` without an `apiVersion` field.

Example:

This event is **not** shown by `kubectl events --for Node/<node-name>`:

```yaml
kind: Event
count: 1074
eventTime: null
firstTimestamp: "2025-10-07T22:00:52Z"
involvedObject:
  kind: Node
  name: XXXXXXXXXX
  uid: XXXXXXXXXX
# apiVersion is missing
message: ...
reason: OOMKilling
source:
  component: kernel-monitor
```

But this event **is** shown:
```yaml
kind: Event
count: 11
eventTime: null
firstTimestamp: "2025-10-09T01:19:49Z"
involvedObject:
  apiVersion: v1
  kind: Node
  name: XXXXXXXXXX
  uid: df71ea00-f008-41b2-bb6e-a21466b7bf38
# apiVersion is present
message: ...
reason: DisruptionBlocked
source:
  component: karpenter
```

The relevant code in `kubectl events` sets a field selector:
```go
listOptions.FieldSelector = fields.AndSelectors(
    fields.OneTermEqualSelector("involvedObject.kind", o.forGVK.Kind),
    fields.OneTermEqualSelector("involvedObject.apiVersion", o.forGVK.GroupVersion().String()),
    fields.OneTermEqualSelector("involvedObject.name", o.forName)).String()
```
Events missing `involvedObject.apiVersion` are excluded from the results.

### What did you expect to happen?

Events for the specified Node should be shown even if their `involvedObject.apiVersion` field is missing, as long as `kind` and `name` match.

### How can we reproduce it (as minimally and precisely as possible)?

1. Install node-problem-detector in the cluster
2. Generate a node event with OOMKilling (e.g., run a memory-hogging process on a node).
3. Ensure an event is created that is visible in `kubectl get events` but missing `involvedObject.apiVersion`.
4. Run `kubectl events --for Node/<node-name>`
5. Observe that the event does not appear, but it does with `kubectl get events`.

### Anything else we need to know?

This bug can be worked around by omitting `--for`, but that makes filtering by object impossible. The filtering logic should be more tolerant to missing fields.

### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.34.0
```

</details>

### Cloud provider

<details>

AWS EC2

</details>

### OS version

<details>

```console
# On Linux:
$ cat /etc/os-release
PRETTY_NAME="Ubuntu 22.04.5 LTS"
NAME="Ubuntu"
VERSION_ID="22.04"
VERSION="22.04.5 LTS (Jammy Jellyfish)"

$ uname -a
Linux di15 5.15.0-156-generic #166-Ubuntu SMP Sat Aug 9 00:02:46 UTC 2025 x86_64 x86_64 x86_64 GNU/Linux
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
**Base commit:** `497ed03ae77411ed2d030c5aaec9ec1155392549`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig cli

It might be the same type of issue https://github.com/kubernetes/kubernetes/issues/134503. Was it working in the previous k8s version? 

> /sig cli

I don't think this is sig cli, the issue is that the kubelet doesn't set the correct metadata

/assign

I created a similar PR for node-problem-detector https://github.com/kubernetes/node-problem-detector/pull/1154, not sure if there's anything to change in the `kubectl events` tool itself.

I am using version 1.34. After restarting kubelet, I can see events with `kubectl events`, but using the command `kubectl events --for Node/k8s-6` does not display anything.
```
[root@k8s-6:~]$ kubectl events
LAST SEEN   TYPE      REASON                    OBJECT             MESSAGE
2m39s       Normal    Starting                  Node/k8s-6   Starting kubelet.
2m39s       Warning   CgroupV1                  Node/k8s-6  cgroup v1 support is in maintenance mode, please migrate to cgroup v2
2m39s       Normal    NodeAllocatableEnforced   Node/k8s-6   Updated Node Allocatable limit across pods
2m39s       Normal    NodeHasSufficientMemory   Node/k8s-6   Node k8s-6 status is now: NodeHasSufficientMemory
2m39s       Normal    NodeHasNoDiskPressure     Node/k8s-6   Node k8s-6 status is now: NodeHasNoDiskPressure
2m39s       Normal    NodeHasSufficientPID      Node/k8s-6   Node k8s-6 status is now: NodeHasSufficientPID
[root@k8s-6:~]$ kubectl events --for Node/k8s-6
No events found in default namespace.
[root@k8s-6:~]$ 
```

I am using the k8s 1.28 version and the display is normal. The event details are as follows:
```
[root@k8s-86:~]$ kubectl get no
NAME           STATUS   ROLES    AGE    VERSION
k8s-86         Ready    master   211d   v1.28.3
[root@k8s-86:~]$ kubectl get event -owide
LAST SEEN   TYPE      REASON                    OBJECT        SUBOBJECT   SOURCE            MESSAGE                                              FIRST SEEN   COUNT   NAME
9s          Normal    Starting                  node/k8s-86               kubelet, k8s-86   Starting kubelet.                                    9s           1       k8s-86.186ed392e13d45e3
9s          Warning   InvalidDiskCapacity       node/k8s-86               kubelet, k8s-86   invalid capacity 0 on image filesystem               9s           1       k8s-86.186ed392e207b5f4
9s          Normal    NodeHasSufficientMemory   node/k8s-86               kubelet, k8s-86   Node k8s-86 status is now: NodeHasSufficientMemory   9s           1       k8s-86.186ed392e874f385
9s          Normal    NodeHasNoDiskPressure     node/k8s-86               kubelet, k8s-86   Node k8s-86 status is now: NodeHasNoDiskPressure     9s           1       k8s-86.186ed392e8751aea
9s          Normal    NodeHasSufficientPID      node/k8s-86               kubelet, k8s-86   Node k8s-86 status is now: NodeHasSufficientPID      9s           1       k8s-86.186ed392e8752e1d
9s          Normal    NodeAllocatableEnforced   node/k8s-86               kubelet, k8s-86   Updated Node Allocatable limit across pods           9s           1       k8s-86.186ed392efe4e610
[root@k8s-86:~]$ 
[root@k8s-86:~]$ kubectl events --for Node/k8s-86
LAST SEEN   TYPE      REASON                    OBJECT        MESSAGE
24s         Normal    Starting                  Node/k8s-86   Starting kubelet.
24s         Warning   InvalidDiskCapacity       Node/k8s-86   invalid capacity 0 on image filesystem
24s         Normal    NodeHasSufficientMemory   Node/k8s-86   Node k8s-86 status is now: NodeHasSufficientMemory
24s         Normal    NodeHasNoDiskPressure     Node/k8s-86   Node k8s-86 status is now: NodeHasNoDiskPressure
24s         Normal    NodeHasSufficientPID      Node/k8s-86   Node k8s-86 status is now: NodeHasSufficientPID
24s         Normal    NodeAllocatableEnforced   Node/k8s-86   Updated Node Allocatable limit across pods
[root@k8s-86:~]$ 
[root@k8s-86:~]$ 
[root@k8s-86:~]$ kubectl events
LAST SEEN   TYPE      REASON                    OBJECT        MESSAGE
35s         Normal    Starting                  Node/k8s-86   Starting kubelet.
35s         Warning   InvalidDiskCapacity       Node/k8s-86   invalid capacity 0 on image filesystem
35s         Normal    NodeHasSufficientMemory   Node/k8s-86   Node k8s-86 status is now: NodeHasSufficientMemory
35s         Normal    NodeHasNoDiskPressure     Node/k8s-86   Node k8s-86 status is now: NodeHasNoDiskPressure
35s         Normal    NodeHasSufficientPID      Node/k8s-86   Node k8s-86 status is now: NodeHasSufficientPID
35s         Normal    NodeAllocatableEnforced   Node/k8s-86   Updated Node Allocatable limit across pods
[root@k8s-86:~]$ 
[root@k8s-86:~]$ kubectl get event k8s-86.186ed392e13d45e3 -oyaml
apiVersion: v1
count: 1
eventTime: null
firstTimestamp: "2025-10-16T01:12:12Z"
involvedObject:
  kind: Node
  name: k8s-86
  uid: k8s-86
kind: Event
lastTimestamp: "2025-10-16T01:12:12Z"
message: Starting kubelet.
metadata:
  creationTimestamp: "2025-10-16T01:12:12Z"
  name: k8s-86.186ed392e13d45e3
  namespace: default
  resourceVersion: "4061764"
  uid: d7787c3f-d1f5-4621-9673-3eaf2f80fc24
reason: Starting
reportingComponent: kubelet
reportingInstance: k8s-86
source:
  component: kubelet
  host: k8s-86
type: Normal
[root@k8s-86:~]$ 
```
