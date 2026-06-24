Frequent churn between EndpointSlice objects
### What happened?

We are running a single control-plane k3s cluster in our lab. The cluster has about 56 high-power bare metal nodes. The cluster is used primarily by our developers and our CICD. We create kubevirt VMs for dev and testing. 

Recently as our cluster grew to serve a 100+ kubevirt VMs (running in pods), we noticed significant uptick in the number of ssh and nslookup failures by our CICD system when trying to communicate with the VMs. On average, we would see 1 in 100 or so attempts fail to resolve the VMs IP address. The lookups happened based on the VM name. We use a single headless Service for all of our VMs. 

We wrote a small script to see if we could reproduce the issue. The script would send DNS lookups (dig) to all running healthy VMs (VM status = ready). We noticed that coredns would occasionally return NXDOMAIN for perfectly healthy VMs. Importantly, those VMs were not going through any state transition. The NXDOMIANs would be short-lived, usually < 10 seconds and then it go back to resolving correctly. Again, it's important to note that the VMs(and their pods) for which the NXDOMAIN was received were not transitioning states during this period. 

To see why coredns would behave this way, we wrote another program to watch for updates on the EndpointSlice object. What we noticed was that when the number of endpoints per slice grew greater than 100 (the default value), then, as expected, a new slice would be created. However, what would happen next was surprising. The two endpointslices would start to exhibit significant churn, where endpoints would be frequently be removed from one slice and added to the other. Here is a snippet for the two slices: tortuga-4frcm and tortuga-sxqh9. The program logs the type of event (e.g. MODIFIED) and what changed (i.e. it does a diff between the old and new object). Note that this is not a onetime thing, the churn continues for prolonged periods. The vast majority of VMs being shuffled are not going through any state transition. They are just sitting idle. 

```
2025/07/24 22:34:09 EVENT [endpointslices]: Type: MODIFIED | Name: **tortuga-4frcm** | Change: endpoint count changed from 35 to 34, added IP: 10.42.59.53 (ready: true), added IP: 10.42.1.234 (ready: true), added IP: 10.42.4.164 (ready: true), added IP: 10.42.12.42 (ready: true), added IP: 10.42.61.70 (ready: true), added IP: 10.42.3.147 (ready: true), added IP: 10.42.3.145 (ready: true), added IP: 10.42.19.136 (ready: true), added IP: 10.42.31.23 (ready: true), added IP: 10.42.57.87 (ready: true), added IP: 10.42.57.84 (ready: true), added IP: 10.42.32.34 (ready: true), added IP: 10.42.8.181 (ready: true), added IP: 10.42.17.106 (ready: true), added IP: 10.42.7.57 (ready: true), added IP: 10.42.34.117 (ready: true), added IP: 10.42.56.229 (ready: true), added IP: 10.42.61.66 (ready: true), added IP: 10.42.9.155 (ready: true), added IP: 10.42.28.211 (ready: true), added IP: 10.42.10.143 (ready: true), added IP: 10.42.34.113 (ready: true), added IP: 10.42.27.21 (ready: true), added IP: 10.42.19.131 (ready: true), added IP: 10.42.44.221 (ready: true), added IP: 10.42.11.121 (ready: true), added IP: 10.42.15.113 (ready: true), added IP: 10.42.11.119 (ready: true), added IP: 10.42.11.115 (ready: true), added IP: 10.42.17.110 (ready: true), added IP: 10.42.60.77 (ready: true), removed IP: 10.42.3.148, removed IP: 10.42.58.38, removed IP: 10.42.27.22, removed IP: 10.42.60.71, removed IP: 10.42.59.46, removed IP: 10.42.44.225, removed IP: 10.42.12.44, removed IP: 10.42.61.71, removed IP: 10.42.43.235, removed IP: 10.42.4.160, removed IP: 10.42.9.157, removed IP: 10.42.60.74, removed IP: 10.42.40.131, removed IP: 10.42.8.178, removed IP: 10.42.35.149, removed IP: 10.42.32.31, removed IP: 10.42.10.142, removed IP: 10.42.60.76, removed IP: 10.42.7.61, removed IP: 10.42.61.68, removed IP: 10.42.6.208, removed IP: 10.42.60.75, removed IP: 10.42.16.91, removed IP: 10.42.12.45, removed IP: 10.42.44.203, removed IP: 10.42.31.28, removed IP: 10.42.2.56, removed IP: 10.42.6.207, removed IP: 10.42.27.28, removed IP: 10.42.28.210, removed IP: 10.42.3.143, removed IP: 10.42.35.147

2025/07/24 22:34:09 EVENT [endpointslices]: Type: MODIFIED | Name: **tortuga-sxqh9** | Change: added IP: 10.42.59.49 (ready: true), added IP: 10.42.35.146 (ready: true), added IP: 10.42.28.206 (ready: true), added IP: 10.42.57.88 (ready: true), added IP: 10.42.40.131 (ready: true), added IP: 10.42.4.159 (ready: true), added IP: 10.42.6.212 (ready: true), added IP: 10.42.44.224 (ready: true), added IP: 10.42.28.208 (ready: true), added IP: 10.42.2.28 (ready: true), added IP: 10.42.15.110 (ready: true), added IP: 10.42.35.147 (ready: true), added IP: 10.42.35.149 (ready: true), added IP: 10.42.31.22 (ready: true), added IP: 10.42.7.59 (ready: true), added IP: 10.42.60.72 (ready: true), added IP: 10.42.60.76 (ready: true), added IP: 10.42.56.232 (ready: true), added IP: 10.42.32.30 (ready: true), added IP: 10.42.16.91 (ready: true), added IP: 10.42.10.142 (ready: true), added IP: 10.42.19.132 (ready: true), added IP: 10.42.16.81 (ready: true), added IP: 10.42.9.132 (ready: true), added IP: 10.42.30.175 (ready: true), added IP: 10.42.60.80 (ready: true), added IP: 10.42.2.52 (ready: true), added IP: 10.42.56.237 (ready: true), added IP: 10.42.56.236 (ready: true), added IP: 10.42.28.210 (ready: true), added IP: 10.42.40.129 (ready: true), added IP: 10.42.34.114 (ready: true), added IP: 10.42.27.26 (ready: true), added IP: 10.42.61.71 (ready: true), added IP: 10.42.27.27 (ready: true), added IP: 10.42.35.151 (ready: true), added IP: 10.42.12.41 (ready: true), added IP: 10.42.44.203 (ready: true), added IP: 10.42.9.159 (ready: true), added IP: 10.42.8.178 (ready: true), added IP: 10.42.32.38 (ready: true), added IP: 10.42.59.46 (ready: true), added IP: 10.42.6.208 (ready: true), added IP: 10.42.7.60 (ready: true), added IP: 10.42.43.235 (ready: true), added IP: 10.42.7.61 (ready: true), added IP: 10.42.16.89 (ready: true), added IP: 10.42.60.74 (ready: true), added IP: 10.42.3.144 (ready: true), added IP: 10.42.30.174 (ready: true), added IP: 10.42.3.141 (ready: true), added IP: 10.42.59.51 (ready: true), added IP: 10.42.27.22 (ready: true), added IP: 10.42.34.118 (ready: true), added IP: 10.42.19.139 (ready: true), added IP: 10.42.32.31 (ready: true), added IP: 10.42.56.239 (ready: true), added IP: 10.42.32.35 (ready: true), added IP: 10.42.58.38 (ready: true), added IP: 10.42.17.112 (ready: true), added IP: 10.42.61.69 (ready: true), added IP: 10.42.2.56 (ready: true), removed IP: 10.42.11.121, removed IP: 10.42.59.53, removed IP: 10.42.7.56, removed IP: 10.42.19.141, removed IP: 10.42.4.166, removed IP: 10.42.35.150, removed IP: 10.42.28.213, removed IP: 10.42.19.140, removed IP: 10.42.11.117, removed IP: 10.42.12.39, removed IP: 10.42.10.141, removed IP: 10.42.34.109, removed IP: 10.42.61.64, removed IP: 10.42.27.29, removed IP: 10.42.56.235, removed IP: 10.42.16.82, removed IP: 10.42.7.58, removed IP: 10.42.16.86, removed IP: 10.42.17.110, removed IP: 10.42.34.108, removed IP: 10.42.10.143, removed IP: 10.42.12.43, removed IP: 10.42.59.47, removed IP: 10.42.15.111, removed IP: 10.42.27.23, removed IP: 10.42.34.110, removed IP: 10.42.19.136, removed IP: 10.42.27.25, removed IP: 10.42.8.180, removed IP: 10.42.16.76, removed IP: 10.42.6.204, removed IP: 10.42.8.177, removed IP: 10.42.40.132, removed IP: 10.42.60.79, removed IP: 10.42.59.52, removed IP: 10.42.43.238, removed IP: 10.42.44.221, removed IP: 10.42.7.54, removed IP: 10.42.12.38, removed IP: 10.42.16.90, removed IP: 10.42.9.155, removed IP: 10.42.28.211, removed IP: 10.42.7.57, removed IP: 10.42.4.165, removed IP: 10.42.8.182, removed IP: 10.42.6.209, removed IP: 10.42.9.160, removed IP: 10.42.34.113, removed IP: 10.42.4.164, removed IP: 10.42.7.62, removed IP: 10.42.1.231, removed IP: 10.42.11.116, removed IP: 10.42.12.40, removed IP: 10.42.43.236, removed IP: 10.42.40.133, removed IP: 10.42.15.115, removed IP: 10.42.27.21, removed IP: 10.42.2.55, removed IP: 10.42.17.105, removed IP: 10.42.56.240, removed IP: 10.42.32.34, removed IP: 10.42.44.222
```

Some additional information that may be helpful:
1. We noticed that the control plane was complaining with these errors:

```
Aug 06 22:20:32 node-name-foo k3s[2663]: time="2025-08-06T22:20:32Z" level=warning msg="Proxy error: write failed: io: read/write on closed pipe"
Aug 06 22:20:42node-name-foo k3s[2663]: I0806 22:20:42.363009    2663 endpointslice_controller.go:337] "Error syncing endpoint slices for service, retrying" key="jenkins/tortuga" err="EndpointSlice informer cache is out of date"
```

2. We are running a single control-plane k3s cluster in our lab. It's certainly possible that this node when under load cannot send out events fast enough to all services (like coredns). However, we would expect that the system should continue to resolve valid VMs to their IPs. 

How does this tie into the coredns issue of returning NXDOMAIN for valid VMs?

Coredns also uses endpointslice objects. One theory would be that there is a significant time gap between the slice update events. Using the example above, an update where one slice removes a (valid) VM is received and then after a delay of several seconds, the update for the second slice, which includes the previously removed VM, is received. Between these two updates, coredns returns NXDOMAIN for the valid VM. 

Other thoughts:
1. The moving of endpoints between slices seems racy to me. If there is significant delay between propagating updates of the two slices, then services like coredns will have temporary inconsistencies. 
2. Is there a corner case where the endpointslice controller frequently balances endpoints across slices? Can this balancing be disabled?
3. Should coredns (and other consumers of endpointslice) be enhanced to detect stale cache entries?  
4. Is this expected behavior? I hope not. 

### What did you expect to happen?

We expect that coredns should reliably resolve IPs for VMs/Pods that are healthy.

### How can we reproduce it (as minimally and precisely as possible)?

Unfortunately, this is not easy to produce, primarily because the issue seems to arise when the control-plane is under load and is having a hard time sending updates to all informers. 

### Anything else we need to know?

Our current workaround has been to increase endpoints pers slice from 100 (default) to 200. This has mitigated the issue for the time being, but we would like to scale to 500+ endpoints. Single slice approach may not be appropriate at that point. 


### Kubernetes version

<details>

```console
$ kubectl version
Client Version: v1.33.2
Kustomize Version: v5.6.0
Server Version: v1.30.5+k3s1
WARNING: version difference between client (1.33) and server (1.30) exceeds the supported minor version skew of +/-1
```

</details>


### Cloud provider

<details>
Bare metal.
</details>


### OS version

<details>

```console
# On Linux:
$ cat /etc/os-release
PRETTY_NAME="Ubuntu 24.04 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04 LTS (Noble Numbat)"
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
Linux node-name-foo 6.8.0-45-generic #45-Ubuntu SMP PREEMPT_DYNAMIC Fri Aug 30 12:02:04 UTC 2024 x86_64 x86_64 x86_64 GNU/Linux
```

</details>


### Install tools

<details>
k3s
</details>


### Container runtime (CRI) and version (if applicable)

<details>
containerd
</details>


### Related plugins (CNI, CSI, ...) and versions (if applicable)

<details>
CNI: flannel
</details>

**Repository:** `kubernetes/kubernetes`
**Base commit:** `99a2c5c6346ad84976f9bda40034670a97950f24`

## Hints

/sig network

1.30 is out of support upstream: https://kubernetes.io/releases/

Is this reproducible on a supported version? We may have already fixed this.

> Unfortunately, this is not easy to produce, primarily because the issue seems to arise when the control-plane is under load and is having a hard time sending updates to all informers.

May be possible to replicate under synthetic load with a toy cluster?

We'll look into upgrading to 1.31. 
I did look through issues and commit history for endpointslice controller. Didn't see anything related, but I could be wrong. https://github.com/kubernetes/endpointslice


I think Ben's comment is probably key: Can you reproduce this:

* Current version of Kubernetes? One thing to note is that 1.31 is also quite old, which means that you may want to consider upgrading to a more recent version.
* If the behavior is localized to EndpointSlice controller, a smaller repro may be possible with a Kind cluster or other minimal setup with a large number of endpoints (> 100). I know that we put explicit logic in the EndpointSlice controller for some amount of hysteresis to avoid churn, but there may be a case where this is not working as intended.

Ok. I'll come back with an update once we have done the upgrade. 

/triage needs-information

/close

please reopen once you have the information requested

Thanks

@aojea: Closing this issue.

<details>

In response to [this](https://github.com/kubernetes/kubernetes/issues/133474#issuecomment-3335001341):

>/close
>
>please reopen once you have the information requested
>
>Thanks


Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>
