Cannot update HPA objects using object metrics with AverageValue
**What happened**:

When attempting to label a HorizontalPodAutoscaler (autoscaling/v2beta2) object that has an object metric using `AverageValue`,  received the following error:

```The HorizontalPodAutoscaler "<hpa-name>" is invalid: spec.metrics[0].object.target.value: Invalid value: resource.Quantity{i:resource.int64Amount{value:0, scale:0}, d:resource.infDecAmount{Dec:(*inf.Dec)(nil)}, s:"0", Format:"DecimalSI"}: must be positive```

**What you expected to happen**:

The `label` command should properly label the HPA object with no errors, since the HPA was able to build and run without errors.

**How to reproduce it (as minimally and precisely as possible)**:

1. Create a hpa.v2beta2.autoscaling object that includes the following metric:
```
  - object:
      describedObject:
        kind: Service
        name: svc-name
      metric:
        name: metric-name:sum 
      target:
        averageValue: 4650
        type: AverageValue
    type: Object
```
Make sure that you're using `AverageValue` and don't have a `Value` set.

2. Run the following command:
```
kubectl label hpa hpa_name -n namespace_name testlabel=test
```

**Anything else we need to know?**:

We were able to build and apply the HPA object without encountering any errors, and it appears to be scaling properly. This error only happens when calling `kubectl label` on the existing HPA object.

**Environment**:
- Kubernetes version (use `kubectl version`): tried in both 1.15.3 and 1.16.4
- Cloud provider or hardware configuration: AWS
- OS (e.g: `cat /etc/os-release`): darwin/amd64
- Kernel (e.g. `uname -a`):  Darwin Kernel Version 17.7.0: Fri Jul  6 19:54:51 PDT 2018; root:xnu-4570.71.3~2/RELEASE_X86_64 x86_64

**Repository:** `kubernetes/kubernetes`
**Base commit:** `0eb3ae1640e0fc9db151e5063815187afeb9b5af`

## Hints

/sig autoscaling

An update: this doesn't only affect the `label` command. Any attempt to patch the affected HPA object (i.e. changing `minReplicas`) will return the same error.

k8s 1.17.2 also meet this error, is this a bug?

Issues go stale after 90d of inactivity.
Mark the issue as fresh with `/remove-lifecycle stale`.
Stale issues rot after an additional 30d of inactivity and eventually close.

If this issue is safe to close now please do so with `/close`.

Send feedback to sig-testing, kubernetes/test-infra and/or [fejta](https://github.com/fejta).
/lifecycle stale

Encountering the same error, are there any updates? 

Stale issues rot after 30d of inactivity.
Mark the issue as fresh with `/remove-lifecycle rotten`.
Rotten issues close after an additional 30d of inactivity.

If this issue is safe to close now please do so with `/close`.

Send feedback to sig-testing, kubernetes/test-infra and/or [fejta](https://github.com/fejta).
/lifecycle rotten

Rotten issues close after 30d of inactivity.
Reopen the issue with `/reopen`.
Mark the issue as fresh with `/remove-lifecycle rotten`.

Send feedback to sig-testing, kubernetes/test-infra and/or [fejta](https://github.com/fejta).
/close

@fejta-bot: Closing this issue.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-692306848):

>Rotten issues close after 30d of inactivity.
>Reopen the issue with `/reopen`.
>Mark the issue as fresh with `/remove-lifecycle rotten`.
>
>Send feedback to sig-testing, kubernetes/test-infra and/or [fejta](https://github.com/fejta).
>/close


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

/reopen

@garimakemwal: You can't reopen an issue/PR unless you authored it or you are a collaborator.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-692917571):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

Encountering the same issue, it breaks our CI pipeline. Can we reopen this?

We have this issue as well. Would be cool to at least reopen it.

Have the same issue :(

@egoroof: You can't reopen an issue/PR unless you authored it or you are a collaborator.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-809577089):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

Hitting this issue as well. There is a  workaround tho

```bash
kubectl edit hpa.v2beta2.autoscaling <your-hpa>
```

Then spot every `spec.metrics.*.object` that uses `AverageValue`. Remove the `.value` ( that in my case is always `"0"`).

After that, you can freely edit w/e you want from the rest of the document. The bad news, the `.value: "0"` returns after saving, so you need to delete it every time you want to edit again.

Btw hitting this on both K8s `v1.17.9` and `v1.18.18`

same problem here, and the workaround outlined above doesn't work either.

My hypothesis is that when the control plane attempts to persist the object in k8s and convert the v2beta2 object to v1, it does so by storing the new interface in annotation. While doing so, it considers "value" as a required attribute and initialized it to 0. This later becomes an issue when we get back the yaml through the v2beta2 endpoint, which transforms the object back into a v2 object, now with both the "value" and "AverageValue" key.

This is still appearing in 1.21 as well. What is the best way to get this re-opened?

/reopen

@szuecs: Reopened this issue.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-954550418):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

We hit the same issue and the workaround in https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-827547710 seems to work for us.

The Kubernetes project currently lacks enough active contributors to adequately respond to all issues and PRs.

This bot triages issues and PRs according to the following rules:
- After 90d of inactivity, `lifecycle/stale` is applied
- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed

You can:
- Reopen this issue or PR with `/reopen`
- Mark this issue or PR as fresh with `/remove-lifecycle rotten`
- Offer to help out with [Issue Triage][1]

Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).

/close

[1]: https://www.kubernetes.dev/docs/guide/issue-triage/

@k8s-triage-robot: Closing this issue.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-981087259):

>The Kubernetes project currently lacks enough active contributors to adequately respond to all issues and PRs.
>
>This bot triages issues and PRs according to the following rules:
>- After 90d of inactivity, `lifecycle/stale` is applied
>- After 30d of inactivity since `lifecycle/stale` was applied, `lifecycle/rotten` is applied
>- After 30d of inactivity since `lifecycle/rotten` was applied, the issue is closed
>
>You can:
>- Reopen this issue or PR with `/reopen`
>- Mark this issue or PR as fresh with `/remove-lifecycle rotten`
>- Offer to help out with [Issue Triage][1]
>
>Please send feedback to sig-contributor-experience at [kubernetes/community](https://github.com/kubernetes/community).
>
>/close
>
>[1]: https://www.kubernetes.dev/docs/guide/issue-triage/


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

@fabianopimentel: You can't reopen an issue/PR unless you authored it or you are a collaborator.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-989129676):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

/reopen

@apratina: You can't reopen an issue/PR unless you authored it or you are a collaborator.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-1017917529):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

/reopen

@hannahtaub: You can't reopen an issue/PR unless you authored it or you are a collaborator.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-1017919449):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>

/reopen

@htaub: Reopened this issue.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/87733#issuecomment-1017921094):

>/reopen


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes/test-infra](https://github.com/kubernetes/test-infra/issues/new?title=Prow%20issue:) repository.
</details>
