HPA - optimize calculatePodRequestsFromContainers func specific container lookups
The `calculatePodRequestsFromContainers` function currently iterates through all containers in a pod, even when a specific container name is provided. This is inefficient. When the container parameter is not an empty string, the function should locate the specified container and return its resource request without iterating through the entire list. We should exit the loop early once the matching container is found.

ref: [comment](https://github.com/kubernetes/kubernetes/pull/132430/files#r2217338178)

/triage accepted
/assign @laoj2 
/sig autoscaling

**Repository:** `kubernetes/kubernetes`
**Base commit:** `993d2862303275a49d387311fad6dff78b4384ed`

## Hints

/kind cleanup

Hi @omerap12, 

I'd like to work on this optimization. The early exit approach makes perfect sense - we can break the loop once we find the target container instead of iterating through all of them.

Quick question: should we also handle the case where the specified container doesn't exist, or just return the current behavior?

Happy to submit a PR if you'd like.


Thanks for following up on this @omerap12!!

@AadiDev005 Thanks!! I haven't started working on this, so feel to fix this

> Quick question: should we also handle the case where the specified container doesn't exist, or just return the current behavior?

That's a good point. We should probably return an error, similar to what we return when the request is missing? https://github.com/kubernetes/kubernetes/blob/dfda323ad9944c3fe49f7dbd6d04e4e7c58dac75/pkg/controller/podautoscaler/replica_calculator.go#L517

Otherwise, it looks like we'll fail with `no metrics returned matched known pods`: https://github.com/kubernetes/kubernetes/blob/6f7df1f1431b20e61cf7d01aa79751c44b8cc156/pkg/controller/podautoscaler/metrics/utilization.go#L45-L48

But I haven't checked if HPA won't fail already if the specified container doesn't exist way before reaching this part of the code.

/assign @AadiDev005

Cool. thanks folks!
