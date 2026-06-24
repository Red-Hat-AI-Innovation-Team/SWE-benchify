Kubectl dry-run command behavior is weird
### What happened?

Observations when using kubectl apply --dry-run=client:

We noticed inconsistent behavior depending on whether a resource already exists in the cluster:

Resource = Deployment

If the Deployment with same name already exists, --dry-run=client outputs the current live values from the cluster.

If the Deployment with same name does not exist, it outputs the values from the manifest provided.

We  observed same with configmap too.



### What did you expect to happen?

The expectation is the command outputs the values from the manifest provided always.

### How can we reproduce it (as minimally and precisely as possible)?

Create a Deployment object with minimal configuration.
Then, apply the same Deployment manifest name again, but this time add one new field (e.g., serviceAccountName).
Run kubectl apply --dry-run=client with this updated manifest, and observe how the output behaves.

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
$ kubectl version
# paste output here
```

</details>


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


kubectl apply with --dry-run=client - docs confusing/inaccurate
Hi,

> --dry-run='none':
>         Must be "none", "server", or "client". **If client strategy, only print the object that would be sent, without sending it**. If server strategy, submit server-side request without persisting the resource.

The output (without -o yaml) does not "print the object that would be sent" - it just gives a one-liner e.g. the manifest has been configured or unchanged

The output with -o yaml also does not "print the object that would be sent", it just shows the live manifest (without any change)

Am i misunderstanding something?

Thanks,

**Repository:** `kubernetes/kubernetes`
**Base commit:** `a51c7d6f315a95761a1a163db7919027227e8e1f`

## Hints

/sig cli

/triage accepted
We were able to replicate this issue on our end, we'll look in to this.
