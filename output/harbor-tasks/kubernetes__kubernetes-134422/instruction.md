kubectl get ingressclass should display (default) marker like storageclass
### What would you like to be added?

Currently, `kubectl get storageclass` displays a `(default)` marker next to the default StorageClass:
```bash
$ k get storageclass -A
NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
standard (default)   rancher.io/local-path   Delete          WaitForFirstConsumer   false                  32s
```

However, `kubectl get ingressclass` does not show this marker for the default IngressClass (marked with `ingressclass.kubernetes.io/is-default-class: "true"` annotation):

**Current output:**

```bash
$ k get ingressclass               
NAME            CONTROLLER             PARAMETERS                                       AGE
nginx           k8s.io/ingress-nginx   <none>                                           80s
nginx-custom    k8s.io/ingress-nginx   IngressParameters.k8s.example.com/nginx-config   2s
nginx-default   k8s.io/ingress-nginx   <none>                                           2s
```

**Expected output:**

```bash
$ k get ingressclass               
NAME            CONTROLLER             PARAMETERS                                       AGE
nginx           k8s.io/ingress-nginx   <none>                                           80s
nginx-custom    k8s.io/ingress-nginx   IngressParameters.k8s.example.com/nginx-config   2s
nginx-default (default)  k8s.io/ingress-nginx   <none>                                           2s
```

### Why is this needed?

**Consistency**: StorageClass and IngressClass both use similar default annotation patterns, but their kubectl output behavior is inconsistent.

**User Experience**: Users expect consistent behavior across similar resources. The lack of visual indicator requires running additional commands or inspecting annotations manually:
```bash
kubectl get ingressclass -o jsonpath='{range .items[?(@.metadata.annotations.ingressclass\.kubernetes\.io/is-default-class=="true")]}{.metadata.name}{"\n"}{end}'
```

**Discoverability**: New users may not be aware which IngressClass is set as default without checking annotations explicitly.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `1078cf59b99c47ea96847d08922be2bb2016e481`

## Hints

/assign

/sig cli

/sig networking
Hi I like this idea lets get an approval from sig-networking as well though since you will need approvals from both of us on this. I'm ok to triage accepted if they are ok with this.

@mpuckett159: The label(s) `sig/networking` cannot be applied, because the repository doesn't have them.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/134421#issuecomment-3382310851):

>/sig networking
>Hi I like this idea lets get an approval from sig-networking as well though since you will need approvals from both of us on this. I'm ok to triage accepted if they are ok with this.


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig network

Note for triage: looks reasonable?

This seems like an uncontroversial FR

//triage accepted

@thockin Just noting that because it's written with // rather than /, the label doesn’t seem to have been applied. Thanks.

/triage accepted
