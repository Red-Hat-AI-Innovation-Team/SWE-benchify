Leadership election should retry lock release on conflict
We've found that there is a corner case that causes leadership election to fail to release the election lock if there is a resource conflict. When this happens, the current leader retains control of the lock until it expires.

Here's some logs showing this:

```
2025-05-12T21:51:36.2025279Z time=2025-05-12T21:51:36.202Z level=ERROR msg="Failed to update lock optimistically: Put \"https://172.20.0.1:443/apis/coordination.k8s.io/v1/namespaces/my-namespace/leases/my-lock-name\": context canceled, falling back to slow path"
2025-05-12T21:51:36.2027230Z time=2025-05-12T21:51:36.202Z level=ERROR msg="error retrieving resource lock my-namespace/my-lock-name: client rate limiter Wait returned an error: context canceled"
2025-05-12T21:51:36.2028372Z time=2025-05-12T21:51:36.202Z level=INFO msg="failed to renew lease my-namespace/my-lock-name: context canceled"
2025-05-12T21:51:36.2098866Z time=2025-05-12T21:51:36.209Z level=ERROR msg="Failed to release lock: Operation cannot be fulfilled on leases.coordination.k8s.io \"my-lock-name\": the object has been modified; please apply your changes to the latest version and try again"
```

It appears there is a race condition between renewal and release when the renewal context is cancelled, but I haven't had a chance to dig into this. Regardless of the cause, the release on cancel logic should retry in the event of a resource conflict. This essentially amounts to wrapping [this line](https://github.com/kubernetes/client-go/blob/025e06660a232d5f9d9a757bad0eed19f58a03cc/tools/leaderelection/leaderelection.go#L321) with a `retry.RetryOnConflict`:

```go
func (le *LeaderElector) release() bool {

	...

	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		if err := le.config.Lock.Update(timeoutCtx, leaderElectionRecord); err != nil {
			klog.Errorf("Failed to release lock: %v", err)
			return err
		}

		return nil
	})

	if err != nil {
		klog.Errorf("Exhausted retries while retrying lock release: %v", err)
		return false
	}

	return true
}
```

If this ~10 line change meets maintainer approval, then I'd be glad to file a PR for it.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `84cacae7046df93c1f6f8ea97c912d948e1ad06a`

## Hints

/transfer kubernetes

moving to the canonical source for this library
/sig api-machinery
/cc @jpbetz 
for visibility and routing

Thank you for the report. So renew and release are synchronous in that and renew will always be executed before release and will block until the renew is either successful or finished. (https://github.com/kubernetes/client-go/blob/025e06660a232d5f9d9a757bad0eed19f58a03cc/tools/leaderelection/leaderelection.go#L283)

Retrying via `le.config.Lock.Update` won't solve the fundamental issue the update will be retried with the same data (resourceVersion) that was already outdated. My suspicion is that we need to call a [Get()](https://github.com/kubernetes/client-go/blob/025e06660a232d5f9d9a757bad0eed19f58a03cc/tools/leaderelection/resourcelock/leaselock.go#L41) in the release() function in order to ensure that the resource version is up to date before we release. 

/cc @Jefftree 


/triage accepted

I will take on this issue.
/assign
