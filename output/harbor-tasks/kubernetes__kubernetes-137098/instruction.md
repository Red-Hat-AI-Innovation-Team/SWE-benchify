container_swap_usage_bytes metric is always 0 in kubelet resource metrics
### What happened?

The container_swap_usage_bytes metric exposed by Kubelet's resource metrics API (/metrics/resource) consistently reports 0, even when containers are actively using swap.

```
container_swap_usage_bytes{container="event-exporter",namespace="kube-system",pod="event-exporter-gke-54578fb7bb-cdmd4"} 0 1771366453461
```

Stats summary shows the correct usage:

```
{
   "podRef": {
    "name": "event-exporter-gke-54578fb7bb-cdmd4",
    "namespace": "kube-system",
    "uid": "43bbf834-faf8-4f46-b016-b468c283382a"
   },
   "startTime": "2026-02-17T19:57:38Z",
   "containers": [
    {
     "name": "event-exporter",
     "swap": {
      "time": "2026-02-17T22:15:35Z",
      "swapAvailableBytes": 133222400,
      "swapUsageBytes": 1024000
       }
     }
  ]
}
```

The pod_swap_usage_bytes metric also reports the correct value. Additionally, the Kubelet summary API (/stats/summary) correctly populates the swap usage for both pods and containers.

```
pod_swap_usage_bytes{namespace="kube-system",pod="event-exporter-gke-54578fb7bb-cdmd4"} 1.024e+06 1771366463287
```

### What did you expect to happen?

The container_swap_usage_bytes metric in /metrics/resource should report the actual swap usage of the container, consistent with the data available in cAdvisor and the summary API.

### How can we reproduce it (as minimally and precisely as possible)?

1. Enable swap on a Linux node and configure Kubelet to support it.
2. Deploy a pod that actively consumes swap memory.
3. Query the Kubelet resource metrics endpoint: /metrics/resource
4. Observe that container_swap_usage_bytes is 0 for the container.
5. Verify that /stats/summary shows a non-zero value for the same container's swap usage.

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.32.4-dispatcher
Kustomize Version: v5.5.0
Server Version: v1.35.0-gke.2232000
```

Node version: v1.35.0-gke.2232000

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
NAME="Container-Optimized OS"
ID=cos
PRETTY_NAME="Container-Optimized OS from Google"
HOME_URL="https://cloud.google.com/container-optimized-os/docs"
BUG_REPORT_URL="https://cloud.google.com/container-optimized-os/docs/resources/support-policy#contact_us"
GOOGLE_CRASH_ID=Lakitu
GOOGLE_METRICS_PRODUCT_ID=26
KERNEL_COMMIT_ID=907f3d47b4cd729b87de8f40712f7f4d92c1e0ae
VERSION=125
VERSION_ID=125
BUILD_ID=19216.104.45
$ uname -a
Linux gke-swaplssd-n4-eebeca1f-lhf0 6.12.55+ #1 SMP Wed Dec  3 09:18:09 UTC 2025 x86_64 INTEL(R) XEON(R) PLATINUM 8581C CPU @ 2.10GHz GenuineIntel GNU/Linux

```

</details>


### Install tools

<details>

</details>


### Container runtime (CRI) and version (if applicable)

<details>
$ containerd --version
containerd github.com/containerd/containerd/v2 2.1.4 207ad711eabd375a01713109a8a197d197ff6542
</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>

</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `4179ebc3d6528d16d1295f9e64d43c7b829124b1`
