DRA API helper: add automated fuzz testing of conversion roundtripping
### What would you like to be added?

k8s.io/dynamic-resource-allocation/api/v1beta1 and v1beta2 contain automatically generated conversion code. That code is trusted to be correct because it is generated. However, it would be better to have that verified through fuzz testing similar to staging/src/k8s.io/api/roundtrip_test.go.

/wg device-management
/help

Not a good first issue, needs some exploration on how to do it.

### Why is this needed?

Avoiding regressions.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `186ec02732f777a2c845a250d17f13b6c8f05e0e`

## Hints

@pohly: 
	This request has been marked as needing help from a contributor.

### Guidelines
Please ensure that the issue body includes answers to the following questions:
- Why are we solving this issue?
- To address this issue, are there any code changes? If there are code changes, what needs to be done in the code and what places can the assignee treat as reference points?
- How can the assignee reach out to you for help?


For more details on the requirements of such an issue, please see [here](https://www.kubernetes.dev/docs/guide/help-wanted/) and ensure that they are met.

If this request no longer meets these requirements, the label can be removed
by commenting with the `/remove-help` command.


<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/134356):

>### What would you like to be added?
>
>k8s.io/dynamic-resource-allocation/api/v1beta1 and v1beta2 contain automatically generated conversion code. That code is trusted to be correct because it is generated. However, it would be better to have that verified through fuzz testing similar to staging/src/k8s.io/api/roundtrip_test.go.
>
>/wg device-management
>/help
>
>Not a good first issue, needs some exploration on how to do it.
>
>### Why is this needed?
>
>Avoiding regressions.


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

maybe @tkashem youd like to take a look?

I'd like to work on this.

I noticed the previous PR #135707 was closed because the test wasn't actually exercising any types — the `kinds` map was being used as a skip list rather than a target list.

My approach:
- Use `scheme.KnownTypes()` to iterate over all non-list types registered in each version
- For each type, fuzz it using the standard Kubernetes fuzzer (`genericfuzzer.Funcs`), convert to the target version via `scheme.Convert()`, convert back, and compare using `apiequality.Semantic.DeepEqual`
- Test both v1beta1 ↔ v1 and v1beta2 ↔ v1

While writing the test, I also found that the v1beta1 manual conversion code was missing several fields:
- `Device`: `BindsToNode`, `BindingConditions`, `BindingFailureConditions`, `AllowMultipleAllocations` (not copied when unwrapping/wrapping `BasicDevice`)
- `DeviceRequest`: `Capacity` (not copied to/from `ExactDeviceRequest`)

I've fixed these in the same PR. Happy to split into separate commits if preferred.
