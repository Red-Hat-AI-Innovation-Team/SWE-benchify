KEP-5304: DecodeMetadataFromStream silently skips malformed metadata for registered API versions
## What happened?
devicemetadata.DecodeMetadataFromStream in staging/src/k8s.io/dynamic-resource-allocation/devicemetadata/decode.go treats all per-entry decode failures the same way: it records them in an internal skippedErrors slice and continues to the next stream entry. The only signal bubbled out is a single aggregated error, and only when no entry in the stream decoded successfully.

The practical consequence: if a DRA driver writes a metadata stream whose registered entry (e.g. metadata.resource.k8s.io/v1alpha1) is malformed, and the stream happens to contain any decodable entry after it, the malformed entry is silently swallowed. The caller, if a producer-side bug has occurred.

## What you expected to happen

The decoder should distinguish between two failure modes:

1. Unknown apiVersion (producer is ahead of consumer): silent skip is correct — this is the forward-compatibility contract the JSON-stream design exists to support.
2. Registered apiVersion but decode/convert fails (malformed object, missing kind, missing apiVersion, wrong field shape, etc.): this is a producer bug. It should be surfaced to the caller even when decoding succeeds via a later stream entry, so the operator can diagnose and fix the driver.

As a tertiary concern, apiVersion-less entries are currently lumped into the silent-skip bucket, which is also wrong: they indicate malformed metadata, not forward compatibility.

## How to reproduce

Will provide a unit test that re-creates this error easily.

More discussion here: https://github.com/kubevirt/kubevirt/pull/17028#discussion_r3106470305

**Repository:** `kubernetes/kubernetes`
**Base commit:** `d92b8fe8f29dfa96d514977244985b2dcd701515`
