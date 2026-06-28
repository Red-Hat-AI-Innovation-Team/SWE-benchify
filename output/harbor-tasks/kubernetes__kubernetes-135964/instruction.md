kubectl get storageclass should indicate the effective default StorageClass when multiple defaults exist
### What would you like to be added?

When multiple StorageClasses are annotated as default (`storageclass.kubernetes.io/is-default-class: "true"`), Kubernetes uses the most recently created one as the actual default applied to PVCs without an explicit storageClassName.
https://kubernetes.io/docs/concepts/storage/storage-classes/#default-storageclass

However, kubectl get storageclass currently shows all of them simply as (default), which makes it unclear which StorageClass will actually be used.

I propose enhancing the kubectl get storageclass output to indicate which default StorageClass is effective.

For example:
```
NAME                       PROVISIONER                   RECLAIMPOLICY   AGE
nfs-client (default, effective)   k8s-sigs.io/nfs-...  Delete          3s
standard   (default, inactive)    rancher.io/local-path Delete         48m
```

or by adding a new column:
```
NAME         PROVISIONER                   DEFAULT   EFFECTIVE   AGE
nfs-client   k8s-sigs.io/nfs-...           true      true        3s
standard     rancher.io/local-path         true      false       48m
```

now display
```
NAME                    PROVISIONER                RECLAIMPOLICY   AGE
nfs-client (default)    k8s-sigs.io/nfs-...        Delete          3s
standard   (default)    rancher.io/local-path      Delete          48m
```

### Why is this needed?

This improves user experience and reduces operational mistakes.

**Repository:** `kubernetes/kubernetes`
**Base commit:** `7ca181be9704208a57ed45dd3c506f81cfe2d463`

## Hints

/sig sli
/sig api-machinery

@jaehanbyun: The label(s) `sig/sli` cannot be applied, because the repository doesn't have them.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/134568#issuecomment-3397356583):

>/sig sli
>/sig api-machinery


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/assign


/sig cli

/cc @seans3 
I think sig-cli should take a look for this UX change?

/sig storage

@soltysh What do you think about this proposal? when u have time, ptal :)

/triage accepted
/remove-sig api-machinery storage
We will implement this by only displaying the most recently created storage class as the default. Thank you for this suggestion.

> [@soltysh](https://github.com/soltysh) What do you think about this proposal? when u have time, ptal :)

Basically what Marly is saying, we want to present only single `(default)` value based on that [link provided](https://kubernetes.io/docs/concepts/storage/storage-classes/#default-storageclass), so the output should look like this:
```
NAME                       PROVISIONER                   RECLAIMPOLICY   AGE
nfs-client (default)		k8s-sigs.io/nfs-...			Delete          3s
standard					rancher.io/local-path		Delete         	48m
```
Notices only single `(default)` value, even though multiple storageclasses have the default annotation. 

@mpuckett159 @soltysh
Thanks for the review and guidance!  
I’ll open a PR implementing the single (default) display behavior.
