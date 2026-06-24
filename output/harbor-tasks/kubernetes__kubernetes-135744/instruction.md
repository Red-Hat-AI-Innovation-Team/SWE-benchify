`kubectl describe service` does not display `appProtocol` field
## Problem

The `appProtocol` field (GA since v1.20) is not displayed in `kubectl describe service` output, even when set. Users must use `kubectl get svc -o yaml` to verify this field.

This can be problematic when debugging Service Mesh or Gateway API configurations where `appProtocol` affects traffic routing. Given that `appProtocol` has been GA for several years and is actively used in Service Mesh environments, displaying it in `kubectl describe` output would be beneficial for users.

## Proposed Solution

Display `appProtocol` in the port section of `kubectl describe service` output:
```
Port:              http  80/TCP
TargetPort:        8080/TCP
AppProtocol:       http          # <-- Add this
NodePort:          http  30080/TCP
```

https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/kubectl/pkg/describe/describe.go#L3015

## Benefits

- Consistency with other port fields (`name`, `protocol`, `port`, `targetPort`, `nodePort`)
- Easier debugging for Service Mesh and Gateway API users

**Repository:** `kubernetes/kubernetes`
**Base commit:** `8de4a1125283df991b529e7e99ec9034be57b510`

## Hints

/sig cli

/assign 

I also think this would be beneficial, as users mostly rely on the `describe` output during debugging. Fields that can change cluster behavior (for example, when a service mesh is used) should be visible in the `describe` output. 

I can create a PR for it, if it is okay.
