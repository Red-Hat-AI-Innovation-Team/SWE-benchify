xds: build the interceptor chain for routes with cluster_specifier_plugins as well
We are currently building the interceptor chain only for routes that point to weighted_clusters. See: https://github.com/grpc/grpc-go/blob/c7ec4d9ae3281bc57a8adce59b572e56965fb728/internal/xds/resolver/xds_resolver.go#L374

And not doing so in the case where the route points to a cluster_specifier_plugin. See: https://github.com/grpc/grpc-go/blob/c7ec4d9ae3281bc57a8adce59b572e56965fb728/internal/xds/resolver/xds_resolver.go#L365

This needs to be fixed. Interceptor chain needs to be build for all cluster types. As part of this change, we also need to add a test to ensure that filters work properly for routes that match to cluster_specifier_plugins.

**Repository:** `grpc/grpc-go`
**Base commit:** `39f16539d2463c05d52b4c44137831fd5f73f7d9`
