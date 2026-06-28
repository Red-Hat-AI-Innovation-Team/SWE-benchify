Kubelet shutdown manager not properly initialized due to race condition in systemd-logind configuration reloading
### What happened?

Observed error log 
`
kubelet.go:1667] "Failed to start node shutdown manager" err="node shutdown manager was unable to update logind InhibitDelayMaxSec to 30s (ShutdownGracePeriod), current value of InhibitDelayMaxSec (5s) is less than requested ShutdownGracePeriod"
`

And the shutdown inhibitor is not registered to the system so shutdown manager would not be in effect.

The bug seems to be a race condition between systemd-logind config reloading and getting the updated `InhibitDelayMaxSec`. The root cause is the reload command is signaled to systemd-logind with no waiting until the reload is complete.

I am thinking a low cost fix,  rather than properly implementing something to get the reload completion signal, is to just backoff wait up to 5 retries to get the new `InhibitDelayUSec` value


### What did you expect to happen?

Kubelet shutdown manager should work properly

### How can we reproduce it (as minimally and precisely as possible)?

Wrote a program trying to reproduce it

```go
package main

import (
        "fmt"
        "math/rand"
        "os"

        "github.com/godbus/dbus/v5"
)

const (
        logindConfDir = "/etc/systemd/logind.conf.d/"
        tempConfFile  = logindConfDir + "99-test-inhibit-delay.conf"
        logindService = "org.freedesktop.login1"
        logindObject  = dbus.ObjectPath("/org/freedesktop/login1")
)

func main() {
        // This program must be run as root to modify systemd config and call D-Bus methods.
        if os.Geteuid() != 0 {
                fmt.Println("This program must be run as root (sudo).")
                os.Exit(1)
        }

        neg, total := 0, 100000
        for i := 0; i < total; i++ {
                if test() {
                        neg++
                }
                if i%500 == 0 {
                        fmt.Printf("Tested %d times, reproduced the bug %d times\n", i, neg)
                }
        }
        fmt.Printf("Tested %d times, reproduced the bug %d times", total, neg)
}

func test() bool {
        newInhibitDelaySec := rand.Intn(100) + 15
        conn, err := dbus.SystemBus()
        if err != nil {
                fmt.Printf("Failed to connect to system D-Bus: %v\n", err)
                os.Exit(1)
        }
        defer conn.Close()

        if err := os.MkdirAll(logindConfDir, 0755); err != nil {
                fmt.Printf("Failed to create logind.conf.d directory: %v\n", err)
                os.Exit(1)
        }

        confContent := fmt.Sprintf("[Login]\nInhibitDelayMaxSec=%ds\n", newInhibitDelaySec)
        err = os.WriteFile(tempConfFile, []byte(confContent), 0644)
        if err != nil {
                fmt.Printf("Failed to write temporary config file: %v\n", err)
                os.Exit(1)
        }
        defer os.Remove(tempConfFile)

        obj0 := conn.Object("org.freedesktop.systemd1", dbus.ObjectPath("/org/freedesktop/systemd1"))
        obj1 := conn.Object(logindService, logindObject)

        call := obj0.Call("org.freedesktop.systemd1.Manager.KillUnit", 0, "systemd-logind.service", "all", 1)
        if call.Err != nil {
                fmt.Printf("Reload call failed: %v\n", call.Err)
                os.Exit(1)
        }
        variant, err := obj1.GetProperty("org.freedesktop.login1.Manager.InhibitDelayMaxUSec")
        if err != nil {
                fmt.Printf("Failed to get property: %v\n", err)
                os.Exit(1)
        }

        updatedInhibitDelayUSec, ok := variant.Value().(uint64)
        if !ok {
                fmt.Println("Failed to assert property type to uint64.")
                os.Exit(1)
        }

        expectedUSec := uint64(newInhibitDelaySec * 1_000_000)

        return expectedUSec != updatedInhibitDelayUSec
}
```

, which had pretty low reproduction rate (`Tested 80500 times, reproduced the bug 1 times/Tested 257500 times, reproduced the bug 4 times`) but on real cases, it should significantly higher because the kubelet is started during OS boot period and a lot of churns on systemd so the logind reload takes more time to take effect. 

### Anything else we need to know?

_No response_

### Kubernetes version

<details>
1.33 and earlier
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
**Base commit:** `39b160f10cf0a71954b58dcc60a013ff7faa34fa`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig node
