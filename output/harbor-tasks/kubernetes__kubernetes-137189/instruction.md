GetLogs doesn't have support for Reactors in fake client
### What would you like to be added?

GetLogs should be supported just like any other `entity` and `verb` in fakeClient, so that we can mock the GetLogs for unit test.
https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/client-go/kubernetes/typed/core/v1/fake/fake_pod_expansion.go#L66

### Why is this needed?

Allows for unit testing of GetLogs function

**Repository:** `kubernetes/kubernetes`
**Base commit:** `7d70fe491d50ebbc14a0495ee09fa0e922a2ff82`

## Hints

/sig api-machinery


/help wanted
If there is a PR raised, we would be happy to review. However, we currently don't have resource for this. :)
/triage accepted

@mjnovice I am interested in working on this. Can you provide a little more context on this? Specifically what do you mean by Reactors? (still very new to this codebase)

This issue has not been updated in over 1 year, and should be re-triaged.

You can:
- Confirm that this issue is still relevant with `/triage accepted` (org members only)
- Close this issue with `/close`

For more details on the triage process, see https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-triage accepted

/help
/triage accepted

@BenTheElder: 
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

In response to [this](https://github.com/kubernetes/kubernetes/issues/117144):

>/help
>/triage accepted


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

@BenTheElder would like to work on this, can you please give more context

Hi, FWIW we mark issues `/good-first-issue` when they're considered good for new contributors and we have a much higher bar in terms of having an agreed direction and clear guidance for contributing https://github.com/kubernetes/community/blob/master/contributors/guide/help-wanted.md#good-first-issue

This issue does not meet that bar and will first require some discussion with OWNERS of the code to figure out what an acceptable approach might be. I can't say on my own.

You might want to consider one of these instead https://github.com/kubernetes/kubernetes/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22

EDIT: "help wanted" without "good first issue" indicates that we don't have enough resources on hand to implement this at the moment but we acknowledge the issue, and an experienced contributor might take it up, or an inexperienced contributor acknowledging the gaps and working through them.

For this one, @cici37 probably has more context about what might be an acceptable solution.
