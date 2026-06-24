Missing request total apiserver latency and components break down in the audit log annotation
### What happened?

Missing request total apiserver latency and components break down in the audit log annotation causes trouble when we want to narrow down which component took longer for a specific slow request. 

In the audit http filter, `writeLatencyToAnnotation` will track latency in annotation only when the total latency of the given request exceeds 500ms. The total latency is calculated by subtracting request start time `ac.GetEventRequestReceivedTimestamp().Time` from end time `ac.GetEventStageTimestamp()`. 

However, the end time is not assigned until the audit log event is persisted to the audit backend [here](https://github.com/kubernetes/kubernetes/blob/612122f1d79eb148b06bb63fbf392c03f9b73d60/staging/src/k8s.io/apiserver/pkg/endpoints/filters/audit.go#L107)

The issue was probably introduced in https://github.com/kubernetes/kubernetes/pull/129472

### What did you expect to happen?

audit log with latency annotation when the request latency exceeds 500ms

### How can we reproduce it (as minimally and precisely as possible)?

1. remove the 500ms threshold
2. `./hack/local-up-cluster.sh`

```
{
    "kind": "Event",
    "apiVersion": "audit.k8s.io/v1",
    "level": "RequestResponse",
    "auditID": "37a0803e-db81-40a9-a7e9-7af70f97db3c",
    "stage": "ResponseComplete",
    "requestURI": "/api/v1/services",
    "verb": "list",
    "user": {
        "username": "system:apiserver",
        "uid": "5561dcaf-ab44-43d6-9b68-a23b20f8175f",
        "groups": [
            "system:authenticated",
            "system:masters"
        ]
    },
    "sourceIPs": [
        "127.0.0.1"
    ],
    "userAgent": "kube-apiserver/v1.36.0 (linux/amd64) kubernetes/612122f",
    "objectRef": {
        "resource": "services",
        "apiVersion": "v1"
    },
    "responseStatus": {
        "metadata": {},
        "code": 200
    },
    "responseObject": {
        "kind": "ServiceList",
        "apiVersion": "v1",
        "metadata": {
            "resourceVersion": "9142"
        },
        "items": [
            {
                "metadata": {
                    "name": "kubernetes",
                    "namespace": "default",
                    "uid": "a6484250-2aa7-4108-af74-8065a197cbb0",
                    "resourceVersion": "76",
                    "creationTimestamp": "2025-11-28T19:45:45Z",
                    "labels": {
                        "component": "apiserver",
                        "provider": "kubernetes"
                    }
                },
                "spec": {
                    "ports": [
                        {
                            "name": "https",
                            "protocol": "TCP",
                            "port": 443,
                            "targetPort": 6443
                        }
                    ],
                    "clusterIP": "10.0.0.1",
                    "clusterIPs": [
                        "10.0.0.1"
                    ],
                    "type": "ClusterIP",
                    "sessionAffinity": "None",
                    "ipFamilies": [
                        "IPv4"
                    ],
                    "ipFamilyPolicy": "SingleStack",
                    "internalTrafficPolicy": "Cluster"
                },
                "status": {
                    "loadBalancer": {}
                }
            }
        ]
    },
    "requestReceivedTimestamp": "2025-12-09T21:10:31.187178Z",
    "stageTimestamp": "2025-12-09T21:10:31.188860Z",
    "annotations": {
        "apiserver.latency.k8s.io/authentication": "3.056µs",
        "apiserver.latency.k8s.io/authorization": "1.767µs",
        "apiserver.latency.k8s.io/etcd": "629.994µs",
        "apiserver.latency.k8s.io/response-write": "2.248µs",
        "apiserver.latency.k8s.io/serialize-response-object": "57.106µs",
        "apiserver.latency.k8s.io/total": "-2562047h47m16.854775808s",
        "apiserver.latency.k8s.io/transform-response-object": "317ns",
        "authorization.k8s.io/decision": "allow",
        "authorization.k8s.io/reason": ""
    }
}
```

`apiserver.latency.k8s.io/total` is abnormal

### Anything else we need to know?

_No response_

### Kubernetes version

1.34 and above

<details>

```console
devdesk % kubectl version --kubeconfig /var/run/kubernetes/admin.kubeconfig
Client Version: v1.32.8-eks-99d6cc0
Kustomize Version: v5.5.0
Server Version: v1.36.0-alpha.0.30+612122f1d79eb1-dirty
WARNING: version difference between client (1.32) and server (1.36) exceeds the supported minor version skew of +/-1
```

</details>


### Cloud provider

<details>

Upstream code

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
**Base commit:** `e777bba0b23ff0801c6bcbec2ce4567a70aaab74`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

cc @dims
