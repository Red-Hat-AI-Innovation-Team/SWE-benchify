#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/dynamic-resource-allocation/api/conversion_test.go b/staging/src/k8s.io/dynamic-resource-allocation/api/conversion_test.go
new file mode 100644
index 0000000000000..1311081f38210
--- /dev/null
+++ b/staging/src/k8s.io/dynamic-resource-allocation/api/conversion_test.go
@@ -0,0 +1,119 @@
+/*
+Copyright 2025 The Kubernetes Authors.
+
+Licensed under the Apache License, Version 2.0 (the "License");
+you may not use this file except in compliance with the License.
+You may obtain a copy of the License at
+
+    http://www.apache.org/licenses/LICENSE-2.0
+
+Unless required by applicable law or agreed to in writing, software
+distributed under the License is distributed on an "AS IS" BASIS,
+WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
+See the License for the specific language governing permissions and
+limitations under the License.
+*/
+
+package api
+
+import (
+	"testing"
+
+	"github.com/google/go-cmp/cmp"
+
+	resourceapi "k8s.io/api/resource/v1"
+	"k8s.io/apimachinery/pkg/api/apitesting/fuzzer"
+	apiequality "k8s.io/apimachinery/pkg/api/equality"
+	"k8s.io/apimachinery/pkg/runtime"
+	"k8s.io/apimachinery/pkg/runtime/serializer"
+	apitest "k8s.io/dynamic-resource-allocation/api/internal/test"
+	"sigs.k8s.io/randfill"
+)
+
+// v1FillFuncs returns custom fill functions needed for v1 types where
+// the default random filling would create objects that cannot round-trip
+// due to pointer-to-value conversions in the internal api types.
+func v1FillFuncs(codecs serializer.CodecFactory) []interface{} {
+	return []interface{}{
+		// The internal api types use bool instead of *bool for AllNodes.
+		// Converting nil -> false -> &false means nil doesn'"'"'t round-trip.
+		// Ensure AllNodes is always non-nil to avoid this.
+		func(s *resourceapi.ResourceSliceSpec, c randfill.Continue) {
+			c.FillNoCustom(s)
+			if s.AllNodes == nil {
+				s.AllNodes = new(bool)
+			}
+		},
+		// The internal api types use bool instead of *bool for BindsToNode.
+		// Converting nil -> false -> &false means nil doesn'"'"'t round-trip.
+		// Ensure BindsToNode is always non-nil to avoid this.
+		func(d *resourceapi.Device, c randfill.Continue) {
+			c.FillNoCustom(d)
+			if d.BindsToNode == nil {
+				d.BindsToNode = new(bool)
+			}
+		},
+	}
+}
+
+// TestConversionRoundTrip verifies that the conversion code for the internal
+// DRA API correctly round-trips between v1 and the internal api types.
+// For v1 -> api -> v1, the conversion should be lossless.
+//
+// api -> v1 -> api is not lossless because of
+// additional fields in the internal representation.
+// Those would get lost during conversion.
+// But this doesn'"'"'t matter because in practice,
+// the internal representation is never converted back,
+// therefore this direction is not tested.
+func TestConversionRoundTrip(t *testing.T) {
+	scheme := runtime.NewScheme()
+	if err := resourceapi.AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+	if err := AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+
+	filler := apitest.NewFiller(t, scheme, fuzzer.FuzzerFuncs(v1FillFuncs))
+
+	testCases := []struct {
+		name   string
+		v1Type func() runtime.Object
+		apiNew func() interface{}
+	}{
+		{
+			name:   "ResourceSlice",
+			v1Type: func() runtime.Object { return &resourceapi.ResourceSlice{} },
+			apiNew: func() interface{} { return &ResourceSlice{} },
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			for i := range apitest.FuzzIterations {
+				// Create and fuzz v1 object.
+				v1Obj := tc.v1Type()
+				filler.Fill(v1Obj)
+
+				// Convert v1 -> api.
+				apiObj := tc.apiNew()
+				if err := scheme.Convert(v1Obj, apiObj, nil); err != nil {
+					t.Fatalf("iteration %d: v1 -> api: %v", i, err)
+				}
+
+				// Convert api -> v1 (round-trip).
+				roundTripped := tc.v1Type()
+				if err := scheme.Convert(apiObj, roundTripped, nil); err != nil {
+					t.Fatalf("iteration %d: api -> v1: %v", i, err)
+				}
+
+				// The round-tripped object must be equal to the original.
+				if !apiequality.Semantic.DeepEqual(v1Obj, roundTripped) {
+					t.Errorf("iteration %d: round-trip v1 -> api -> v1 failed\ndiff (-want +got):\n%s",
+						i, cmp.Diff(v1Obj, roundTripped))
+				}
+			}
+		})
+	}
+}
diff --git a/staging/src/k8s.io/dynamic-resource-allocation/api/internal/test/roundtrip.go b/staging/src/k8s.io/dynamic-resource-allocation/api/internal/test/roundtrip.go
new file mode 100644
index 0000000000000..bceeeb66d9ac1
--- /dev/null
+++ b/staging/src/k8s.io/dynamic-resource-allocation/api/internal/test/roundtrip.go
@@ -0,0 +1,113 @@
+/*
+Copyright The Kubernetes Authors.
+
+Licensed under the Apache License, Version 2.0 (the "License");
+you may not use this file except in compliance with the License.
+You may obtain a copy of the License at
+
+    http://www.apache.org/licenses/LICENSE-2.0
+
+Unless required by applicable law or agreed to in writing, software
+distributed under the License is distributed on an "AS IS" BASIS,
+WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
+See the License for the specific language governing permissions and
+limitations under the License.
+*/
+
+// Package test provides test utilities for DRA API conversion testing.
+package test
+
+import (
+	"math/rand"
+	"strings"
+	"testing"
+
+	"github.com/google/go-cmp/cmp"
+
+	"k8s.io/apimachinery/pkg/api/apitesting/fuzzer"
+	apiequality "k8s.io/apimachinery/pkg/api/equality"
+	genericfuzzer "k8s.io/apimachinery/pkg/apis/meta/fuzzer"
+	"k8s.io/apimachinery/pkg/runtime"
+	"k8s.io/apimachinery/pkg/runtime/schema"
+	"k8s.io/apimachinery/pkg/runtime/serializer"
+	"sigs.k8s.io/randfill"
+)
+
+// FuzzIterations is the number of fuzz iterations to run for each type.
+const FuzzIterations = 100
+
+// NewFiller creates a new randfill.Filler for fuzzing objects.
+func NewFiller(t *testing.T, scheme *runtime.Scheme, customFuncs fuzzer.FuzzerFuncs) *randfill.Filler {
+	seed := rand.Int63()
+	t.Logf("Using seed: %d", seed)
+	codecs := serializer.NewCodecFactory(scheme)
+	return fuzzer.FuzzerFor(
+		fuzzer.MergeFuzzerFuncs(genericfuzzer.Funcs, customFuncs),
+		rand.NewSource(seed),
+		codecs,
+	)
+}
+
+// ConversionRoundTrip tests that all non-list types in srcGV can be converted
+// to dstGV and back without loss of information.
+func ConversionRoundTrip(t *testing.T, scheme *runtime.Scheme, filler *randfill.Filler, srcGV, dstGV schema.GroupVersion) {
+	t.Helper()
+
+	tested := 0
+	for kind := range scheme.KnownTypes(srcGV) {
+		if strings.HasSuffix(kind, "List") {
+			continue
+		}
+
+		srcGVK := srcGV.WithKind(kind)
+		dstGVK := dstGV.WithKind(kind)
+		if _, err := scheme.New(dstGVK); err != nil {
+			// Kind does not exist in the destination version.
+			continue
+		}
+
+		tested++
+		t.Run(kind, func(t *testing.T) {
+			for i := range FuzzIterations {
+				// Create and fuzz source object.
+				srcObj, err := scheme.New(srcGVK)
+				if err != nil {
+					t.Fatal(err)
+				}
+				filler.Fill(srcObj)
+
+				// Convert source -> destination.
+				dstObj, err := scheme.New(dstGVK)
+				if err != nil {
+					t.Fatal(err)
+				}
+				if err := scheme.Convert(srcObj, dstObj, nil); err != nil {
+					t.Fatalf("iteration %d: %v -> %v: %v", i, srcGVK, dstGVK, err)
+				}
+
+				// Convert destination -> source (round-trip).
+				roundTripped, err := scheme.New(srcGVK)
+				if err != nil {
+					t.Fatal(err)
+				}
+				if err := scheme.Convert(dstObj, roundTripped, nil); err != nil {
+					t.Fatalf("iteration %d: %v -> %v: %v", i, dstGVK, srcGVK, err)
+				}
+
+				// The round-tripped object must be equal to the original.
+				// Use Semantic.DeepEqual which treats nil and empty
+				// slices/maps as equivalent.
+				if !apiequality.Semantic.DeepEqual(srcObj, roundTripped) {
+					t.Errorf("iteration %d: round-trip %v -> %v -> %v failed\ndiff (-want +got):\n%s",
+						i, srcGVK, dstGVK, srcGVK,
+						cmp.Diff(srcObj, roundTripped))
+				}
+			}
+		})
+	}
+
+	if tested == 0 {
+		t.Fatal("no types were tested")
+	}
+	t.Logf("tested %d types for %v <-> %v", tested, srcGV, dstGV)
+}
diff --git a/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion_test.go b/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion_test.go
index 85a53bef08a50..b5fcfcc01c34a 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion_test.go
+++ b/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta1/conversion_test.go
@@ -24,7 +24,12 @@ import (
 	"github.com/google/go-cmp/cmp"
 	resourceapi "k8s.io/api/resource/v1"
 	resourcev1beta1 "k8s.io/api/resource/v1beta1"
+	"k8s.io/apimachinery/pkg/api/apitesting/fuzzer"
 	"k8s.io/apimachinery/pkg/runtime"
+	"k8s.io/apimachinery/pkg/runtime/schema"
+	"k8s.io/apimachinery/pkg/runtime/serializer"
+	apitest "k8s.io/dynamic-resource-allocation/api/internal/test"
+	"sigs.k8s.io/randfill"
 )
 
 func TestConversion(t *testing.T) {
@@ -331,3 +336,49 @@ func TestConversion(t *testing.T) {
 	}
 
 }
+
+// v1beta1FillFuncs returns custom fill functions needed for v1beta1
+// types where the default random filling would create objects that
+// cannot round-trip due to structural differences between versions.
+func v1beta1FillFuncs(codecs serializer.CodecFactory) []interface{} {
+	return []interface{}{
+		// v1 -> v1beta1 conversion always creates a non-nil Basic,
+		// so we must ensure it is non-nil in the source object too.
+		func(d *resourcev1beta1.Device, c randfill.Continue) {
+			c.FillNoCustom(d)
+			if d.Basic == nil {
+				d.Basic = &resourcev1beta1.BasicDevice{}
+			}
+		},
+	}
+}
+
+// TestConversionRoundTrip verifies that the automatically generated and
+// hand-written conversion code for the DRA API correctly round-trips
+// between v1beta1 and v1. For each non-list type registered in v1beta1,
+// a fuzzed object is converted to v1 and back, and the result must be
+// equal to the original.
+//
+// Note that this only covers conversion code which is called
+// while converting the top-level API types. Types embedded
+// inside those have their own conversion functions, but those
+// are not necessarily called.
+func TestConversionRoundTrip(t *testing.T) {
+	scheme := runtime.NewScheme()
+	if err := resourceapi.AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+	if err := resourcev1beta1.AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+	if err := AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+
+	filler := apitest.NewFiller(t, scheme, fuzzer.FuzzerFuncs(v1beta1FillFuncs))
+
+	apitest.ConversionRoundTrip(t, scheme, filler,
+		schema.GroupVersion{Group: resourcev1beta1.GroupName, Version: "v1beta1"},
+		schema.GroupVersion{Group: resourceapi.GroupName, Version: "v1"},
+	)
+}
diff --git a/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta2/conversion_test.go b/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta2/conversion_test.go
index 480476948e63a..ea89918261913 100644
--- a/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta2/conversion_test.go
+++ b/staging/src/k8s.io/dynamic-resource-allocation/api/v1beta2/conversion_test.go
@@ -25,6 +25,8 @@ import (
 	resourceapi "k8s.io/api/resource/v1"
 	resourcev1beta2 "k8s.io/api/resource/v1beta2"
 	"k8s.io/apimachinery/pkg/runtime"
+	"k8s.io/apimachinery/pkg/runtime/schema"
+	apitest "k8s.io/dynamic-resource-allocation/api/internal/test"
 )
 
 func TestConversion(t *testing.T) {
@@ -335,3 +337,33 @@ func TestConversion(t *testing.T) {
 	}
 
 }
+
+// TestConversionRoundTrip verifies that the automatically generated and
+// hand-written conversion code for the DRA API correctly round-trips
+// between v1beta2 and v1. For each non-list type registered in v1beta2,
+// a fuzzed object is converted to v1 and back, and the result must be
+// equal to the original.
+//
+// Note that this only covers conversion code which is called
+// while converting the top-level API types. Types embedded
+// inside those have their own conversion functions, but those
+// are not necessarily called.
+func TestConversionRoundTrip(t *testing.T) {
+	scheme := runtime.NewScheme()
+	if err := resourceapi.AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+	if err := resourcev1beta2.AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+	if err := AddToScheme(scheme); err != nil {
+		t.Fatal(err)
+	}
+
+	filler := apitest.NewFiller(t, scheme, nil)
+
+	apitest.ConversionRoundTrip(t, scheme, filler,
+		schema.GroupVersion{Group: resourcev1beta2.GroupName, Version: "v1beta2"},
+		schema.GroupVersion{Group: resourceapi.GroupName, Version: "v1"},
+	)
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestConversionRoundTrip"]

def parse_go_json(text):
    results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action in ("pass", "fail", "skip"):
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[action]
            results[test] = status
            # Also store bare name (no subtest suffix)
            results[test.split("/")[0]] = status
    return results

def parse_pytest_verbose(text):
    results = {}
    for line in text.splitlines():
        m = re.match(r"^(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if m:
            test_id = m.group(1).strip()
            status = {"PASSED": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped"}[m.group(2)]
            results[test_id] = status
    return results

PARSERS = {
    "go-json": parse_go_json,
    "pytest-verbose": parse_pytest_verbose,
}

with open("/tmp/test_output.txt") as f:
    raw = f.read()

parser_fn = PARSERS.get(OUTPUT_FORMAT)
if not parser_fn:
    print(f"Unknown test output format: {OUTPUT_FORMAT}")
    sys.exit(1)

passed = parser_fn(raw)

def test_matches(expected, actual_results):
    """Check if an expected test ID matches any result in the parsed output."""
    if expected in actual_results and actual_results[expected] == "passed":
        return True
    # Try bare name match (strip subtest suffix for Go, method match for pytest)
    bare = expected.split("/")[0]
    if bare in actual_results and actual_results[bare] == "passed":
        return True
    # Suffix match: the last component of "::" or "/" delimited IDs
    last = expected.split("::")[-1] if "::" in expected else expected.split("/")[-1]
    for k, v in actual_results.items():
        k_last = k.split("::")[-1] if "::" in k else k.split("/")[-1]
        if k_last == last and v == "passed":
            return True
    return False

all_pass = all(test_matches(t, passed) for t in f2p)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if not test_matches(t, passed)]
    print(f"NOT RESOLVED: {len(missing)}/{len(f2p)} tests still failing: {missing}")
    sys.exit(1)
PYEOF

TEST_OUTPUT_FORMAT="go-json" python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${exit_code}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${exit_code}"
