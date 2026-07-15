#!/bin/bash
set -uxo pipefail

cd /testbed

# Ensure git trusts the directory
git config --global --add safe.directory /testbed

# Capture agent's patch before any reverts (for analysis/dashboard)
git diff HEAD > /logs/artifacts/candidate_patch.diff 2>/dev/null || true
git diff HEAD --stat > /logs/artifacts/patch_stat.txt 2>/dev/null || true

# --- Phase 1: Apply test patch ---
# Anti-reward-hacking: revert ONLY test file modifications
# Agent's source changes are preserved for grading
python3 -c "
import re, subprocess, os
test_patterns = [
    r'(^|/)tests?/', r'(^|/)e2e/', r'(^|/)testing/', r'(^|/)testdata/',
    r'(^|/)src/test/', r'_test\\.go$', r'_test\\.rs$', r'_test\\.py$',
    r'^test_', r'\\.test\\.', r'_spec\\.', r'\\.spec\\.',
    r'conftest\\.py$',
]
combined = re.compile('|'.join(test_patterns))
result = subprocess.run(['git', 'diff', '--name-only'], capture_output=True, text=True)
for f in result.stdout.strip().split('\\n'):
    if f and combined.search(f):
        subprocess.run(['git', 'checkout', '--', f], capture_output=True)
result = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard'], capture_output=True, text=True)
for f in result.stdout.strip().split('\\n'):
    if f and combined.search(f):
        try: os.remove(f)
        except: pass
" 2>/dev/null || true

# Apply test patch (adds/modifies test files that catch the bug)
git apply --3way /tests/test.patch 2>&1 || git apply /tests/test.patch 2>&1 || {
    echo "TEST_PATCH_APPLY_FAILED"
    echo 0 > /logs/verifier/reward.txt
    exit 0
}

# --- Phase 2: Run tests ---
# Capture test output for grading
LOG_FILE=$(mktemp)

echo '>>>>> Start Test Output'

(cd admin && go test -v -count=1 ./test) > "$LOG_FILE" 2>&1 || true
cat "$LOG_FILE"

echo '>>>>> End Test Output'

# --- Phase 3: Grade results ---
# Parse go test output and check against expected FAIL_TO_PASS / PASS_TO_PASS
# Load expected test lists from config.json
FAIL_TO_PASS=$(python3 -c "
import json, sys
with open('/tests/config.json') as f:
    cfg = json.load(f)
f2p = cfg.get('FAIL_TO_PASS', '[]')
if isinstance(f2p, str):
    f2p = json.loads(f2p)
print('\n'.join(f2p))
" 2>/dev/null || true)

PASS_TO_PASS=$(python3 -c "
import json, sys
with open('/tests/config.json') as f:
    cfg = json.load(f)
p2p = cfg.get('PASS_TO_PASS', '[]')
if isinstance(p2p, str):
    p2p = json.loads(p2p)
print('\n'.join(p2p))
" 2>/dev/null || true)

# Check if all FAIL_TO_PASS tests now pass
ALL_PASS=1
while IFS= read -r test_name; do
    [ -z "$test_name" ] && continue
    if ! grep -q -- "--- PASS: ${test_name}" "$LOG_FILE" 2>/dev/null; then
        ALL_PASS=0
        break
    fi
done <<< "$FAIL_TO_PASS"

# Check if all PASS_TO_PASS tests still pass
while IFS= read -r test_name; do
    [ -z "$test_name" ] && continue
    if grep -q -- "--- FAIL: ${test_name}" "$LOG_FILE" 2>/dev/null; then
        ALL_PASS=0
        break
    fi
done <<< "$PASS_TO_PASS"

# Write reward
if [ $ALL_PASS -eq 1 ] && [ -n "$FAIL_TO_PASS" ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

# Write detailed report
python3 -c "
import json, re

log = open('$LOG_FILE').read()

# Parse go test verbose output
results = {}
for line in log.split('\n'):
    m = re.match(r'--- (PASS|FAIL): (\S+)', line)
    if m:
        results[m.group(2)] = m.group(1).lower()

report = {
    'test_results': results,
    'total_tests': len(results),
    'passed': sum(1 for v in results.values() if v == 'pass'),
    'failed': sum(1 for v in results.values() if v == 'fail'),
}
with open('/logs/verifier/report.json', 'w') as f:
    json.dump(report, f, indent=2)
" 2>/dev/null || true

exit 0
