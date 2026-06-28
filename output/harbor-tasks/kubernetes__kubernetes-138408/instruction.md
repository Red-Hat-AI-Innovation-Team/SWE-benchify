[DRA] pod.status.resourceClaimStatuses entries are flapping
### What happened?

I have a Pod that uses two ResourceClaimTemplates that is stuck in pending for various (irrelevant) reasons. I noticed that the status.resourceClaimStatuses field was flapping between entries with the the RCs created for each of the templates:

```console
$ kubectl get pods vllm-opt-125m-6b6f655ddb-8zb4p -w -o custom-columns="NAME:.metadata.name,RV:.metadata.resourceVersion,CLAIM STATUSES:.status.resourceClaimStatuses[*].name"
NAME                             RV                    CLAIM STATUSES
vllm-opt-125m-6b6f655ddb-8zb4p   1776286634735007008   model
vllm-opt-125m-6b6f655ddb-8zb4p   1776286634832495008   model
vllm-opt-125m-6b6f655ddb-8zb4p   1776286634891151008   gpu
vllm-opt-125m-6b6f655ddb-8zb4p   1776286634934959008   model
vllm-opt-125m-6b6f655ddb-8zb4p   1776286634986255008   gpu
vllm-opt-125m-6b6f655ddb-8zb4p   1776286635035711008   model
vllm-opt-125m-6b6f655ddb-8zb4p   1776286635087583008   gpu
vllm-opt-125m-6b6f655ddb-8zb4p   1776286635134271008   model
vllm-opt-125m-6b6f655ddb-8zb4p   1776286635186143008   gpu
vllm-opt-125m-6b6f655ddb-8zb4p   1776286635235007008   model
```

This shouldn't be happening. Once the resource claims are created, they should be added there and it should remain stable.

### What did you expect to happen?

Once the resource claims are created, they should be added there and it should remain stable. Here's an example of a Pod that has reached `Running` state:

```console
$ kubectl get pods vllm-gemma-4-e2b-it-586d595ffc-85k4h -w -o custom-columns="NAME:.metadata.name,RV:.metadata.resourceVersion,CLAIM STATUSES:.status.resourceClaimStatuses[*].name"
NAME                                   RV                    CLAIM STATUSES
vllm-gemma-4-e2b-it-586d595ffc-85k4h   1776276444200351023   gpu,model
```

### How can we reproduce it (as minimally and precisely as possible)?

I suspect this happens whenever a pod is in pending and uses multiple ResourceClaims, but I am not sure. I have a unit test that reproduces it, but not an e2e test. I will submit a PR with the unit test and a fix.

### Anything else we need to know?

/wg device-management
/sig node

### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.35.3
Kustomize Version: v5.7.1
Server Version: v1.35.1-gke.1396002
```

With the DRAConsumableCapacity feature gate enabled.
</details>


### Cloud provider

<details>
GKE
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
**Base commit:** `f665f2605bbd23e4fdbcde91f054469c855b5cb9`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>
