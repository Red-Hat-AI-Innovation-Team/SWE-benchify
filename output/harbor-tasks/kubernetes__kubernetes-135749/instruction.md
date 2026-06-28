kubelet_http_requests_duration_seconds metric records incorrect (near-zero) latency values
### What happened?

The `kubelet_http_requests_duration_seconds` histogram metric always records near-zero values (~2 microseconds) regardless of actual request processing time.

Below is a screenshot from a downstream CI run showing the average latency of kubetet's /metrics/cadvisor endpoint:

<img width="1858" height="842" alt="Image" src="https://github.com/user-attachments/assets/c9286e88-63e6-4a55-b1e5-fe5f0d4329ab" />

### What did you expect to happen?

The metric should record the actual time taken to handle each HTTP request, from when it's received until the response is sent.

### How can we reproduce it (as minimally and precisely as possible)?

1. Make an HTTP request to the kubelet that takes a measurable amount of time (e.g., `/pods/` endpoint)
2. Query the `kubelet_http_requests_duration_seconds` metric
3. Observe that the recorded duration is always ~2 microseconds instead of the actual processing time

### Anything else we need to know?

**Root cause:**

In `pkg/kubelet/server/server.go`, the defer statement evaluates `SinceInSeconds(startTime)` immediately when the defer is declared, not when it executes:

```go
defer servermetrics.HTTPRequestsDuration.WithLabelValues(...).Observe(servermetrics.SinceInSeconds(startTime))
```

In Go, arguments to deferred function calls are evaluated immediately at the defer statement. This means `SinceInSeconds(startTime)` computes the duration at the start of the request (~5µs after `startTime` was set), rather than at the end when the defer actually runs.

This affects observability and SLO tracking for kubelet HTTP endpoints since duration data is meaningless.

### Kubernetes version

1.33

**Repository:** `kubernetes/kubernetes`
**Base commit:** `44dc4cb68cfe322c0d1bba16f3ca984f694d67fe`

## Hints

/kind bug
/sig node

/assign

/area kubelet

/triage accepted
/assign @novahe 
/priority backlog

@SergeyKanzhelev: GitHub didn't allow me to assign the following users: novahe.

Note that only [kubernetes members](https://github.com/orgs/kubernetes/people) with read permissions, repo collaborators and people who have commented on this issue/PR can be assigned. Additionally, issues/PRs can only have 10 assignees at the same time.
For more information please see [the contributor guide](https://git.k8s.io/community/contributors/guide/first-contribution.md#issue-assignment-in-github)

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/135662#issuecomment-3780570798):

>/triage accepted
>/assign @novahe 
>/priority backlog


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>
