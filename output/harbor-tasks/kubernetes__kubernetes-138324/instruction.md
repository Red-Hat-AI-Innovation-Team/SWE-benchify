Race in scheduler can cause infinite growth of inFlightEvents
### What happened?

During the scheduling cycle if pod gets recreated with the same name during filtering there is a potential race condition causing the pod to stay in inFlightPods/inFlightEvents forever. 

Exact steps:

## Step 1: The Initial Lock-in
- Pop: The scheduler pops Pod-X (UID: AAAA) from the top of the scheduling queue.
- Record: The queue pushes Pod-X to the tail of the mixed doubly-linked `inFlightEvents` list to track when it started.
- Map: The queue stores the exact memory pointer to that list node inside `inFlightPods[AAAA]`.

## Step 2: The Synchronous Failure
- Execute: The scheduler begins running synchronous Filter plugins (e.g. checking NodeSelector, Taints, or custom filters).
- Fail: One of the filter plugins returns Unschedulable.
- Abort: Because scheduling cannot proceed, the scheduler aborts the cycle immediately and jumps straight to the failure handler. It skips `sched.SchedulingQueue.Done(assumedPod.UID)` done before bindingCycle.


## Step 3: The Recreation Overwrite (The Race Condition)
- Delete & Recreate: Just milliseconds before the failure handler runs, an external controller deletes Pod-X and immediately recreates a brand new instance with the exact same name/namespace, generating a new UID (BBBB).
- Fetch: The failure handler queries the local Informer cache for the latest state of the pod using its string name (Pod-X).
- Retrieve: The cache naturally returns the newly created instance with UID BBBB.
- Overwrite: The internal reference in the scheduler is updated to hold the new pod reference (BBBB).


## Step 4: Missing the Target
- Queue Push: The failure handler attempts to put the pod back into the queue using `AddUnschedulableIfNotPresent(BBBB)`.
- Deferred Done: The very first line of `AddUnschedulableIfNotPresent` function unconditionally executes:
``` go
       // In any case, this Pod will be moved back to the queue and we should call Done.
	defer p.Done(pInfo.Pod.UID)
```
- The Miss: `Done(BBBB)` looks inside the `inFlightPods` tracking map, sees that UID BBBB does not exist, and does absolutely nothing.
- The Ghost: The original UID (AAAA) is entirely forgotten by the system and remains permanently trapped inside the `inFlightPods` map and the doubly-linked list!

# Step 5: The Catastrophic Dam
- Drift: Over the next few seconds, as other unrelated pods complete their cycles normally, they get removed from the front of the list. The trapped ghost pod (AAAA) eventually shifts all the way to the Front() position of the list.
- The Blockade: Because `Done(AAAA)` is never called, this node can never be removed from Front().
- Paralysis: Every time the cleanup routine attempts to run, it looks at the very first element of the list, sees the ghost pod (AAAA), and completely halts all pruning to protect it.
- The Explosion: Meanwhile, standard background updates (Node usage, endpoint slices, system leases) continuously append thousands of new *clusterEvent nodes to the tail of the linked list. Because the front node is anchored forever, none of those incoming events can ever be deleted—causing your InFlightEvents metric to grow infinitely 

### What did you expect to happen?

The Done method of scheduling queue should be called on the old UID. 

### How can we reproduce it (as minimally and precisely as possible)?

Integration test `TestInFlightPodLeak` added in https://github.com/kubernetes/kubernetes/compare/master...Argh4k:kubernetes:potential-memory-leak reproduces that locally. 

### Anything else we need to know?

_No response_

### Kubernetes version

Observed on a cluster running v1.34.1, but still reproducible with the HEAD.

### Cloud provider

Observed on a cluster running on GKE but reproducible on a HEAD.


### OS version

N/A

### Install tools

N/A

### Container runtime (CRI) and version (if applicable)

N/A

### Related plugins (CNI, CSI, ...) and versions (if applicable)

N/A

**Repository:** `kubernetes/kubernetes`
**Base commit:** `cec8f06d2ce283d1563d37849619887aa2b11c9f`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig scheduling

Thanks — tagging /sig scheduling makes sense.
Let me know if more info is needed from my side

On Fri, Apr 10, 2026, 8:33 AM Maciej Wyrzuc ***@***.***>
wrote:

> *Argh4k* left a comment (kubernetes/kubernetes#138316)
> <https://github.com/kubernetes/kubernetes/issues/138316#issuecomment-4224093758>
>
> /sig scheduling
>
> —
> Reply to this email directly, view it on GitHub
> <https://github.com/kubernetes/kubernetes/issues/138316#issuecomment-4224093758>,
> or unsubscribe
> <https://github.com/notifications/unsubscribe-auth/B7X2MB3LF2W2IR2ZPRTRSGL4VDZ2FAVCNFSM6AAAAACXT64V36VHI2DSMVQWIX3LMV43OSLTON2WKQ3PNVWWK3TUHM2DEMRUGA4TGNZVHA>
> .
> You are receiving this because you are subscribed to this thread.Message
> ID: ***@***.***>
>
