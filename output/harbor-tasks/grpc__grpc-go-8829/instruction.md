xds/googlec2p: cleanup in googlec2p resolver.
The xdsclient package contains legacy support for a "fallback" bootstrap configuration, which was originally used by the googlec2p resolver via `SetFallbackBootstrapConfig`.
This global fallback mechanism has been superseded by the changes in PR #8648. The googlec2p resolver now uses this new, explicit approach to create a xdsClient in googlec2p resolver.

To simplify the API and prevent confusion, the legacy fallback logic should be removed.
- Deprecate and remove the exported `xdsclient.SetFallbackBootstrapConfig` function.
- Remove the internal `fallbackConfig` field from the `xdsclient.Pool` and all associated logic that applies it during client creation.

**Repository:** `grpc/grpc-go`
**Base commit:** `6601041bab5b34e51cbb5d58666659e0b17bf6b0`
