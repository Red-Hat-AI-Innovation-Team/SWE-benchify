Version `v1.74.2` Doesn't allow empty `Node ID` value anymore
### What version of gRPC are you using?
`v1.74.2`
### What version of Go are you using (`go version`)?

go `1.24.4`

### What operating system (Linux, Windows, …) and version?
Linux

### What did you do?
We are using an empty Node ID value in our bootstrap file!

### What did you expect to see?
Until `v1.73.0`, this was working as expected.

### What did you see instead?
`xdsclient: node ID is empty (check that target is valid)"`

**Repository:** `grpc/grpc-go`
**Base commit:** `9186ebd774370e3b3232d1b202914ff8fc2c56d6`

## Hints

It seems to be an artifact of https://github.com/grpc/grpc-go/pull/8391 

https://www.envoyproxy.io/docs/envoy/latest/api-v3/config/core/v3/base.proto#envoy-v3-api-msg-config-core-v3-node envoy docs seem a bit ambiguous  around allowing `""` but from a quickly playing around with envoy config it seems valid

cc @purnesh42H 

Hi @shadialtarsha and @davinci26, thanks for reporting this. We recently made significant refactorings to the xDS client used within gRPC, with the goal of eventually providing the xDS client as a standalone library for use outside of gRPC. These changes were intended to be transparent to users. However, it seems that requiring a node ID may be backward-incompatible. I checked [gRPC C++](https://github.com/grpc/grpc/blob/2ca9ac63ced7b77cf0eb885276fbedec1ab0bd10/src/core/xds/grpc/xds_bootstrap_grpc.cc#L67), and it also treats the node ID as optional.

@easwars, can you confirm if we should make the xDS node ID optional again?

> with the goal of eventually providing the xDS client as a standalone library for use outside of gRPC

Ohhhh that is very very exciting :D we would absolutely use this for other protocols as well like doing XDS for rest HTTP and even storage protocols

keep us posted we are happy to try out stuff :D 

@arjan-bal : Thanks for checking with the C++ team. If node ID is optional there, it should be optional in Go as well.

@davinci26 : Would you mind sending us a PR for this? I'd be happy to review it.
