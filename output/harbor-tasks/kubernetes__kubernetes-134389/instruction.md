Create ResourceQuota request resource more than limit resource, is it normal?
### What happened?

I can create this ResourceQuota, it cpu request more than limits.
```
apiVersion: v1
kind: ResourceQuota
metadata:
  creationTimestamp: "2025-03-12T09:26:12Z"
  name: quota-test
  namespace: test
  resourceVersion: "654584334"
  uid: b41e9dce-5228-48bf-98d0-ab3980ab56a2
spec:
  hard:
    limits.cpu: "1"
    requests.cpu: "10"
```

### What did you expect to happen?

We can in the webhook to check this value, prevent request value more than limit.

### How can we reproduce it (as minimally and precisely as possible)?

kubectl create -f 
```
apiVersion: v1
kind: ResourceQuota
metadata:
  name: quota-test
spec:
  hard:
    limits.cpu: "1"
    requests.cpu: "10"
```

### Anything else we need to know?

_No response_

### Kubernetes version

```
$ kubectl version
Client Version: v1.30.3
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
Server Version: v1.27.5
WARNING: version difference between client (1.30) and server (1.27) exceeds the supported minor version skew of +/-1
```


### Cloud provider

<details>

</details>


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


### Container runtime (CRI) and version (if applicable)

<details>

</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>

</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `439a3c4f3577f837b273e07e443fbdf19e14b6a7`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig apps
/wg apps

@lengrongfu: The label(s) `wg/apps` cannot be applied, because the repository doesn't have them.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/130743#issuecomment-2717279149):

>/sig apps
>/wg apps


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/assign

If this is the problem, I can fix it.

> What did you expect to happen?
We can in the webhook to check this value, prevent request value more than limit.

maybe we should check it during validation? 🤔
