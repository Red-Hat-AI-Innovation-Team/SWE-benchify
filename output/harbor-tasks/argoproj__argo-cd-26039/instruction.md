repo-server prints Invalid log messages on liveness check failures
<!-- If you are trying to resolve an environment-specific issue or have a one-off question about the edge case that does not require a feature then please consider asking a question in argocd slack [channel](https://argoproj.github.io/community/join-slack). -->

Checklist:

- [ ] I've searched in the docs and FAQ for my answer: https://bit.ly/argocd-faq.
- [X] I've included steps to reproduce the bug.
- [X] I've pasted the output of `argocd version`.

**Describe the bug**

When repo-server liveness check (`/healthz?full=true`) fails, it prints an invalid and confusing error log  message like:
```
time="2026-01-11T22:34:04Z" level=error msg="&{0xc000884bd0 0xc001310640 {} 0x4fba00 true false true {{} {0 0}} {{} 0} 0xc0001033c0 {0xc0013163c0 map[] false false} map[] false 0 -1 503 false false false [] {{} 0} [0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0] [0 0 0 0 0 0 0 0 0 0] [0 0 0] {{} {0 0}} <nil> true} rpc error: code = Canceled desc = context canceled"
```

Originally reported by @maximemoreillon in #25931 . This issue is opened to fix this specific problem with logging, not the original issue.

**To Reproduce**

Make the liveness check fail to respond in time.

One way to do that is to configure in the deployment:
* liveness check timeout to 1 second (the min. value possible)
* give to the repo-server pod an inadequately small cpu limit:

```
        livenessProbe:
          timeoutSeconds: 1
...
        resources:
          limits:
            cpu: 1m
```

The repo server will start and it will fail to respond to the liveness
probe under the specified 1 second timeout, then kubernetes will
close the HTTP connection to the pod, which will cause to print
the incorrect error message.
 
**Expected behavior**

A correct and useful message should be printed

**Screenshots**

**Version**

```shell
argocd: v3.2.3+2b6251d
  BuildDate: 2025-12-24T12:35:36Z
  GitCommit: 2b6251dfedb54de40596272a73ed1fb19d740219
  GitTreeState: clean
  GoVersion: go1.25.0
  Compiler: gc
  Platform: windows/amd64
```

**Repository:** `argoproj/argo-cd`
**Base commit:** `8b1415a6b7f27f41b3b6a1cf9fe20f75b3cfd022`
