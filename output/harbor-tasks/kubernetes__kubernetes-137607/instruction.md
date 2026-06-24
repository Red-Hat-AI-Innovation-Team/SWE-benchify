Flaky test: [sig-node] [DRA] retries pod scheduling after updating device class
### Which jobs are flaking?

TestGrid Link: https://testgrid.k8s.io/sig-release-1.34-blocking#gce-cos-k8sbeta-default

Failed Run: https://prow.k8s.io/view/gs/kubernetes-ci-logs/logs/ci-kubernetes-e2e-gce-cos-k8sbeta-default/1955087524003057664

e2e test: https://github.com/kubernetes/kubernetes/blob/790393ae92e97262827d4f1fba24e8ae65bbada0/test/e2e/dra/dra.go#L801

The test failed with the following error:
```
{ failed [FAILED] schedule pod: Timed out after 80.001s.
expected pod to be pod is scheduled, got instead:
```

The error is originating from: https://github.com/kubernetes/kubernetes/blob/790393ae92e97262827d4f1fba24e8ae65bbada0/test/e2e/dra/utils/builder.go#L399-L404

The test times out waiting for the pod to be scheduled
```
status:
          conditions:
          - lastProbeTime: null
            lastTransitionTime: "2025-08-12T02:18:04Z"
            message: '0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane:
              }, 1 timed out trying to allocate devices, 2 cannot allocate all claims. still
              not schedulable, preemption: 0/4 nodes are available: 4 Preemption is not helpful
              for scheduling.'
            observedGeneration: 1
            reason: Unschedulable
            status: "False"
            type: PodScheduled
          phase: Pending
          qosClass: BestEffort
          resourceClaimStatuses:
          - name: my-inline-claim
            resourceClaimName: tester-1-my-inline-claim-mhnh9
```

https://github.com/kubernetes/kubernetes/blob/790393ae92e97262827d4f1fba24e8ae65bbada0/test/e2e/framework/pod/wait.go#L863-L867

A timeline of the events constructed from the audit log:
- a) `02:17:43.699544Z`: the device class is updated to `expression: false`
```
  "auditID": "084c3e2f-262d-44d4-830a-79bc4851ed7f",
  "stage": "ResponseComplete",
  "requestURI": "/apis/resource.k8s.io/v1/deviceclasses/dra-6628-class",
  "verb": "update",
```
- b) `02:17:44.023`: the test pod `dra-6628/tester-1` gets created
- c) the test starts waiting for the pod to be Unschedulable 
- d) `02:17:54.385781Z`: the scheduler adds the status `Unschedulable`
```
  "auditID": "1f7d7773-12f4-4b2e-8b21-0948750b0d23",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/dra-6628/pods/tester-1/status",
...
"status": {
      "conditions": [
        {
          "lastProbeTime": null,
          "lastTransitionTime": "2025-08-12T02:17:54Z",
          "message": "0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, 3 cannot allocate all claims. still not schedulable, preemption: 0/4 nodes are available: 4 Preemption is not helpful for scheduling.",
          "observedGeneration": 1,
          "reason": "Unschedulable",
          "status": "False",
          "type": "PodScheduled"
        }
      ]
    }
```
- e) `02:17:56.638903Z`: the device class is restored by the test so the pod can be scheduled
```
  "auditID": "6a2a511c-2c62-4c58-aa78-4d9dfb564c10",
  "stage": "ResponseComplete",
  "requestURI": "/apis/resource.k8s.io/v1/deviceclasses/dra-6628-class",
  "verb": "update",
```
- f) the test starts waiting for the pod to be scheduled
- g) `02:18:04.292566Z`: The scheduler updates the pod status
```
  "auditID": "a88f656d-6447-4e27-a7ae-8b53e9fe26a5",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/dra-6628/pods/tester-1/status",
  "verb": "patch",
  ...
    "status": {
      "conditions": [
        {
          "lastProbeTime": null,
          "lastTransitionTime": "2025-08-12T02:18:04Z",
          "message": "0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, 3 cannot allocate all claims. still not schedulable, preemption: 0/4 nodes are available: 4 Preemption is not helpful for scheduling.",
          "observedGeneration": 1,
          "reason": "Unschedulable",
          "status": "False",
          "type": "PodScheduled"
        }
      ]
    }
```
- h) `02:18:15.027340Z`: The scheduler updates the pod status
```
  "auditID": "40e22815-28b1-4111-9db5-42e03ea8f344",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/dra-6628/pods/tester-1/status",
  "verb": "patch",
  ...
  "requestObject": {
    "status": {
      "$setElementOrder/conditions": [
        {
          "type": "PodScheduled"
        }
      ],
      "conditions": [
        {
          "message": "0/4 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, 1 timed out trying to allocate devices, 2 cannot allocate all claims. still not schedulable, preemption: 0/4 nodes are available: 4 Preemption is not helpful for scheduling.",
          "type": "PodScheduled"
        }
      ]
    }
  },  
```
- i) `T02:19:17`: the test times and deletes the pod
```
  "auditID": "21099d72-783f-405a-84dc-0f0c6e60ec00",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/dra-6628/pods/tester-1",
  "verb": "delete", 
```
The test times out after `80s`, and the wait between `e` and `i` is expectedly about `80s`

The test restored the deviceclass at `02:17:56` (from `e`), and it seems the scheduler did not pick up DeviceClass update, I did not see any "DeviceClassUpdate" event, is this not expected?

The scheduler does show slow traces around the time the test was running:
```
I0812 02:18:04.188864      11 trace.go:236] Trace[1802395760]: "Scheduling" namespace:dra-6628,name:tester-1 (12-Aug-2025 02:17:54.394) (total time: 9794ms):
Trace[1802395760]: ---"Snapshotting scheduler cache and node infos done" 0ms (02:17:54.394)
Trace[1802395760]: ---"Computing predicates done" 9794ms (02:18:04.188)
Trace[1802395760]: [9.794235951s] [9.794235951s] END
```

Could that cause the scheduler to not pick up the changes to the deviceclass? I do see the scheduler picking up other events though

### Relevant SIG(s)

/sig node

**Repository:** `kubernetes/kubernetes`
**Base commit:** `7d56731021ecb86428eea2cd910f0406372c897f`

## Hints

In step h, `1 timed out trying to allocate devices` indicates that the filter operation for one node did not complete within 10 seconds (https://github.com/kubernetes/kubernetes/pull/132033). **Why** it takes that long is unclear. Perhaps the scheduler really was CPU starved?

Is it always this one test which fails?

> The test restored the deviceclass at 02:17:56 (from e), and it seems the scheduler did not pick up DeviceClass update, I did not see any "DeviceClassUpdate" event, is this not expected?

Are other events logged? I don't think events get logged in sufficient detail to draw the conclusion that the update was missed. If it was, there would be no scheduling attempt.


I just checked a successful run https://prow.k8s.io/view/gs/kubernetes-ci-logs/logs/ci-kubernetes-e2e-gce-cos-k8sbeta-default/1955102875705151488

I do see the `DeviceClassUpdate` event.
```
I0812 03:24:14.360703      11 scheduling_queue.go:1216] "Pod moved to an internal scheduling queue" pod="dra-1603/tester-1" event="resource.k8s.io/DeviceClassUpdate" queue="Active" hint=1
```


That log message is printed because the pod was moved, not because of receiving the event. If the pod wasn't in the unschedulable queue when the event was received, there's no output about receiving the event because it had no effect and there are many such events. Logging all of them would be too much.

I still think the main problem of at least this one run is the `1 timed out trying to allocate devices` - that shouldn't have happened. It doesn't seem to occur often. https://storage.googleapis.com/k8s-triage/index.html?test=retries%20pod%20scheduling%20after%20updating%20device%20class has some failures, but none related to it.

Searching for other occurrences (https://storage.googleapis.com/k8s-triage/index.html?text=timed%20out%20trying%20to%20allocate%20devices) leads to exactly one other failure in another test (https://prow.k8s.io/view/gs/kubernetes-ci-logs/logs/ci-kubernetes-e2e-gce-cos-k8sbeta-default/1954404589973278720).

I'm tentatively leaning towards "control plane overloaded" as the explanation for this issue.



> I'm tentatively leaning towards "control plane overloaded" as the explanation for this issue.

I did not see any metrics dump in the e2e artifacts, so I used the audit entries from the kube-apiserver to plot a latency distribution:
- use only the `GET` requests: jq filter `select(.stage == "ResponseComplete" and .verb == "get" and .objectRef != null and .objectRef.subresource == null)`
- latency of a request in milliseconds is `event.StageTimestamp.Time.Sub(event.RequestReceivedTimestamp.Time).Milliseconds()`

failed run:
- we can see an elevation in the latency distribution (highlighted in the rectangle) that lasts for about 3m , this can potentially be the control plane overload
- if we look at the test run, it overlaps with the degradation window.

successful run:
- the elevation in the latency distribution is pretty similar to the failed run
- on the contrary, the test run does not overlap with the degradation, it runs about 8m later where the latency distribution seems normal.

<img width="1918" height="1007" alt="Image" src="https://github.com/user-attachments/assets/de69b11a-42ee-46f6-9d3b-cf5b3e468684" />

<img width="1918" height="1007" alt="Image" src="https://github.com/user-attachments/assets/11b63913-2b5a-4201-a8bd-d9a5064d6106" />




/triage accepted
/priority important-longterm

/assign
