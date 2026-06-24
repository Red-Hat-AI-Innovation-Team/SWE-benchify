NodeLogQuery stopped accepting POST
This feature is currently off-by-default, but it's slated for GA in 1.36 https://github.com/kubernetes/enhancements/issues/2258

Recently we discovered that while GET works at head POST stopped working after the project upgraded to go 1.26
See previously: https://github.com/kubernetes/kubernetes/issues/137459

The handler for this API should probably be evaluated before it goes GA.

/kind bug
/sig node

At the very least, it was either unintentionally working before. The handler should probably restrict verbs explicitly.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `c6886b7d697a41f0b779abfaf5aeba66b4c577d1`

## Hints

It would also be good to understand why this stopped working, in case it impacts any other APIs.

Taking a look, I [commented](https://github.com/kubernetes/kubernetes/issues/137459#issuecomment-4013357373) on the parent issue.

/assign @jrvaldes 

> Is it confirmed that the "stopped accepting POST" is exclusive to the [query](https://github.com/kubernetes/kubernetes/pull/137462/files#diff-9b2eaad633b1ac2ad543e05ddeb831f207bfb4d034456070bc7d32ea45b7ed05R624) feature, or is this a behavior inherited from the [logs](https://github.com/kubernetes/kubernetes/pull/137462/files#diff-9b2eaad633b1ac2ad543e05ddeb831f207bfb4d034456070bc7d32ea45b7ed05L623) endpoint

Unclear, the primary concern at the time was unbreaking the data race signal, but I'm concerned that we don't know why this happened, it's entirely possible it's not specific to either of these endpoints, but I think it's less likely with GA endpoints.
