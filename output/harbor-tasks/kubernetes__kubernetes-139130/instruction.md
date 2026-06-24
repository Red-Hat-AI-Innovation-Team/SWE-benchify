Return full list of pods in podGroupSchedulingAlgorithm
Right now podGroupSchedulingAlgorithmis returning list of pods for wich it get schedulingResult. 
If scheduling of pdGroup will end earlier, for example due to not being able to fulfil minCount, some pods will not be present in result list.
It might be problematic for preemption algorithm.

More detaile in https://github.com/kubernetes/kubernetes/pull/138967#discussion_r3224151178

/sig scheduling
/assign

**Repository:** `kubernetes/kubernetes`
**Base commit:** `465cb5fc8d60b6c7aaffc37b61affc0f01313daa`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>
