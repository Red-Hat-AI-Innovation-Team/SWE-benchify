#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo 'diff --git a/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement_test.go b/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement_test.go
index a14319e537358..b93771633f1ae 100644
--- a/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement_test.go
+++ b/staging/src/k8s.io/apiserver/pkg/server/options/api_enablement_test.go
@@ -17,11 +17,19 @@ limitations under the License.
 package options
 
 import (
+	"bytes"
 	"strings"
 	"testing"
 
+	"k8s.io/apimachinery/pkg/runtime/schema"
 	utilerrors "k8s.io/apimachinery/pkg/util/errors"
+	"k8s.io/apimachinery/pkg/util/version"
+	apimachineryversion "k8s.io/apimachinery/pkg/version"
+	"k8s.io/apiserver/pkg/server"
+	serverstore "k8s.io/apiserver/pkg/server/storage"
 	cliflag "k8s.io/component-base/cli/flag"
+	"k8s.io/component-base/compatibility"
+	"k8s.io/klog/v2"
 )
 
 type fakeGroupRegistry struct{}
@@ -77,3 +85,292 @@ func TestAPIEnablementOptionsValidate(t *testing.T) {
 		})
 	}
 }
+
+type fakeGroupVersionRegistry struct {
+	versions []schema.GroupVersion
+}
+
+func (f fakeGroupVersionRegistry) PrioritizedVersionsAllGroups() []schema.GroupVersion {
+	return f.versions
+}
+
+func (f fakeGroupVersionRegistry) PrioritizedVersionsForGroup(group string) []schema.GroupVersion {
+	var result []schema.GroupVersion
+	for _, gv := range f.versions {
+		if gv.Group == group {
+			result = append(result, gv)
+		}
+	}
+	return result
+}
+
+func (f fakeGroupVersionRegistry) IsGroupRegistered(group string) bool {
+	for _, gv := range f.versions {
+		if gv.Group == group {
+			return true
+		}
+	}
+	return false
+}
+
+func (f fakeGroupVersionRegistry) IsVersionRegistered(gv schema.GroupVersion) bool {
+	for _, version := range f.versions {
+		if version == gv {
+			return true
+		}
+	}
+	return false
+}
+
+func (f fakeGroupVersionRegistry) GroupVersions() []schema.GroupVersion {
+	return f.versions
+}
+
+type fakeEffectiveVersion struct {
+	binaryVersion    *version.Version
+	emulationVersion *version.Version
+}
+
+func (f fakeEffectiveVersion) BinaryVersion() *version.Version {
+	return f.binaryVersion
+}
+
+func (f fakeEffectiveVersion) EmulationVersion() *version.Version {
+	return f.emulationVersion
+}
+
+func (f fakeEffectiveVersion) MinCompatibilityVersion() *version.Version {
+	return nil
+}
+
+func (f fakeEffectiveVersion) EqualTo(other compatibility.EffectiveVersion) bool {
+	return f.binaryVersion.EqualTo(other.BinaryVersion()) && f.emulationVersion.EqualTo(other.EmulationVersion())
+}
+
+func (f fakeEffectiveVersion) String() string {
+	return "fake"
+}
+
+func (f fakeEffectiveVersion) Info() *apimachineryversion.Info {
+	return nil
+}
+
+func (f fakeEffectiveVersion) AllowedEmulationVersionRange() string {
+	return "fake range"
+}
+
+func (f fakeEffectiveVersion) AllowedMinCompatibilityVersionRange() string {
+	return "fake range"
+}
+
+func (f fakeEffectiveVersion) Validate() []error {
+	return nil
+}
+
+func TestAPIEnablementOptionsApplyToVersionComparison(t *testing.T) {
+	// Helper function to capture klog output
+	captureKlogOutput := func(fn func()) string {
+		var buf bytes.Buffer
+		klog.SetOutput(&buf)
+		klog.LogToStderr(false)
+		defer func() {
+			klog.SetOutput(nil)
+			klog.LogToStderr(true)
+		}()
+
+		fn()
+		klog.Flush()
+		return buf.String()
+	}
+
+	testCases := []struct {
+		name                 string
+		binaryVersion        string
+		emulationVersion     string
+		alphaAPIsPresent     bool
+		versionEnabled       bool
+		expectWarning        bool
+		expectWarningContent string
+	}{
+		{
+			name:             "same major.minor versions, different patch - no warning",
+			binaryVersion:    "1.34.1",
+			emulationVersion: "1.34.0",
+			alphaAPIsPresent: true,
+			versionEnabled:   true,
+			expectWarning:    false,
+		},
+		{
+			name:             "same major.minor versions, no patch in emulation - no warning",
+			binaryVersion:    "1.34.1",
+			emulationVersion: "1.34",
+			alphaAPIsPresent: true,
+			versionEnabled:   true,
+			expectWarning:    false,
+		},
+		{
+			name:             "identical versions - no warning",
+			binaryVersion:    "1.34.1",
+			emulationVersion: "1.34.1",
+			alphaAPIsPresent: true,
+			versionEnabled:   true,
+			expectWarning:    false,
+		},
+		{
+			name:             "different major versions but not enabled - should not warn",
+			binaryVersion:    "1.34.1",
+			emulationVersion: "1.33.0",
+			alphaAPIsPresent: true,
+			expectWarning:    false,
+		},
+		{
+			name:                 "different major versions - should warn",
+			binaryVersion:        "1.34.1",
+			emulationVersion:     "1.33.0",
+			alphaAPIsPresent:     true,
+			expectWarning:        true,
+			versionEnabled:       true,
+			expectWarningContent: "alpha api enabled with emulated version",
+		},
+		{
+			name:                 "different minor versions - should warn",
+			binaryVersion:        "1.34.1",
+			emulationVersion:     "1.33.5",
+			alphaAPIsPresent:     true,
+			expectWarning:        true,
+			versionEnabled:       true,
+			expectWarningContent: "alpha api enabled with emulated version",
+		},
+		{
+			name:             "different major.minor but no alpha APIs - no warning",
+			binaryVersion:    "1.34.1",
+			emulationVersion: "1.33.0",
+			alphaAPIsPresent: false,
+			expectWarning:    false,
+			versionEnabled:   true,
+		},
+		{
+			name:             "same major.minor with alpha APIs - no warning",
+			binaryVersion:    "1.34.5",
+			emulationVersion: "1.34.0",
+			alphaAPIsPresent: true,
+			expectWarning:    false,
+			versionEnabled:   true,
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			binaryVer := version.MustParse(tc.binaryVersion)
+			emulationVer := version.MustParse(tc.emulationVersion)
+
+			effectiveVersion := fakeEffectiveVersion{
+				binaryVersion:    binaryVer,
+				emulationVersion: emulationVer,
+			}
+
+			var versions []schema.GroupVersion
+			if tc.alphaAPIsPresent {
+				versions = []schema.GroupVersion{
+					{Group: "rbac.authorization.k8s.io", Version: "v1alpha1"},
+					{Group: "storage.k8s.io", Version: "v1alpha1"},
+				}
+			} else {
+				versions = []schema.GroupVersion{
+					{Group: "rbac.authorization.k8s.io", Version: "v1"},
+					{Group: "storage.k8s.io", Version: "v1beta1"},
+				}
+			}
+
+			registry := fakeGroupVersionRegistry{versions: versions}
+			config := &server.Config{EffectiveVersion: effectiveVersion}
+			options := &APIEnablementOptions{RuntimeConfig: make(cliflag.ConfigurationMap)}
+
+			// Enable the API
+			resourceConfig := serverstore.NewResourceConfig()
+			if tc.versionEnabled {
+				resourceConfig.ExplicitGroupVersionConfigs[schema.GroupVersion{Group: "rbac.authorization.k8s.io", Version: "v1alpha1"}] = true
+			}
+
+			// Capture log output during ApplyTo execution
+			logOutput := captureKlogOutput(func() {
+				err := options.ApplyTo(config, resourceConfig, registry)
+				if err != nil {
+					t.Errorf("ApplyTo failed: %v", err)
+				}
+			})
+
+			// Verify warning expectations
+			if tc.expectWarning {
+				if !strings.Contains(logOutput, tc.expectWarningContent) {
+					t.Errorf("Expected warning containing '"'"'%s'"'"', but got log output: %s", tc.expectWarningContent, logOutput)
+				}
+				if !strings.Contains(logOutput, "W") { // klog warning prefix
+					t.Errorf("Expected warning log level, but got log output: %s", logOutput)
+				}
+			} else if strings.Contains(logOutput, "alpha api enabled") {
+				t.Errorf("Expected no warning, but got log output: %s", logOutput)
+			}
+		})
+	}
+}
+
+func TestAPIEnablementOptionsApplyToErrorCases(t *testing.T) {
+	// Create a default effective version for test configs
+	defaultEffectiveVersion := fakeEffectiveVersion{
+		binaryVersion:    version.MustParse("1.34.0"),
+		emulationVersion: version.MustParse("1.34.0"),
+	}
+
+	testCases := []struct {
+		name          string
+		options       *APIEnablementOptions
+		config        *server.Config
+		expectError   bool
+		errorContains string
+	}{
+		{
+			name:    "nil options should not error",
+			options: nil,
+			config: &server.Config{
+				EffectiveVersion: defaultEffectiveVersion,
+			},
+			expectError: false,
+		},
+		{
+			name: "invalid runtime config value should error",
+			options: &APIEnablementOptions{
+				RuntimeConfig: cliflag.ConfigurationMap{
+					"api/all": "invalid-value", // Must be "true" or "false"
+				},
+			},
+			config: &server.Config{
+				EffectiveVersion: defaultEffectiveVersion,
+			},
+			expectError:   true,
+			errorContains: "invalid value",
+		},
+	}
+
+	for _, tc := range testCases {
+		t.Run(tc.name, func(t *testing.T) {
+			registry := fakeGroupVersionRegistry{versions: []schema.GroupVersion{
+				{Group: "rbac.authorization.k8s.io", Version: "v1"},
+			}}
+
+			err := tc.options.ApplyTo(tc.config, serverstore.NewResourceConfig(), registry)
+
+			if tc.expectError {
+				if err == nil {
+					t.Errorf("Expected error but got none")
+				} else if tc.errorContains != "" && !strings.Contains(err.Error(), tc.errorContains) {
+					t.Errorf("Expected error containing '"'"'%s'"'"', but got: %v", tc.errorContains, err)
+				}
+			} else {
+				if err != nil {
+					t.Errorf("Expected no error but got: %v", err)
+				}
+			}
+		})
+	}
+}
' > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
make test 2>&1 | tee /tmp/test_output.txt || true

# ── Embedded F2P checker (multi-format) ──────────────────────
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys, os

OUTPUT_FORMAT = os.environ.get("TEST_OUTPUT_FORMAT", "go-json")
f2p = ["TestAPIEnablementOptionsApplyToVersionComparison"]

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
