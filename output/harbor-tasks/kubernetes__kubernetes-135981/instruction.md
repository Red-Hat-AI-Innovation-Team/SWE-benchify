scheduler_unschedulable_pods metric might broke when running PreEnqueue plugins
### What happened?

`scheduler_unschedulable_pods` metric stores the number of unschedulable pods broken down by plugin name. It is incremented when the pod is re-added to the scheduling queue (with its all unschedulable and pending plugins) as well as when `PreEnqueue` plugin fails for such pod. When the pod is popped out from the scheduling queue, the metric is decremented using pod's unschedulable and pending pods lists. However, if `PreEnqueue` fails for a plugin that was already reported as unschedulable for a pod, the metric is still incremented (multiple ones for one plugin and one pod) what leads to not clearing the metric properly when popping out the pod.

### What did you expect to happen?

`scheduler_unschedulable_pods` metric to be incremented properly when `PreEnqueue` fails.

### How can we reproduce it (as minimally and precisely as possible)?

Create a pod that will get rejected by a plugin while scheduling (e.g. on `Filter`) and then blocked by `PreEnqueue` by the same plugin. If the pod is finally scheduled, the `scheduler_unschedulable_pods` will be non-zero.

### Anything else we need to know?

/sig scheduling

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

**Repository:** `kubernetes/kubernetes`
**Base commit:** `0ba578f91f5de11776152b55bac37491d9848ef3`

## Hints

/cc 

I will take a look at this issue 

/assign @googs1025 
/triage accepted

Hi @googs1025 ,
I'm looking to contribute to Kubernetes and noticed you're assigned to #132333. If you're no longer able to work on it or would like help to resolve it, I'd be happy to take over.

sorry for late. Due to limited bandwidth, you can go on. 😄 

/uassign 



/unassign

/assign @manthan-parmar-1998
