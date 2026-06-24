Distinguish PDB error separately in eviction API
### What would you like to be added?

Currently in eviction API, when violating PDB, we'll have two common errors, see https://github.com/kubernetes/kubernetes/blob/eb6840928df59bf8203b1eda839ccd3da68fb37d/pkg/registry/core/pod/storage/eviction.go#L423-L432

We can't easily distinguish them with other `forbidden` or `tooManyRequests` errors, we do have different messages but that's not an appropriate criteria for judgement.

When detecting `update conflicts`, we have a conflict reason for it, maybe we can do the same thing here like **A Forbidden status code with different Reasons**, have no idea whether this is acceptable. but at least it's feasible because we maintain the status reasons ourself in kubernetes.

/kind api-machineary

### Why is this needed?

It would be great if we can tell them when calling eviction API, like in https://github.com/kubernetes/enhancements/pull/4329#discussion_r1637925556, this can be an important metric for users to know the reason why Pods can't be evicted, because of PDB constraints or others.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `d8d43a90343eafa7598da658febc8d312fc2a880`

## Hints

@kerthcet: The label(s) `kind/api-machineary` cannot be applied, because the repository doesn't have them.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/125500):

>### What would you like to be added?
>
>Currently in eviction API, when violating PDB, we'll have two common errors, see https://github.com/kubernetes/kubernetes/blob/eb6840928df59bf8203b1eda839ccd3da68fb37d/pkg/registry/core/pod/storage/eviction.go#L423-L432
>
>We can't easily distinguish them with other `forbidden` or `tooManyRequests` errors, we do have different messages but that's not an appropriate criteria for judgement.
>
>When detecting `update conflicts`, we have a conflict reason for it, maybe we can do the same thing here like **A Forbidden status code with different Reasons**, have no idea whether this is acceptable. but at least it's feasible because we maintain the status reasons ourself in kubernetes.
>
>/kind api-machineary
>
>### Why is this needed?
>
>It would be great if we can tell them when calling eviction API, like in https://github.com/kubernetes/enhancements/pull/4329#discussion_r1637925556, this can be an important metric for users to know the reason why Pods can't be evicted, because of PDB constraints or others. 


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig api-machinery

similar issue: https://github.com/kubernetes/kubernetes/issues/106286

/triage accepted
/help

@seans3: 
	This request has been marked as needing help from a contributor.

### Guidelines
Please ensure that the issue body includes answers to the following questions:
- Why are we solving this issue?
- To address this issue, are there any code changes? If there are code changes, what needs to be done in the code and what places can the assignee treat as reference points?
- Does this issue have zero to low barrier of entry?
- How can the assignee reach out to you for help?


For more details on the requirements of such an issue, please see [here](https://git.k8s.io/community/contributors/guide/help-wanted.md) and ensure that they are met.

If this request no longer meets these requirements, the label can be removed
by commenting with the `/remove-help` command.


<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/125500):

>/triage accepted
>/help


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

Can someone determine if these two issues are duplicates?

Hello and greetings,
I'm a newbie and would like to address the issue as I recently finished learning Go and basic Kubernetes. If possible, could you please provide more insights into the error?
Thanks.

/assign
/honk

@varshith257: 
![goose image](https://images.unsplash.com/photo-1613150851117-d880cc5bafff?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5NDI1N3wwfDF8cmFuZG9tfHx8fHx8fHx8MTcxODgyMjI2MXw&ixlib=rb-4.0.3&q=80&w=400)

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/125500#issuecomment-2179297882):

>/assign
>/honk


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

Hey team, Is this issue being actively worked upon ? I would be happy to contribute if this still needs a contributor.

> Hey team, Is this issue being actively worked upon ? I would be happy to contribute if this still needs a contributor.

cc @varshith257 @kerthcet 

I'm working on this. Will open a PR shortly.

@shady0503: GitHub didn't allow me to assign the following users: yourself.

Note that only [kubernetes members](https://github.com/orgs/kubernetes/people) with read permissions, repo collaborators and people who have commented on this issue/PR can be assigned. Additionally, issues/PRs can only have 10 assignees at the same time.
For more information please see [the contributor guide](https://git.k8s.io/community/contributors/guide/first-contribution.md#issue-assignment-in-github)

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/125500#issuecomment-4117518508):

>/assign @yourself


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>
