Use eachKey DV in DRA resources.
]#### What type of PR is this?

/kind feature

#### What this PR does / why we need it:

This PR uses `eachKey` to mirror map keys validations for DRA resource fields declaratively. 

This is part of the broader effort to adopt declarative validation, making the validation rules more explicit and the code easier to maintain.

#### Which issue(s) this PR is related to:

KEP: https://github.com/kubernetes/enhancements/issues/5073

#### Special notes for your reviewer:

The field path for map key validation has been changed from `fldPath.Key(truncateIfTooLong(string(key), truncateKeyLen))` to just `fldPath`. This is because declarative validation for `eachKey` uses the map field itself as the path, not each individual key. This change is necessary to make the declarative validation work correctly.

#### Does this PR introduce a user-facing change?
```release-note
NONE
```

#### Additional documentation e.g., KEPs (Kubernetes Enhancement Proposals), usage docs, etc.:
```docs
- [KEP]: https://github.com/kubernetes/enhancements/issues/5073
```

**Repository:** `kubernetes/kubernetes`
**Base commit:** `51579e9c36436fd2d35ffccc441de1dbebdceaca`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/assign @jpbetz @aaron-prindle 

This PR [may require API review](https://git.k8s.io/community/sig-architecture/api-review-process.md#what-apis-need-to-be-reviewed).

If so, when the changes are ready, [complete the pre-review checklist and request an API review](https://git.k8s.io/community/sig-architecture/api-review-process.md#mechanics).

Status of requested reviews is tracked in the [API Review project](https://github.com/orgs/kubernetes/projects/169).

> This is part of the broader effort to adopt declarative validation using CEL, making the validation rules more explicit and the code easier to maintain.
>
In PR description, it's not using CEL right?

/lgtm 



LGTM label has been added.  <details>Git tree hash: cc15a3e372f8ff2dee9a30b441697cdbb9e1b8c3</details>

/assign @thockin 

Thanks!

/lgtm
/approve

LGTM label has been added.  <details>Git tree hash: b3e2e6d4f99e15c57054936a3dcaf61093fac88a</details>

[APPROVALNOTIFIER] This PR is **APPROVED**

This pull-request has been approved by: *<a href="https://github.com/kubernetes/kubernetes/pull/134836#" title="Author self-approved">lalitc375</a>*, *<a href="https://github.com/kubernetes/kubernetes/pull/134836#issuecomment-3458887260" title="Approved">thockin</a>*

The full list of commands accepted by this bot can be found [here](https://go.k8s.io/bot-commands?repo=kubernetes%2Fkubernetes).

The pull request process is described [here](https://git.k8s.io/community/contributors/guide/owners.md#the-code-review-process)

<details >
Needs approval from an approver in each of these files:

- ~~[pkg/apis/OWNERS](https://github.com/kubernetes/kubernetes/blob/master/pkg/apis/OWNERS)~~ [thockin]
- ~~[pkg/registry/OWNERS](https://github.com/kubernetes/kubernetes/blob/master/pkg/registry/OWNERS)~~ [thockin]
- ~~[staging/src/k8s.io/api/OWNERS](https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/api/OWNERS)~~ [thockin]
- ~~[staging/src/k8s.io/code-generator/OWNERS](https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/code-generator/OWNERS)~~ [thockin]

Approvers can indicate their approval by writing `/approve` in a comment
Approvers can cancel approval by writing `/approve cancel` in a comment
</details>
<!-- META={"approvers":[]} -->
