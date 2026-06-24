The IP address allocated by the IPv6 service exceeds the serviceCIDR range.
### What happened?

My serviceCIDR is fd22:ff0::/64, but the IP address assigned to me is fd22:fef:ffff:ffff:849a:c484:cfc0:71a8, which is not within the allowed range of the serviceCIDR.

### What did you expect to happen?

The allocated service IP address is within the serviceCIDR range.

### How can we reproduce it (as minimally and precisely as possible)?

Set serviceCIDR to fd22:ff0::/64 and create the service multiple times.

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
$ kubectl version
1.34.1
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
**Base commit:** `96c9676d7c1cfbf485447d00402c0e6b64431f62`
