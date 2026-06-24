kube-proxy generate no iptables rules when endpointslices have two ep with same ip but one pod is terminating
### What happened?

Two pods with same ip, one pod is running, one pod is terminating
```
[root@xxx:~]$ kubectl get pod -owide
NAME                               READY   STATUS        RESTARTS   AGE    IP             NODE             NOMINATED NODE   READINESS GATES
caas-deployment-6ddfd47c58-w724s   1/1     Terminating   0          44h    172.30.4.119   192.168.11.234   <none>           <none>
caas-deployment-6ddfd47c58-wp7jk   1/1     Running       0          101s   172.30.4.119   192.168.11.233   <none>           <none>
```

endpointslices have two endpoints
```
**[root@xxx:/paasdata/op-log/k8s]$ kubectl get endpointslices svc-clusterip-deploy-v6hns -o yaml 
addressType: IPv4
apiVersion: discovery.k8s.io/v1
endpoints:
- addresses:
  - 172.30.4.119
  conditions:
    ready: false
    serving: false
    terminating: true
  nodeName: 192.168.11.234
  targetRef:
    kind: Pod
    name: caas-deployment-6ddfd47c58-w724s
    namespace: default
    uid: b73ef9fb-4546-4fa9-a202-cdc67cd9850b
- addresses:
  - 172.30.4.119
  conditions:
    ready: true
    serving: true
    terminating: false
  nodeName: 192.168.11.233
  targetRef:
    kind: Pod
    name: caas-deployment-6ddfd47c58-wp7jk
    namespace: default
    uid: fe8436fe-c172-46a8-b816-0c6c0d29b897
kind: EndpointSlice

```

curl with clusterip failed, no iptables rules are created by kube-proxy
```
[root@xxx:/paasdata/op-log/k8s]$ curl 10.254.223.183:80
curl: (7) Failed to connect to 10.254.223.183 port 80: Connection refused

[root@xxx:/paasdata/op-log/k8s]$ iptables-save | grep svc-clusterip-deploy
-A KUBE-SERVICES -d 10.254.223.183/32 -p tcp -m comment --comment "default/svc-clusterip-deploy:web has no endpoints" -j REJECT --reject-with icmp-port-unreachable
```

### What did you expect to happen?

iptables rules is normal.

### How can we reproduce it (as minimally and precisely as possible)?

The CNI plugin must support assigning static IPs to pods of the deployment type. 

When the node hosting the pod powers down, the pod is evicted. However, because the kubelet fails to clean up, the pod remains in a terminating state while the newly created pod enters a running state. 

Both pods share the same IP address.

### Anything else we need to know?

in k8s1.22, two pods with same ip will cause endpointslices only have the terminating endpont sometimes, because two endpoint have same hash key.

https://github.com/kubernetes/kubernetes/blob/bc4763cbf8b9e6adfbc07bb3194509b187b0b901/pkg/controller/util/endpointslice/endpointset.go#L49-L54

https://github.com/kubernetes/kubernetes/blob/bc4763cbf8b9e6adfbc07bb3194509b187b0b901/pkg/controller/util/endpointslice/endpointset.go#L35-L43

for endpointslices with one terminating endpoint, kube-proxy will not generate iptables rules. we modify Insert function to solve the replace problem, but it not take affect in k8s 1.28 and newer version due to #115907.
```
func (s EndpointSet) Insert(items ...*discovery.Endpoint) EndpointSet {
	for _, item := range items {
		// 1. two pods with same pod ip, pod1 is running, pod2 is terminating
		// 2. if pod1 already insert into EndpointSet, pod2 should not override pod1
		if _, ok := s[hashEndpoint(item)]; ok {
			if *item.Conditions.Terminating || *item.Conditions.Ready == false {
				continue
			}
		}

		s[hashEndpoint(item)] = item
	}
	return s
}
```

after pr #115907 merged, two pods with same ip, endpointslices will have two endpoint, kube-proxy handle the endpointslice,  function addEndpoints will only return one endpoint. it maybe the terminating pod, and kube-proxy will not generate iptables rules also.

https://github.com/kubernetes/kubernetes/blob/9c915e357f3805124401f0ccf2babf28beb9d8aa/pkg/proxy/endpointslicecache.go#L235-L240


/assign @aojea 

### Kubernetes version

<details>

```console
$ kubectl version
# paste output here
Client Version: v1.28.3
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
Server Version: v1.28.3

but i think the bug is exist in master branch
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
**Base commit:** `101ee1bc9c6c276090c9708abfd5db52eaea2657`

## Hints

/assign @aojea     PTAL

/sig network

@pandaamanda how did you decide who to assign this to? (assigning to one person can look like asking everyone else to skip working on it)

> i think the bug is exist in master branch

It'd be great to get this confirmed. AIUI, anyone is welcome to check.

> [@pandaamanda](https://github.com/pandaamanda) how did you decide who to assign this to? (assigning to one person can look like asking everyone else to skip working on it)

I discuss the problem with @aojea in https://github.com/kubernetes/kubernetes/pull/115907#discussion_r2513918410_

maybe @aojea  can have a look ?
            

@pandaamanda can you please confirm that this patch solves your issue https://github.com/kubernetes/kubernetes/pull/135334 ?

> [@pandaamanda](https://github.com/pandaamanda) can you please confirm that this patch solves your issue [#135334](https://github.com/kubernetes/kubernetes/pull/135334) ?

/lgtm

does that means that you have tested and worked?

> does that means that you have tested and worked?

i have already test with same logic.

```
if endpoint, exists := endpointSet[endpointInfo.String()]; !exists || (endpointInfo.Ready && endpointInfo.Serving && !endpoint.IsServing() && !endpoint.IsReady()) || (isLocal && !endpointInfo.Terminating) {
    endpointSet[endpointInfo.String()] = cache.makeEndpointInfo(endpointInfo, svcPortName)
}
```

/triage accepted
already a PR for this

/assign @danwinship 

"it is not as easy as you think" .... Dan will take over, there are multiple cases as same endpoint in the same slice, same endpoint in different slices, same endpoint different pod reference, plus ready, serving, terminating states ...
