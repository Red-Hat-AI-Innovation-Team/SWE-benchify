Garbage Collector: handle NotFound errors when objects are deleted externally
### Background

In our Kubernetes cluster, we run many offline jobs. In some cases, these jobs no longer need to continue running, so we want the pods to be deleted as soon as possible to free up resources.

However, the Kubernetes Garbage Collector (GC) controller has QPS and worker limits, which makes it unable to delete all pods of the deleted jobs quickly. In particular, `processGraphChanges` is single-threaded, so increasing the worker count or QPS does not effectively improve the deletion throughput.

As a result, in our service, we delete the pods directly right after deleting the job.

However, we found that the GC controller then logs a large number of error messages, because it later attempts to delete pods that no longer exist. For example:
```
error syncing item &garbagecollector.node{identity:garbagecollector.objectReference{OwnerReference:v1.OwnerReference{APIVersion:"v1", Kind:"Pod", Name:"tvx26012630os8ir2hfmgp2rbr2nssnf-t-0", UID:"87ec3922-07be-438b-9d61-ab3058fa1f19", Controller:(*bool)(nil), BlockOwnerDeletion:(*bool)(nil)}, Namespace:"video-tiga"}, ...}: pods "tvx26012630os8ir2hfmgp2rbr2nssnf-t-0" not found
```

### Proposed Solution
In the source code, the function `attemptToDeleteItem` first retrieves the node from the graph. However, the object may have already been deleted by the user, which results in a NotFound error when the GC controller later tries to delete it again.

I think it is necessary to explicitly handle this case. If `errors.IsNotFound(err)` is returned from deleteObject, we could treat it the same way as before: 
1. enqueue a virtual delete event
2. return enqueuedVirtualDeleteEventErr.

Do you think this approach is acceptable? If so, I would be happy to submit a fix.
```go
func (gc *GarbageCollector) attemptToDeleteItem(ctx context.Context, item *node) error {
	// TODO: It's only necessary to talk to the API server if this is a
	// "virtual" node. The local graph could lag behind the real status, but in
	// practice, the difference is small.
	latest, err := gc.getObject(item.identity)
	switch {
	case errors.IsNotFound(err):
		// the GraphBuilder can add "virtual" node for an owner that doesn't
		// exist yet, so we need to enqueue a virtual Delete event to remove
		// the virtual node from GraphBuilder.uidToNode.
		logger.V(5).Info("item not found, generating a virtual delete event",
			"item", item.identity,
		)
		gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)
		return enqueuedVirtualDeleteEventErr
	case err != nil:
		return err
	}

	// some code is omitted for brevity
	switch {
	case len(solid) != 0:
		// some code is omitted for brevity
		return err
	case len(waitingForDependentsDeletion) != 0 && item.dependentsLength() != 0:
		// some code is omitted for brevity
		if err := gc.deleteObject(item.identity, &policy); errors.IsNotFound(err) {
			// enqueue a virtual delete event and return enqueuedVirtualDeleteEventErr
			gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)
			return enqueuedVirtualDeleteEventErr
		} else {
			return err
		}
	default:
		// some code is omitted for brevity
		if err := gc.deleteObject(item.identity, &policy); errors.IsNotFound(err) {
			// enqueue a virtual delete event and return enqueuedVirtualDeleteEventErr
			gc.dependencyGraphBuilder.enqueueVirtualDeleteEvent(item.identity)
			return enqueuedVirtualDeleteEventErr
		} else {
			return err
		}
	}
}
```

**Repository:** `kubernetes/kubernetes`
**Base commit:** `67579b0285f34cab833378c763be2e97d14f76c1`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig API-Machinery

> I think it is necessary to explicitly handle this case. If `errors.IsNotFound(err)` is returned from deleteObject, we could treat it the same way as before:
> 
> 1. enqueue a virtual delete event
> 2. return enqueuedVirtualDeleteEventErr.

if the pod was actually deleted in the meantime, won't that delete event be observed and handled normally? I'm trying to understand if this is a temporary race that resolves itself naturally

> if the pod was actually deleted in the meantime, won't that delete event be observed and handled normally? I'm trying to understand if this is a temporary race that resolves itself naturally

You are right that the delete event is eventually observed and the state resolves itself naturally. However, during that brief race window, the GC logs a significant number of 'not found' errors.

In large-scale clusters with many short-lived offline jobs, this race condition occurs frequently enough to cause substantial log noise. I propose we explicitly check for errors.IsNotFound(err) after the delete attempt. If matched, we can handle it gracefully (similar to the logic at the start of attemptToDeleteItem) instead of logging it as an error.
