ContainerRestartRules: exitCodes.values validation incorrectly reports "bytes" instead of "items"
### What happened?

When a container's `restartPolicyRules[].exitCodes.values` length exceeds 255 elements, the validation error message says:

```bash
containers[0].restartPolicyRules[0].exitCodes.values: Too long: may not be more than 255 bytes
```

The validation uses field.TooLong (byte length checks) instead of field.TooMany (slice length checks).

### What did you expect to happen?

The field is []int32, and the length limit is at most 255 elements, not 255 bytes.
If I am not wrong, I think the correct error message should be:
```bash
containers[0].restartPolicyRules[0].exitCodes.values: Too many: 256: must have at most 255 items
```

### How can we reproduce it (as minimally and precisely as possible)?

https://github.com/kubernetes/kubernetes/blob/master/pkg/apis/core/validation/validation.go#L3716

### Anything else we need to know?

_No response_

### Kubernetes version

v1.35

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
**Base commit:** `9d685325edee86b4ee2fce090257a08801e3883e`

## Hints

/assign
/sig node
