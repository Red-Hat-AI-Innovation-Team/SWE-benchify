RestartRules and other feature-gated fields are not allowed for static pods
Static pods are validated differently from API pods because the ValidationOptions are not initialized appropriately:

https://github.com/kubernetes/kubernetes/blob/d2e1e3b6bc9fd5330bb9e2671c026634b18106bb/pkg/kubelet/config/common.go#L141-L143

This results in static pod cannot have restart rules, as well as all other option-based values.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `9a5193796bff2910dd00efe2539b318936f49ec3`

## Hints

/sig node
/triage accepted
/assign yuanwang04
