kube-apiserver fails to start because start-service-ip-repair-controllers PostStartHook fails
### What happened?

When upgrading a Kubernetes cluster from v1.32 to v1.33 by creating new control plane nodes with v1.33 manifests, the kube-apiserver fails to start with admission errors. 
```
0115 20:56:16.106534   # log start
...
E0115 20:56:24.741991       1 repairip.go:372] "Unhandled Error" err="the ClusterIP [IPv4]: 10.211.95.185 for Service <namespace foo>/<service bar>is not allocated; repairing" logger="UnhandledError"
...
Trace[295533714]: ---"Write to database call failed" len:247,err:ipaddresses.networking.k8s.io "10.211.95.185" is forbidden: not yet ready to handle request 10000ms (20:56:34.744)
Trace[295533714]: [10.000527316s] [10.000527316s] END
E0115 20:56:34.745027       1 repairip.go:235] "Unhandled Error" err="ipaddresses.networking.k8s.io \"10.211.95.185\" is forbidden: not yet ready to handle request" logger="UnhandledError"
I0115 20:56:34.746095       1 repairip.go:236] Shutting down ipallocator-repair-controller
I0115 20:56:34.834949       1 healthz.go:280] informer-sync,poststarthook/start-service-ip-repair-controllers check failed: readyz
[-]informer-sync failed: 4 informers not started yet: [*v1.Pod *v1.ServiceAccount *v1.Secret *v1.Namespace]
[-]poststarthook/start-service-ip-repair-controllers failed: not finished
...
I0115 20:57:06.335471       1 healthz.go:280] informer-sync,poststarthook/start-service-ip-repair-controllers check failed: readyz
[-]informer-sync failed: 1 informers not started yet: [*v1.Secret] # v1.Namespace informer is ready  
[-]poststarthook/start-service-ip-repair-controllers failed: not finished
...
F0115 20:57:18.630248       1 hooks.go:204] PostStartHook "start-service-ip-repair-controllers" failed: unable to perform initial IP and Port allocation check

```

We think this is a race condition introduced by new code path when `MultiCIDRServiceAllocator` is enabled by default in v1.33.  
`start-service-ip-repair-controllers` reads clusterIPs from all `Services` objects and creates `IPAddresses` objects if they are not found from cache. Since we are upgrading from v1.32, where `MultiCIDRServiceAllocator` is disabled, ETCD does not contain any `IPAddresses` objects. 
`start-service-ip-repair-controllers` therefore does not read any existing `IPAddresses` objects from cache and attempts to create them. However, at this point, the `ipaddresses.networking.k8s.io` API is not yet ready. As a result, `start-service-ip-repair-controllers` failes and the kube-apiserver never becomes ready.

Because we have a large number of namespaces, `v1.Namespace` informer takes more time to become ready, which increases the likelihood of this issue occurring in our cluster.
In v1.32 `MultiCIDRServiceAllocator` is disabled. The `start-service-ip-repair-controllers`  implementation only invokes the internal `RangeRegistry` API, which is initialized earlier, so this issue did not exist.



### What did you expect to happen?

The kube-apiserver should start successfully and the repair controller should create missing `IPAddress` objects for existing `Services`, either by:
1. Waiting for admission plugins to be ready before attempting writes
2. Deferring repair work until after startup completes
3. Retrying failed operations instead of terminating

### How can we reproduce it (as minimally and precisely as possible)?

Prerequisites:
- Cluster with large number of `Namespaces` and `Services` 
- `MultiCIDRServiceAllocator` feature gate previously disabled

Steps:
1. Prepare v1.33 kube-apiserver manifests with `MultiCIDRServiceAllocator` enabled by default
2. Start kube-apiserver
3. Observe API server fails to start


### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
control-plane components: v1.33.7
worker node kubelet: v1.30.7
kube-proxy: v1.31.11
```

</details>


### Cloud provider

<details>
Self-managed cluster on AWS ec2 instances

</details>

### OS version

<details>

```console
# On Linux:
$ cat /etc/os-release
PRETTY_NAME="Ubuntu 24.04.3 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.3 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo
$ uname -a
Linux ip-10-206-19-65 6.8.0-1044-aws #46-Ubuntu SMP Fri Nov 21 16:50:44 UTC 2025 x86_64 x86_64 x86_64 GNU/Linux

```

</details>


### Install tools

<details>
kubeadm
</details>


### Container runtime (CRI) and version (if applicable)

<details>
- containerd: v1.7.28
- runc: v1.3.3
- cri-tools: v1.33.0-1.1 
</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>
Calico: v3.30.4
</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `151cebbbef1d28d912e0d9009b0000a220a6b5a3`

## Hints

Hey @haojiwu !
Thanks for reporting this issue, I have deeply analyzed the issue and the relevant code, and will very soon create a PR to fix this issue!
Would be glad if any of the maintainers can assign this issue to me!
Thanks!

Hi maintainers!
I have raised a PR #136290 to fix this issue!
Would love to receive any feedbacks / suggestions for any changes / improvements if needed!
Thanks!

Hi @adityasharmawork very appreciated for your solution! 
I think retry `runOnce()` in `RepairIPAddress` can mitigate this issue in some scenarios, but if the `v1.Namespace` informer takes more than 1 minutes to be synced and ready, the issue still can happen.

Hi @haojiwu !
Thanks for highlighting this edge case, and this error may still persist in large clusters, after analyzing the codebase, I think - 

The Actual Error Source -                                                                                                                                          
                                                                                                                                                                 
 The "not yet ready to handle request" error for IPAddresses comes from the Webhook Admission Plugin, not the NamespaceLifecycle plugin.                         
                                                                                                                                                                 
 File: staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/generic/webhook.go                                                                              
                                                                                                                                                       
``` 
// Line 131-133: Webhook readiness depends on Namespace informer                                                                                                
 a.SetReadyFunc(func() bool {                                                                                                                                    
     return namespaceInformer.Informer().HasSynced() && a.hookSource.HasSynced()                                                                                 
 })  
```                                                                                                                                                            
                                                                                                                                                                 
``` 
// Line 257-258: Dispatch blocks if not ready                                                                                                                   
 if !a.WaitForReady() {                                                                                                                                          
     return admission.NewForbidden(attr, fmt.Errorf("not yet ready to handle request"))                                                                          
 }                                                                                                                                                               
```
                                                                                                                                                                 
 IPAddresses are cluster-scoped resources, so NamespaceLifecycle doesn't apply to them. But the Webhook admission plugin applies to ALL resources and requires   
 the Namespace informer to be synced. 

The Solution -                                                                                                                                                
                                                                                                     
 Strategy: Wait for Namespace Informer + Keep Retry Logic                                                                                                        
                                                                                                                                                                 
 The most correct fix is to wait for the Namespace informer to sync before calling runOnce(), because:                                                           
                                                                                                                                                                 
 1. The Webhook admission plugin depends on it                                                                                                                   
 2. The Namespace informer is already available in the SharedInformerFactory                                                                                     
 3. This follows existing patterns in the codebase                                                                                                               
 4. It addresses the root cause directly 

What About Very Large Clusters?                                                                                                                                 
                                                                                                                                                                 
 If the Namespace informer takes > 1 minute to sync:                                                                                                             
 - The PostStartHook will still timeout (this is by design for backward compatibility)                                                                           
 - The fix still helps by avoiding unnecessary runOnce() failures                                                                                                
 - For such extreme cases, users may need to increase the timeout (separate discussion)  




 Implementation Plan                                                                                                                                             
                                                                                                                                                                 
 File 1: pkg/registry/core/service/ipallocator/controller/repairip.go                                                                                            
                                                                                                                                                                 
 Changes needed:                                                                                                                                                 
                                                                                                                                                                 
 1. Add Namespace informer field to struct (around line 100):                                                                                                    
``` 
type RepairIPAddress struct {                                                                                                                                   
     // ... existing fields ...                                                                                                                                  
                                                                                                                                                                 
     // Namespace informer synced function - required because admission plugins                                                                                  
     // (especially webhooks) depend on the Namespace informer being synced                                                                                      
     namespaceSynced cache.InformerSynced  // ADD THIS                                                                                                           
 }                                                                                                                                                               
```
                                                                                                                                                                 
 2. Update constructor to accept Namespace informer (line 113-119):                                                                                              
``` 
func NewRepairIPAddress(interval time.Duration,                                                                                                                 
     client kubernetes.Interface,                                                                                                                                
     serviceInformer coreinformers.ServiceInformer,                                                                                                              
     serviceCIDRInformer networkinginformers.ServiceCIDRInformer,                                                                                                
     ipAddressInformer networkinginformers.IPAddressInformer,                                                                                                    
     namespaceInformer coreinformers.NamespaceInformer,  // ADD THIS                                                                                             
 ) *RepairIPAddress {                                                                                                                                            
                                                                                                                                                                
``` 
 3. Store the Namespace synced function (in newRepairIPAddress, around line 139):                                                                                
 namespaceSynced: namespaceInformer.Informer().HasSynced,  // ADD THIS                                                                                           
                                                                                                                                                                 
 4. Wait for Namespace informer in RunUntil (line 213):                                                                                                          
``` 
// Change from:                                                                                                                                                 
 if !cache.WaitForNamedCacheSync("ipallocator-repair-controller", stopCh,                                                                                        
     r.ipAddressSynced, r.servicesSynced, r.serviceCIDRSynced) {                                                                                                 
                                                                                                                                                                 
 // To:                                                                                                                                                          
 if !cache.WaitForNamedCacheSync("ipallocator-repair-controller", stopCh,                                                                                        
     r.ipAddressSynced, r.servicesSynced, r.serviceCIDRSynced, r.namespaceSynced) {                                                                              
```
                                                                                                                                                                 
 5. Keep the retry logic (lines 237-244) - this provides belt-and-suspenders protection                                                                          
                                                                                                                                                                 
 File 2: pkg/registry/core/rest/storage_core.go                                                                                                                  
                                                                                                                                                                 
 Changes needed:                                                                                                                                                 
                                                                                                                                                                 
```
 1. Pass Namespace informer when creating RepairIPAddress (lines 142-148):                                                                                       
 // Change from:                                                                                                                                                 
 p.startServiceClusterIPRepair = serviceipallocatorcontroller.NewRepairIPAddress(                                                                                
     c.Services.IPRepairInterval,                                                                                                                                
     client,                                                                                                                                                     
     c.Informers.Core().V1().Services(),                                                                                                                         
     c.Informers.Networking().V1().ServiceCIDRs(),                                                                                                               
     c.Informers.Networking().V1().IPAddresses(),                                                                                                                
 ).RunUntil                                                                                                                                                      
                                                                                                                                                                 
 // To:                                                                                                                                                          
 p.startServiceClusterIPRepair = serviceipallocatorcontroller.NewRepairIPAddress(                                                                                
     c.Services.IPRepairInterval,                                                                                                                                
     client,                                                                                                                                                     
     c.Informers.Core().V1().Services(),                                                                                                                         
     c.Informers.Networking().V1().ServiceCIDRs(),                                                                                                               
     c.Informers.Networking().V1().IPAddresses(),                                                                                                                
     c.Informers.Core().V1().Namespaces(),  // ADD THIS                                                                                                          
 ).RunUntil                                                                                                                                                     
``` 
                                                                                                                                                                 
 File 3: pkg/registry/core/service/ipallocator/controller/repairip_test.go                                                                                       
                                                                                                                                                                 
 Changes needed:                                                                                                                                                 
                                                                                                                                                                 
 1. Update test helper newFakeRepair to include Namespace informer                                                                                               
 2. Update existing tests to pass Namespace informer                                                                                                             
 3. Keep your new tests (TestRunUntilRetryOnError, etc.)                                                                                                         
 4. Add a test that verifies waiting for Namespace informer                                                                                                      
                                                                                                                                                                 
 ---                                                                                                                                                             
 Why This Is Better Than Just Retry                                                                                                                              
                                                                                                                                                      
 This fix: Waits until we know admission plugins are ready (Namespace informer synced), THEN tries runOnce(). Retries are only for unexpected transient          
 failures.                                                                                                                                                       
                                                                                                                                                                 
 ---                                                                                                                                                             
                                                                                                                                                                                                                             
 Summary of Changes                                                                                                                                              
                                                                                                                                                                 
 pkg/registry/core/service/ipallocator/controller/repairip.go                                                                                                    
 ├── Add namespaceSynced field to RepairIPAddress struct                                                                                                         
 ├── Update NewRepairIPAddress to accept NamespaceInformer                                                                                                       
 ├── Update newRepairIPAddress to store namespaceSynced                                                                                                          
 ├── Update RunUntil to wait for namespaceSynced                                                                                                                 
 └── Keep existing retry logic                                                                                                                                   
                                                                                                                                                                 
 pkg/registry/core/rest/storage_core.go                                                                                                                          
 └── Pass Namespaces informer to NewRepairIPAddress                                                                                                              
                                                                                                                                                                 
 pkg/registry/core/service/ipallocator/controller/repairip_test.go                                                                                               
 ├── Update newFakeRepair helper                                                                                                                                 
 ├── Update existing tests                                                                                                                                       
 └── Add test for namespace informer waiting 


Please lemme know if I am missing out something, I am working on this and will very soon push the changes!

Hi @haojiwu and other maintainers!
i have pushed my latest changes to the #136290 .
I hope the fix now is correct and as per the Kubernetes Standard, however I am thinking of one more approach to completely Decouple PostStartHook from runOnce Success like - 

```
// In RunUntil, after WaitForNamedCacheSync succeeds:                                                                                                          
  onFirstSuccess()  // Signal immediately                                                                                                                        
                                                                                                                                                                 
  // Then run runOnce asynchronously - failures handled by worker loops                                                                                          
  go func() {                                                                                                                                                    
      if err := r.runOnce(); err != nil {                                                                                                                        
          runtime.HandleError(err)                                                                                                                               
      }                                                                                                                                                          
  }()
```

  1. Calling onFirstSuccess() after informers sync (but before runOnce())                                                                                        
  2. Running runOnce() without blocking the PostStartHook                                                                                                        
  3. Letting the worker loops handle any failures 


Your review for the best possible solution would be highly valuable! Thanks!

/sig network
/assign @aojea 

Let me try to understand the problem first, so you say that because the webhooks are not synced they are failing the ipaddress requests, hence causing the startup to fail. 

My question is why are thay failing the IPAddress request? is this some special webhook that you have or it can happen with any webhooks? are other objects created at startup also failing or is specific of the IPAddress object?

> Let me try to understand the problem first, so you say that because the webhooks are not synced they are failing the ipaddress requests, hence causing the startup to fail.
> My question is why are thay failing the IPAddress request? 

From the error 
```
E0115 20:56:34.745027       1 repairip.go:235] "Unhandled Error" err="ipaddresses.networking.k8s.io \"10.211.95.185\" is forbidden: not yet ready to handle request" logger="UnhandledError"
```
I think the failure is retuned from admission webhook, possibly _something_ wasn't ready. 
When the error happens, these 4 informer are not synced: Pod, ServiceAccount, Secret and Namespace.
```
[-]informer-sync failed: 4 informers not started yet: [*v1.Pod *v1.ServiceAccount *v1.Secret *v1.Namespace]
```
My suspicion is that admission webhook returns error becuase Namespace informer is not fully synced. 
In our cluster, Namespace informer takes 1 to 2 minutes to synced.

> is this some special webhook that you have or it can happen with any webhooks? 

I am not sure. Are there related logs that I can check?

> are other objects created at startup also failing or is specific of the IPAddress object?

Yes, it also failed to create `events.events.k8s.io` for the same error.
```
I0115 20:56:34.743478       1 trace.go:236] Trace[668673092]: "Create" accept:application/vnd.kubernetes.protobuf, */*,audit-id:a107d8e1-3b08-4779-8b21-a91a4eef8958,client:::1,api-group:events.k8s.io,api-version:v1,name:,subresource:,namespace:<namespace foo>,protocol:HTTP/2.0,resource:events,scope:resource,url:/apis/events.k8s.io/v1/namespaces/<namespace foo>/events,user-agent:kube-apiserver/v1.33.7 (linux/amd64) kubernetes/a7245cd,verb:POST (15-Jan-2026 20:56:24.742) (total time: 10000ms):
Trace[668673092]: ---"Write to database call failed" len:460,err:events.events.k8s.io "<service bar>.188b0301c10fab69" is forbidden: not yet ready to handle request 10000ms (20:56:34.743)
Trace[668673092]: [10.000699259s] [10.000699259s] END
```

HI @aojea 
Please let us know what additional information we can provide to help clarify the issue. We can consistently reproduce this problem in our cluster when `MultiCIDRServiceAllocator` is enabled.
We’re happy to increase log verbosity or collect any other data that would be useful.
Thanks!

it can be useful if you can upload the entire apiserver log ...  or reproduce the problem on the integration test framework https://github.com/kubernetes/kubernetes/tree/master/test/integration/servicecidr or a kind cluster

Hi @aojea,                                                                                                                                                                                 

I created integration tests in https://github.com/kubernetes/kubernetes/pull/136644 to reproduce the issue.                                                                                `TestServiceIPRepairRaceCondition_RealLoad` creates a large number of namespaces to trigger the issue. On my laptop, 330,000 namespaces can reliably reproduce the issue, while smaller numbers like 250,000 do not trigger it consistently.                                                                                                                                       

However, it takes approximately 30 minutes to create 330,000 namespaces in local etcd. Based on the callstack, I believe the root cause is that the namespace informer is not synced when the repair controller tries to create ipaddress:                                                                                                                                                              

<img width="1022" height="874" alt="Image" src="https://github.com/user-attachments/assets/8cd793b7-8cc6-41f3-9333-b1b1610edd96" />                                                       

To make testing faster, I created `TestServiceIPRepairRaceCondition_SimulatedDelay`, which uses only a small number of namespaces but adds an artificial delay to the namespace informer's `HasSynced()` method. On my laptop, a 20-second delay (simulating the namespace informer taking 20 seconds to fully sync) can consistently trigger the issue.                              

Both tests demonstrate the same race condition, but the simulated delay approach is much faster for iterative debugging and validation.  

hmm, that admisison plgin seems to impact only namespaced objects

https://github.com/kubernetes/kubernetes/blob/8c9c67c000104450cfc5a5f48053a9a84b73cf93/staging/src/k8s.io/apiserver/pkg/admission/plugin/namespace/lifecycle/admission.go#L83-L86

an ipaddress is non namespaced

@aojea 
You are right. 
The ipaddress creation request was not blocked by namespace lifecycle admission. The screenshot I pasted was about other resources.
Instead, ipaddress request was blocked in webhook's `Dispatch()`, https://github.com/kubernetes/kubernetes/blob/081353bf8ad963d43c5da6714a24f62cfe0b8401/staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/generic/webhook.go#L260
I add `debug.PrintStack()` to dump more information
```
E0202 14:21:26.382531   42965 repairip.go:372] "Unhandled Error" err="the ClusterIP [IPv4]: 10.0.0.11 for Service test-repair-race/test-service-1 is not allocated; repairing" logger="UnhandledError"
(debug)2026-02-02 14:21:36.384946 -0800 PST m=+14.312244585 Webhook not ready for request: kind="networking.k8s.io/v1, Kind=IPAddress", resource="networking.k8s.io/v1, Resource=ipaddresses", subresource="", namespace="", name="10.0.0.11", operation="CREATE"
goroutine 6916 [running]:
runtime/debug.Stack()
	/opt/homebrew/opt/go/libexec/src/runtime/debug/stack.go:26 +0x64
runtime/debug.PrintStack()
	/opt/homebrew/opt/go/libexec/src/runtime/debug/stack.go:18 +0x1c
k8s.io/apiserver/pkg/admission/plugin/webhook/generic.(*Webhook).Dispatch(0x140034a8fc0, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, {0x107b2f4e0, 0x140046efba0})
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/generic/webhook.go:266 +0x2d8
k8s.io/apiserver/pkg/admission/plugin/webhook/mutating.(*Plugin).Admit(0x109c3d220?, {0x107b28ef8?, 0x14002362690?}, {0x107b4ed88?, 0x1400ab57200?}, {0x107b2f4e0?, 0x140046efba0?})
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/mutating/plugin.go:75 +0x38
k8s.io/apiserver/pkg/admission/metrics.pluginHandlerWithMetrics.Admit({{0x107ae95e0, 0x1400123f4d0}, 0x1400507b270, {0x1400507b280, 0x1, 0x1}}, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, ...)
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/metrics/metrics.go:97 +0xbc
k8s.io/apiserver/pkg/admission.chainAdmissionHandler.Admit({0x14007792e00?, 0x104265aac?, 0x14003b17b78?}, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, {0x107b2f4e0, 0x140046efba0})
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/chain.go:37 +0x114
k8s.io/apiserver/pkg/admission.(*reinvoker).Admit(0x109c3d220?, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, {0x107b2f4e0, 0x140046efba0})
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/reinvocation.go:37 +0x70
k8s.io/apiserver/pkg/admission/metrics.pluginHandlerWithMetrics.Admit({{0x107aecd00, 0x140051b9b40}, 0x140051b9b50, {0x0, 0x0, 0x0}}, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, ...)
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/metrics/metrics.go:97 +0xbc
k8s.io/apiserver/pkg/admission.(*auditHandler).Admit(0x14002c2b9c0, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, {0x107b2f4e0, 0x140046efba0})
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/admission/audit.go:55 +0xf8
k8s.io/apiserver/pkg/endpoints/handlers/fieldmanager.(*managedFieldsValidatingAdmissionController).Admit(0x109c3fb20?, {0x107b28ef8, 0x14002362690}, {0x107b4ed88, 0x1400ab57200}, {0x107b2f4e0, 0x140046efba0})
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/fieldmanager/admission.go:70 +0xd0
k8s.io/apiserver/pkg/endpoints/handlers.CreateResource.createHandler.func1.2()
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/create.go:203 +0x298
k8s.io/apiserver/pkg/endpoints/handlers/finisher.finishRequest.func1()
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/finisher/finisher.go:117 +0x74
created by k8s.io/apiserver/pkg/endpoints/handlers/finisher.finishRequest in goroutine 6915
	/Users/haoji/Projects/my/kubernetes/staging/src/k8s.io/apiserver/pkg/endpoints/handlers/finisher/finisher.go:92 +0xa4
I0202 14:21:36.385316   42965 httplog.go:134] "HTTP" verb="POST" URI="/apis/networking.k8s.io/v1/ipaddresses" latency="10.001525084s" userAgent="servicecidr.test/v0.0.0 (darwin/arm64) kubernetes/$Format" audit-ID="87959404-3b50-4aee-935b-14d4ba6788f9" srcIP="127.0.0.1:59087" apf_pl="exempt" apf_fs="exempt" apf_iseats=1 apf_fseats=0 apf_additionalLatency="0s" apf_execution_time="10.001415584s" resp=403
E0202 14:21:36.385621   42965 repairip.go:235] "Unhandled Error" err="ipaddresses.networking.k8s.io \"10.0.0.11\" is forbidden: not yet ready to handle request" logger="UnhandledError"
```

However,  I think slowness of namespace informer (from large number of namespace objects) is still the trigger of the issue. In the webhook, the `readyFunc` depends on namespace informer's `HasSynced()` https://github.com/kubernetes/kubernetes/blob/081353bf8ad963d43c5da6714a24f62cfe0b8401/staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/generic/webhook.go#L134

Please let me know any information I can provide. Thank you!


/triage accepted

> However, I think slowness of namespace informer (from large number of namespace objects) is still the trigger of the issue

just to be clear, I think there is something here, if a cluster before ipaddresses was able to boot and after is not looks like a change in behavior ... but we need to fully understand the root cause and avoid trying to workaround the situation, as you can see the apiserver bootstrap has a lot of moving pieces and one change in one can have unpredictable consequences 

@haojiwu @adityasharmawork found the root cause, I was surprised an informer took more than 1 minute in catch up, that will present more serious problems in production.

The main problem is that the ip repair controller only retries on conflicts during the initial sync, so when it sees the `forbidden` error it bails out and never initializes. The fix is:

```diff
diff --git a/pkg/registry/core/service/ipallocator/controller/repairip.go b/pkg/registry/core/service/ipallocator/controller/repairip.go
index feb7fce3076..79c5060e2e5 100644
--- a/pkg/registry/core/service/ipallocator/controller/repairip.go
+++ b/pkg/registry/core/service/ipallocator/controller/repairip.go
@@ -247,7 +247,18 @@ func (r *RepairIPAddress) RunUntil(onFirstSuccess func(), stopCh chan struct{})
 
 // runOnce verifies the state of the ClusterIP allocations and returns an error if an unrecoverable problem occurs.
 func (r *RepairIPAddress) runOnce() error {
-       return retry.RetryOnConflict(retry.DefaultBackoff, r.doRunOnce)
+       return retry.OnError(retry.DefaultBackoff, func(err error) bool {
+               // When trying to repair the ClusterIP allocations, we may get a conflict or forbidden error.
+               // IsForbidden depends on the admission chain to be ready that may depend on the
+               // Namespace informer to be ready.
+               // Ref: https://issues.k8s.io/136288
+               if apierrors.IsConflict(err) || apierrors.IsForbidden(err) {
+                       klog.ErrorS(err, "Running ipallocator repair failed ... retrying")
+                       return true
+               }
+               klog.ErrorS(err, "Running ipallocator repair failed with not retryable error")
+               return false
+       }, r.doRunOnce)
 }
 
```

do you want to send the PR with the fix, the integration tests with `TestServiceIPRepairRaceCondition_RealLoad` maybe commited just with a skip and the comment. The addition of global variables to reproduce the latency does not look good to me, I do not know if we can use other option less invasive, but if not better to avoid it.

Hi @aojea,

Thanks for your investigation and the proposed fix. I will update the PR with your suggested changes.                                                                                       

I do have a follow-up question about the fix: With the retry logic now handling forbidden errors, `runOnce()` can keep retrying `doRunOnce()` when the informer hasn't synced yet. However, looking at the PostStartHook timeout in `pkg/registry/core/rest/storage_core.go`, the `start-service-ip-repair-controllers` hook has a 1-minute timeout:                                
                                                                                                                                                                                              
  ```go                                                                                                                                                                                       
		case <-time.After(time.Minute):
			return goerrors.New("unable to perform initial IP and Port allocation check")                                                                                                      
  ```                                                                                                                                                                                            
If the namespace informer consistently takes more than 1 minutes to sync (which could happen with large number of namespaces), wouldn't the PostStartHook still timeout and fail apiserver startup, even with the retry logic?    

> If the namespace informer consistently takes more than 1 minutes to sync (which could happen with large number of namespaces),

Let's fix one thing at a time, do we have evidence that the List() to etcd takes more than one minute?

Hi @aojea,
I create https://github.com/kubernetes/kubernetes/pull/137147 with the fix and integration test. I only keep the test with real load. The test will be skipped when running short tests.

> > If the namespace informer consistently takes more than 1 minutes to sync (which could happen with large number of namespaces),
> 
> Let's fix one thing at a time, do we have evidence that the List() to etcd takes more than one minute?

In our production control plane (1.33.7, MultiCIDRServiceAllocator=false), here are the logs when creating a new apiserver:
```
# apiserver logs start
W0218 20:41:59.706677       1 feature_gate.go:352] Setting GA feature gate MultiCIDRServiceAllocator=false. It will be removed in a future release.

# server started listening
I0218 20:42:03.657668       1 secure_serving.go:211] Serving securely on [::]:6443

# last health check where Namespace informer is still not synced
I0218 20:43:04.797540       1 healthz.go:280] informer-sync check failed: readyz
[-]informer-sync failed: 3 informers not started yet: [*v1.Secret *v1.Namespace *v1.ServiceAccount]

# first health check where Namespace informer is synced
I0218 20:43:04.895992       1 healthz.go:280] informer-sync check failed: readyz
[-]informer-sync failed: 2 informers not started yet: [*v1.Secret *v1.ServiceAccount]
```
From these logs, the server started listening at 20:42:03. PostStartHooks (including start-service-ip-repair-controllers) are called immediately after Serve() in the [code](https://github.com/kubernetes/kubernetes/blob/b1a9cc347311012bade7230b55ab95229a1e22c9/staging/src/k8s.io/apiserver/pkg/server/genericapiserver.go#L749), though there's no log for the exact moment. At 20:43:04 (~61 seconds later), the Namespace informer was still not synced, and it became synced within the next 100ms. 
So when MultiCIDRServiceAllocator is enabled, the RepairIPAddress controller would be retrying against an unsynced Namespace informer for ~61 seconds — just over the 1-minute timeout.
