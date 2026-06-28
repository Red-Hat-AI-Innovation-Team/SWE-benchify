Confusing use of TooManyRequests error for eviction
### What happened?

When the Kubernetes API server returns a 429 (throttled), the response may include misleading cause information.

We observed that a pod eviction API call received a response that included _**both**_ of the following fragments:

``` json
"responseStatus": {
  "metadata": {},
  "status": "Failure",
  "reason": "TooManyRequests",
  "code": 429
},
```

and

``` json
"responseObject": {
  "kind": "Status",
  "apiVersion": "v1",
  "metadata": {},
  "status": "Failure",
  "message": "Cannot evict pod as it would violate the pod's disruption budget.",
  "reason": "TooManyRequests",
  "details": {
    "causes": [
      {
        "reason": "DisruptionBudget",
        "message": "The disruption budget [elided] needs 11 healthy pods and has 12 currently"
      }
    ]
  },
  "code": 429
},
```
Note that the `message` given above is confusing, as there are more currently healthy pods than the required number.


### What did you expect to happen?

When a request is rejected due to throttling (429 HTTP response), either
* no other error information should be included; or
* the included error information should indicate throttling

### How can we reproduce it (as minimally and precisely as possible)?

Provoke a 429 HTTP response and inspect the response. 

### Anything else we need to know?

Issue #88535 seems to be similar - it also describes a 429 response where inclusion of a cause resulted in confusion.

### Kubernetes version

Version: 1.20.9


### Cloud provider

Azure Kubernetes Service	

### OS version

<details>

```console
# On Linux:
$ cat /etc/os-release
# paste output here
$ uname -a
# paste output here

# On Windows:
C:\> wmic os get Caption, Version, BuildNumber, OSArchitecture
# paste output here
```

</details>


### Install tools

<details>

</details>


### Container runtime (CRI) and and version (if applicable)

<details>

</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>

</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `6f093ef29234787b51fc80154c0fa9988a1d7853`

## Hints

/sig api-machinery

/remove-sig api-machinery
/sig apps
for PDB

@liggitt , are you sure?

As far as I've been able to work out, the 429 HTTP response is correct and the PDB error is a red herring. 

The PDB error we observed doesn't even make sense, given the number of healthy pods (12) was _more_ than the needed (11):

> The disruption budget [elided] needs 11 healthy pods and has 12 currently

(My experience is that I spent a bunch of time digging into possible causes of the PDB error before realizing that I'd been ignoring the HTTP response code - and once I started paying attention to that, everything started to make sense. Of course, you understand this area far better, I just don't want you to fall into the same trap that I did!)


any message coming back with PDB language in it belongs to sig-apps

The Kubernetes project currently lacks enough contributors to adequately respond to all issues and PRs.

This bot triages issues and PRs according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue or PR as fresh with `/remove-lifecycle stale`
- Mark this issue or PR as rotten with `/lifecycle rotten`
- Close this issue or PR with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-lifecycle stale

The Kubernetes project currently lacks enough contributors to adequately respond to all issues and PRs.

This bot triages issues and PRs according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue or PR as fresh with `/remove-lifecycle stale`
- Mark this issue or PR as rotten with `/lifecycle rotten`
- Close this issue or PR with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-lifecycle stale 

/remove-lifecycle stale

The Kubernetes project currently lacks enough contributors to adequately respond to all issues and PRs.

This bot triages issues and PRs according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue or PR as fresh with `/remove-lifecycle stale`
- Mark this issue or PR as rotten with `/lifecycle rotten`
- Close this issue or PR with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

The Kubernetes project currently lacks enough active contributors to adequately respond to all issues and PRs.

This bot triages issues and PRs according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue or PR as fresh with `/remove-lifecycle rotten`
- Close this issue or PR with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle rotten

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-lifecycle rotten

The Kubernetes project currently lacks enough contributors to adequately respond to all issues and PRs.

This bot triages issues and PRs according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue or PR as fresh with `/remove-lifecycle stale`
- Mark this issue or PR as rotten with `/lifecycle rotten`
- Close this issue or PR with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-lifecycle stale

The Kubernetes project currently lacks enough contributors to adequately respond to all issues.

This bot triages un-triaged issues according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue as fresh with `/remove-lifecycle stale`
- Close this issue with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-lifecycle stale

/triage accepted
/priority important-longterm

It looks like eviction has some creative uses of `TooManyRequests` errors. Why is this conflict error converted to TooManyRequests?

https://github.com/kubernetes/kubernetes/blob/786316f0b6bb9078cd564ebf5401bb2e9ac7f2a2/pkg/registry/core/pod/storage/eviction.go#L294-L305

Also this observed generation mismatch (stale cache?):

https://github.com/kubernetes/kubernetes/blob/786316f0b6bb9078cd564ebf5401bb2e9ac7f2a2/pkg/registry/core/pod/storage/eviction.go#L419-L422

Violating the disruption budget is more debatable, but I still don't think a 429 error is right:

https://github.com/kubernetes/kubernetes/blob/786316f0b6bb9078cd564ebf5401bb2e9ac7f2a2/pkg/registry/core/pod/storage/eviction.go#L429-L433



> It looks like eviction has some creative uses of `TooManyRequests` errors. Why is this conflict error converted to TooManyRequests?

that was added in https://github.com/kubernetes/kubernetes/pull/94381/files#r507982781 with some discussion there

I think the short answer is we wanted to drive an automatic retry (which the server returning TooManyRequests with a RetryAfter does), and returning a conflict when the user did not set a precondition on the request did not seem correct

This issue has not been updated in over 1 year, and should be re-triaged.

You can:
- Confirm that this issue is still relevant with `/triage accepted` (org members only)
- Close this issue with `/close`

For more details on the triage process, see https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-triage accepted

If we put aside the 429 for a moment and focus on the error's cause in question:
```
  "details": {
    "causes": [
      {
        "reason": "DisruptionBudget",
        "message": "The disruption budget [elided] needs 11 healthy pods and has 12 currently"
      }
    ]
  },
```
source:
https://github.com/kubernetes/kubernetes/blob/786316f0b6bb9078cd564ebf5401bb2e9ac7f2a2/pkg/registry/core/pod/storage/eviction.go#L429-L433
Isn't it weird that this state (`needs 11 healthy pods and has 12 currently`) is an error?
The code returns this error cause when `pdb.Status.DisruptionsAllowed == 0`. Is this value wrong in this case, should it have been 1? I couldn't find how this is calculated but I don't know the code so well.

`pdb.Status.DisruptionsAllowed = 0` is set as a fail safe when the DesiredHealthy / CurrentHealthy pods can't be calculated so those numbers are not trustworthy:

https://github.com/kubernetes/kubernetes/blob/bb838fde5bb9df4becb9fd267c84759be9f5400f/pkg/controller/disruption/disruption.go#L944-L962

If the `type=DisruptionAllowedCondition, status=False` condition is present, we should probably use the message from that condition rather than the pdb.Status.DesiredHealthy and pdb.Status.CurrentHealthy fields

The Kubernetes project currently lacks enough contributors to adequately respond to all issues.

This bot triages un-triaged issues according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue as fresh with `/remove-lifecycle stale`
- Close this issue with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/remove-lifecycle stale

The Kubernetes project currently lacks enough contributors to adequately respond to all issues.

This bot triages un-triaged issues according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Mark this issue as fresh with `/remove-lifecycle stale`
- Close this issue with `/close`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/lifecycle stale

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

/lifecycle stale

/remove-lifecycle stale

I also came across the same scenario wherein in kube-api-server-audit logs, we see 429 requests but then there is a response as well which says eviction not possible due to PDB. If its 429 & request is rejected, how come this message is appearing in audit logs ?
EKS version: 1.29

@theunrepentantgeek  Were you able to find out by any chance reason behind it ?

/triage accepted

I will work on this issue :)
/assign
