ValidatingAdmissionPolicy causes kube-controller-manager to panic
### What happened?

I have a validatingadmissionpolicy which appears to cause kube-controller-manager to panic on a nil pointer dereference. This is the backtrace from the log:

```
E0123 12:33:29.270214       1 panic.go:262] "Observed a panic" panic="runtime error: invalid memory address or nil pointer dereference" panicGoValue="\"invalid memory address or nil pointer dereference\"" stacktrace=<
        goroutine 3482 [running]:
        k8s.io/apimachinery/pkg/util/runtime.logPanic({0x38d6f30, 0x56429e0}, {0x2e10c60, 0x55c0f10})
                k8s.io/apimachinery/pkg/util/runtime/runtime.go:107 +0xbc
        k8s.io/apimachinery/pkg/util/runtime.handleCrash({0x38d6f30, 0x56429e0}, {0x2e10c60, 0x55c0f10}, {0x56429e0, 0x0, 0x10000000043ab05?})
                k8s.io/apimachinery/pkg/util/runtime/runtime.go:82 +0x5e
        k8s.io/apimachinery/pkg/util/runtime.HandleCrash({0x0, 0x0, 0xc00378d180?})
                k8s.io/apimachinery/pkg/util/runtime/runtime.go:59 +0x108
        panic({0x2e10c60?, 0x55c0f10?})
                runtime/panic.go:791 +0x132
        k8s.io/apiserver/pkg/cel.(*DeclType).IsObject(...)
                k8s.io/apiserver/pkg/cel/types.go:223
        k8s.io/apiserver/pkg/cel.(*DeclType).MaybeAssignTypeName(0x0, {0xc003f12b90?, 0x1?})
                k8s.io/apiserver/pkg/cel/types.go:117 +0x2d
        k8s.io/apiserver/pkg/admission/plugin/policy/validating.(*TypeChecker).declType(0xc001c46ba0?, {{0xc0029b4930, 0x11}, {0xc000daabb7, 0x7}, {0xc002887a38, 0x6}})
                k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go:253 +0x146
        k8s.io/apiserver/pkg/admission/plugin/policy/validating.(*TypeChecker).CreateContext(0xc001c46ba0, 0xc002bf8000)
                k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go:149 +0x18f
        k8s.io/apiserver/pkg/admission/plugin/policy/validating.(*TypeChecker).Check(0xc001c46ba0, 0xc002bf8000)
                k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go:111 +0x32
        k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus.(*Controller).reconcile(0xc001c58380, {0x38d70d8, 0xc001c0ee40}, 0xc002bf8000)
                k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus/controller.go:147 +0x78
        k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus.(*Controller).processNextWorkItem.func1(0xc001c58380, {0xc0029a5cc0, 0x19}, {0x38d70d8, 0xc001c0ee40})
                k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus/controller.go:126 +0xa5
        k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus.(*Controller).processNextWorkItem(0xc001c58380, {0x38d70d8, 0xc001c0ee40})
                k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus/controller.go:127 +0xbe
        k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus.(*Controller).runWorker(...)
                k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus/controller.go:106
        k8s.io/apimachinery/pkg/util/wait.JitterUntilWithContext.func1()
                k8s.io/apimachinery/pkg/util/wait/backoff.go:259 +0x1f
        k8s.io/apimachinery/pkg/util/wait.BackoffUntil.func1(0x30?)
                k8s.io/apimachinery/pkg/util/wait/backoff.go:226 +0x33
        k8s.io/apimachinery/pkg/util/wait.BackoffUntil(0xc0023dff70, {0x389ae40, 0xc003f0fce0}, 0x1, 0xc000118e00)
                k8s.io/apimachinery/pkg/util/wait/backoff.go:227 +0xaf
        k8s.io/apimachinery/pkg/util/wait.JitterUntil(0xc002914770, 0x3b9aca00, 0x0, 0x1, 0xc000118e00)
                k8s.io/apimachinery/pkg/util/wait/backoff.go:204 +0x7f
        k8s.io/apimachinery/pkg/util/wait.JitterUntilWithContext({0x38d70d8, 0xc001c0ee40}, 0xc00208a090, 0x3b9aca00, 0x0, 0x1)
                k8s.io/apimachinery/pkg/util/wait/backoff.go:259 +0x87
        k8s.io/apimachinery/pkg/util/wait.UntilWithContext(...)
                k8s.io/apimachinery/pkg/util/wait/backoff.go:170
        created by k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus.(*Controller).Run in goroutine 857
                k8s.io/kubernetes/pkg/controller/validatingadmissionpolicystatus/controller.go:63 +0xf8
 >
panic: runtime error: invalid memory address or nil pointer dereference [recovered]
        panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x28 pc=0x1d4060d]
```



### What did you expect to happen?

Not to crash. By looks of it, `common.SchemaDeclType()` can (and does) return nil, and the caller at https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go#L247 doesn't check the value before using it.

### How can we reproduce it (as minimally and precisely as possible)?

Probably x-kubernetes-preserve-unknown-fields extension is causing this.

### Anything else we need to know?

_No response_

### Kubernetes version

<details>

```console
v1.32.9
```

</details>


### Cloud provider

<details>
N/A
</details>


### OS version

<details>

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
**Base commit:** `598922db7562f628fb51ef1db6d3ccb6003369a4`

## Hints

/assign @ermias19

I’ve been able to analyze the panic further and it appears to be caused by
`common.SchemaDeclType()` returning nil, which is then dereferenced in
(*DeclType).MaybeAssignTypeName without a nil check.

This seems to be in the API machinery / admission / CEL type checking path.
I believe this belongs to SIG API Machinery.

I’m planning to work on a fix with a regression test if there are no objections.

`/sig api-machinery`
