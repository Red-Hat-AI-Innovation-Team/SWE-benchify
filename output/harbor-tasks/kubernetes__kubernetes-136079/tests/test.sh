#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/pkg/apis/resource/validation/validation_resourceslice_test.go b/pkg/apis/resource/validation/validation_resourceslice_test.go
index 7a867b6bdd538..b9160a356df1b 100644
--- a/pkg/apis/resource/validation/validation_resourceslice_test.go
+++ b/pkg/apis/resource/validation/validation_resourceslice_test.go
@@ -390,7 +390,7 @@ func TestValidateResourceSlice(t *testing.T) {
 		},
 		"bad-attribute": {
 			wantFailures: field.ErrorList{
-				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes").Key(badName), badName, "a valid C identifier must start with alphabetic character or '"'"'_'"'"', followed by a string of alphanumeric characters or '"'"'_'"'"' (e.g. '"'"'my_name'"'"',  or '"'"'MY_NAME'"'"',  or '"'"'MyName'"'"', regex used for validation is '"'"'[A-Za-z_][A-Za-z0-9_]*'"'"')"),
+				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes"), badName, "a valid C identifier must start with alphabetic character or '"'"'_'"'"', followed by a string of alphanumeric characters or '"'"'_'"'"' (e.g. '"'"'my_name'"'"',  or '"'"'MY_NAME'"'"',  or '"'"'MyName'"'"', regex used for validation is '"'"'[A-Za-z_][A-Za-z0-9_]*'"'"')"),
 				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes").Key(badName), "", "exactly one value must be specified").MarkCoveredByDeclarative(),
 				field.Invalid(field.NewPath("spec", "devices").Index(2).Child("attributes").Key(goodName), resourceapi.DeviceAttribute{StringValue: ptr.To("x"), VersionValue: ptr.To("1.2.3")}, "exactly one value must be specified").MarkCoveredByDeclarative(),
 				field.Invalid(field.NewPath("spec", "devices").Index(3).Child("attributes").Key(goodName).Child("version"), strings.Repeat("x", resourceapi.DeviceAttributeMaxValueLength+1), "must be a string compatible with semver.org spec 2.0.0"),
@@ -426,8 +426,8 @@ func TestValidateResourceSlice(t *testing.T) {
 		},
 		"bad-attribute-c-identifier": {
 			wantFailures: field.ErrorList{
-				field.TooLongMaxLength(field.NewPath("spec", "devices").Index(1).Child("attributes").Key(strings.Repeat(".", resourceapi.DeviceMaxIDLength+1)), strings.Repeat(".", resourceapi.DeviceMaxIDLength+1), resourceapi.DeviceMaxIDLength),
-				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes").Key(strings.Repeat(".", resourceapi.DeviceMaxIDLength+1)), strings.Repeat(".", resourceapi.DeviceMaxIDLength+1), "a valid C identifier must start with alphabetic character or '"'"'_'"'"', followed by a string of alphanumeric characters or '"'"'_'"'"' (e.g. '"'"'my_name'"'"',  or '"'"'MY_NAME'"'"',  or '"'"'MyName'"'"', regex used for validation is '"'"'[A-Za-z_][A-Za-z0-9_]*'"'"')"),
+				field.TooLongMaxLength(field.NewPath("spec", "devices").Index(1).Child("attributes"), strings.Repeat(".", resourceapi.DeviceMaxIDLength+1), resourceapi.DeviceMaxIDLength),
+				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes"), strings.Repeat(".", resourceapi.DeviceMaxIDLength+1), "a valid C identifier must start with alphabetic character or '"'"'_'"'"', followed by a string of alphanumeric characters or '"'"'_'"'"' (e.g. '"'"'my_name'"'"',  or '"'"'MY_NAME'"'"',  or '"'"'MyName'"'"', regex used for validation is '"'"'[A-Za-z_][A-Za-z0-9_]*'"'"')"),
 			},
 			slice: func() *resourceapi.ResourceSlice {
 				slice := testResourceSlice(goodName, goodName, goodName, 2)
@@ -439,8 +439,8 @@ func TestValidateResourceSlice(t *testing.T) {
 		},
 		"bad-attribute-domain": {
 			wantFailures: field.ErrorList{
-				field.TooLong(field.NewPath("spec", "devices").Index(1).Child("attributes").Key(strings.Repeat("_", resourceapi.DeviceMaxDomainLength+1)+"/y"), strings.Repeat("_", resourceapi.DeviceMaxDomainLength+1), resourceapi.DeviceMaxDomainLength),
-				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes").Key(strings.Repeat("_", resourceapi.DeviceMaxDomainLength+1)+"/y"), strings.Repeat("_", resourceapi.DeviceMaxDomainLength+1), "a lowercase RFC 1123 subdomain must consist of lower case alphanumeric characters, '"'"'-'"'"' or '"'"'.'"'"', and must start and end with an alphanumeric character (e.g. '"'"'example.com'"'"', regex used for validation is '"'"'[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*'"'"')"),
+				field.TooLong(field.NewPath("spec", "devices").Index(1).Child("attributes"), strings.Repeat("_", resourceapi.DeviceMaxDomainLength+1), resourceapi.DeviceMaxDomainLength),
+				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes"), strings.Repeat("_", resourceapi.DeviceMaxDomainLength+1), "a lowercase RFC 1123 subdomain must consist of lower case alphanumeric characters, '"'"'-'"'"' or '"'"'.'"'"', and must start and end with an alphanumeric character (e.g. '"'"'example.com'"'"', regex used for validation is '"'"'[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*'"'"')"),
 			},
 			slice: func() *resourceapi.ResourceSlice {
 				slice := testResourceSlice(goodName, goodName, goodName, 2)
@@ -452,8 +452,8 @@ func TestValidateResourceSlice(t *testing.T) {
 		},
 		"bad-key-too-long": {
 			wantFailures: field.ErrorList{
-				field.TooLong(field.NewPath("spec", "devices").Index(1).Child("attributes").Key("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx...xxxxxxxxxxxx/yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"), strings.Repeat("x", resourceapi.DeviceMaxDomainLength+1), resourceapi.DeviceMaxDomainLength),
-				field.TooLongMaxLength(field.NewPath("spec", "devices").Index(1).Child("attributes").Key("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx...xxxxxxxxxxxx/yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"), strings.Repeat("y", resourceapi.DeviceMaxIDLength+1), resourceapi.DeviceMaxIDLength),
+				field.TooLong(field.NewPath("spec", "devices").Index(1).Child("attributes"), strings.Repeat("x", resourceapi.DeviceMaxDomainLength+1), resourceapi.DeviceMaxDomainLength),
+				field.TooLongMaxLength(field.NewPath("spec", "devices").Index(1).Child("attributes"), strings.Repeat("y", resourceapi.DeviceMaxIDLength+1), resourceapi.DeviceMaxIDLength),
 			},
 			slice: func() *resourceapi.ResourceSlice {
 				slice := testResourceSlice(goodName, goodName, goodName, 2)
@@ -465,8 +465,8 @@ func TestValidateResourceSlice(t *testing.T) {
 		},
 		"bad-attribute-empty-domain-and-c-identifier": {
 			wantFailures: field.ErrorList{
-				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes").Key("/"), "", "the domain must not be empty"),
-				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes").Key("/"), "", "the name must not be empty"),
+				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes"), "", "the domain must not be empty"),
+				field.Invalid(field.NewPath("spec", "devices").Index(1).Child("attributes"), "", "the name must not be empty"),
 			},
 			slice: func() *resourceapi.ResourceSlice {
 				slice := testResourceSlice(goodName, goodName, goodName, 2)
@@ -746,7 +746,7 @@ func TestValidateResourceSlice(t *testing.T) {
 		},
 		"bad-countername-shared-counters": {
 			wantFailures: field.ErrorList{
-				field.Invalid(field.NewPath("spec", "sharedCounters").Index(0).Child("counters").Key(badName), badName, "a lowercase RFC 1123 label must consist of lower case alphanumeric characters or '"'"'-'"'"', and must start and end with an alphanumeric character (e.g. '"'"'my-name'"'"',  or '"'"'123-abc'"'"', regex used for validation is '"'"'[a-z0-9]([-a-z0-9]*[a-z0-9])?'"'"')"),
+				field.Invalid(field.NewPath("spec", "sharedCounters").Index(0).Child("counters"), badName, "a lowercase RFC 1123 label must consist of lower case alphanumeric characters or '"'"'-'"'"', and must start and end with an alphanumeric character (e.g. '"'"'my-name'"'"',  or '"'"'123-abc'"'"', regex used for validation is '"'"'[a-z0-9]([-a-z0-9]*[a-z0-9])?'"'"')").MarkCoveredByDeclarative(),
 			},
 			slice: func() *resourceapi.ResourceSlice {
 				slice := testResourceSliceWithSharedCounters(goodName, goodName, driverName, 1)
diff --git a/pkg/registry/resource/resourceslice/declarative_validation_test.go b/pkg/registry/resource/resourceslice/declarative_validation_test.go
index ae0886f2297ab..5e0916721b763 100644
--- a/pkg/registry/resource/resourceslice/declarative_validation_test.go
+++ b/pkg/registry/resource/resourceslice/declarative_validation_test.go
@@ -194,6 +194,26 @@ func TestDeclarativeValidate(t *testing.T) {
 						field.Duplicate(field.NewPath("spec").Child("devices").Index(0).Child("consumesCounters").Index(1), "duplicate-key"),
 					},
 				},
+				// spec.sharedCounters.counters
+				"invalid: shared counter key with uppercase": {
+					input: mkResourceSliceWithSharedCounters(tweakSharedCounter(counters("InvalidKey"))),
+					expectedErrs: field.ErrorList{
+						field.Invalid(field.NewPath("spec", "sharedCounters").Index(0).Child("counters"), "InvalidKey", "").WithOrigin("format=k8s-short-name"),
+					},
+				},
+				"valid: shared counter key": {
+					input: mkResourceSliceWithSharedCounters(tweakSharedCounter(counters("valid-key"))),
+				},
+				// spec.devices.consumesCounters.counters
+				"invalid: device counter key with uppercase": {
+					input: mkResourceSliceWithDevices(tweakDeviceCounter(counters("InvalidKey"))),
+					expectedErrs: field.ErrorList{
+						field.Invalid(field.NewPath("spec", "devices").Index(0).Child("consumesCounters").Index(0).Child("counters"), "InvalidKey", "").WithOrigin("format=k8s-short-name"),
+					},
+				},
+				"valid: device counter key": {
+					input: mkResourceSliceWithDevices(tweakDeviceCounter(counters("valid-key"))),
+				},
 				// TODO: Add more test cases
 			}
 
@@ -370,8 +390,41 @@ func TestDeclarativeValidateUpdate(t *testing.T) {
 						field.Duplicate(field.NewPath("spec").Child("devices").Index(0).Child("consumesCounters").Index(1), "duplicate-key"),
 					},
 				},
+				// spec.sharedCounters.counters
+				"invalid update: shared counter key with uppercase": {
+					old:    mkResourceSliceWithSharedCounters(),
+					update: mkResourceSliceWithSharedCounters(tweakSharedCounter(counters("InvalidKey"))),
+					expectedErrs: field.ErrorList{
+						field.Invalid(field.NewPath("spec", "sharedCounters").Index(0).Child("counters"), "InvalidKey", "").WithOrigin("format=k8s-short-name"),
+					},
+				},
+				// spec.sharedCounters.counters: nil -> invalid
+				"invalid update: shared counter key nil to invalid": {
+					old:    mkResourceSliceWithSharedCounters(tweakSharedCounter(nil)),
+					update: mkResourceSliceWithSharedCounters(tweakSharedCounter(counters("InvalidKey"))),
+					expectedErrs: field.ErrorList{
+						field.Invalid(field.NewPath("spec", "sharedCounters").Index(0).Child("counters"), "InvalidKey", "").WithOrigin("format=k8s-short-name"),
+					},
+				},
+				// spec.devices.consumesCounters.counters
+				"invalid update: device counter key with uppercase": {
+					old:    mkResourceSliceWithDevices(),
+					update: mkResourceSliceWithDevices(tweakDeviceCounter(counters("InvalidKey"))),
+					expectedErrs: field.ErrorList{
+						field.Invalid(field.NewPath("spec", "devices").Index(0).Child("consumesCounters").Index(0).Child("counters"), "InvalidKey", "").WithOrigin("format=k8s-short-name"),
+					},
+				},
+				// spec.devices.consumesCounters.counters: nil -> invalid
+				"invalid update: device counter key nil to invalid": {
+					old:    mkResourceSliceWithDevices(tweakDeviceCounter(nil)),
+					update: mkResourceSliceWithDevices(tweakDeviceCounter(counters("InvalidKey"))),
+					expectedErrs: field.ErrorList{
+						field.Invalid(field.NewPath("spec", "devices").Index(0).Child("consumesCounters").Index(0).Child("counters"), "InvalidKey", "").WithOrigin("format=k8s-short-name"),
+					},
+				},
 			}
 			for k, tc := range testCases {
+
 				t.Run(k, func(t *testing.T) {
 					tc.old.ResourceVersion = "1"
 					tc.update.ResourceVersion = "1"
@@ -540,3 +593,31 @@ func tweakDeviceConsumesCountersCounterSetName(counterSets ...string) func(*reso
 		rs.Spec.Devices[0].ConsumesCounters = consumesCounters
 	}
 }
+
+func tweakSharedCounter(counters map[string]resource.Counter) func(*resource.ResourceSlice) {
+	return func(rs *resource.ResourceSlice) {
+		rs.Spec.SharedCounters = []resource.CounterSet{
+			{
+				Name:     "shared-counter-set",
+				Counters: counters,
+			},
+		}
+	}
+}
+
+func tweakDeviceCounter(counters map[string]resource.Counter) func(*resource.ResourceSlice) {
+	return func(rs *resource.ResourceSlice) {
+		rs.Spec.Devices[0].ConsumesCounters = []resource.DeviceCounterConsumption{
+			{
+				CounterSet: "shared-counter-set",
+				Counters:   counters,
+			},
+		}
+	}
+}
+
+func counters(key string) map[string]resource.Counter {
+	return map[string]resource.Counter{
+		key: {},
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 ./pkg/apis/resource/validation/... ./pkg/registry/resource/resourceslice/... 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestDeclarativeValidate", "TestDeclarativeValidateUpdate", "TestValidateResourceSlice"]

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
