kube_apiserver clusterip_allocator available_ips reports negative available ips when using multiple servicecidr
### What happened?

```
❯ kubectl get servicecidr
NAME                       CIDRS            AGE
kubernetes                 172.29.8.0/22    168d
service-cidr-extension-1   172.28.48.0/22   156d
```

```
kubectl get ipaddress -A -l ipaddress.kubernetes.io/managed-by=ipallocator.k8s.io --no-headers | wc -l
    1051
```

```
# TYPE kube_apiserver_clusterip_allocator_allocated_ips gauge
kube_apiserver_clusterip_allocator_allocated_ips{cidr="172.28.48.0/22"} 1050
kube_apiserver_clusterip_allocator_allocated_ips{cidr="172.29.8.0/22"} 1051

# TYPE kube_apiserver_clusterip_allocator_allocation_total counter
kube_apiserver_clusterip_allocator_allocation_total{cidr="172.28.48.0/22",scope="dynamic"} 25
kube_apiserver_clusterip_allocator_allocation_total{cidr="172.29.8.0/22",scope="dynamic"} 197

# TYPE kube_apiserver_clusterip_allocator_available_ips gauge
kube_apiserver_clusterip_allocator_available_ips{cidr="172.28.48.0/22"} -28
kube_apiserver_clusterip_allocator_available_ips{cidr="172.29.8.0/22"} -28
```

### What did you expect to happen?

no negative numbers

### How can we reproduce it (as minimally and precisely as possible)?

create cluster with multiple service cidrs and create more services than the first cird can hold
(or just observe that available ips is not the sum of both cidrs)

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
Server Version: v1.33.4
```

</details>


### Cloud provider

<details>
aws
</details>


### OS version

_No response_

### Install tools

_No response_

### Container runtime (CRI) and version (if applicable)

_No response_

### Related plugins (CNI, CSI, ...) and versions (if applicable)

_No response_

**Repository:** `kubernetes/kubernetes`
**Base commit:** `5277a104e6abe448cb362e2b699f0d38f7498c8e`

## Hints

/sig network
cc @aojea 

OMG, so `kube_apiserver_clusterip_allocator_available_ips` seems to only consider the first range for total number of ips, and when it substracts the number of allocated it gives a negative number

This is the metric

https://github.com/kubernetes/kubernetes/blob/0a4651c9910533f4649b8a11c334cf23237b1ccc/pkg/registry/core/service/ipallocator/metrics.go#L45-L53

I need to look more careful but it seems the metrics system is not handling well the multiple allocators on the system https://github.com/kubernetes/kubernetes/blob/0a4651c9910533f4649b8a11c334cf23237b1ccc/pkg/registry/core/service/ipallocator/ipallocator.go

/triage accepted

https://github.com/kubernetes/kubernetes/blob/master/pkg/registry/core/service/ipallocator/ipallocator.go#L427

The Used() method appears to count all IPs across CIDRs, not just IPs in the current CIDR, which might be causing the negative values.

/assign
