#!/usr/bin/env bash
set -euo pipefail

# Collect oracle validation results from K8s job annotations.
#
# Usage:
#   bash k8s/collect-oracle-results.sh
#   bash k8s/collect-oracle-results.sh --output data/oracle-results.jsonl

NAMESPACE="${NAMESPACE:-swebenchify}"
OUTPUT="${1:-}"

oc project "$NAMESPACE" 2>/dev/null || true

# Get all oracle validation jobs
jobs=$(oc get jobs -l component=oracle-validation -n "$NAMESPACE" \
  -o json 2>/dev/null)

total=$(echo "$jobs" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('items',[])))")
completed=$(echo "$jobs" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(sum(1 for j in d.get('items',[]) if any(c.get('type')=='Complete' and c.get('status')=='True' for c in j.get('status',{}).get('conditions',[]))))
")
failed=$(echo "$jobs" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(sum(1 for j in d.get('items',[]) if any(c.get('type')=='Failed' and c.get('status')=='True' for c in j.get('status',{}).get('conditions',[]))))
")
running=$((total - completed - failed))

echo "=== Oracle Validation Results ==="
echo "Total: $total | Completed: $completed | Failed: $failed | Running: $running"
echo

# Parse results from annotations
echo "$jobs" | python3 -c "
import json, sys

data = json.load(sys.stdin)
items = data.get('items', [])

passed = 0
total_with_result = 0
failed_tasks = []
error_tasks = []
output_lines = []

for job in items:
    name = job['metadata']['name']
    annotations = job['metadata'].get('annotations', {})
    result_str = annotations.get('result', '')

    if not result_str:
        continue

    try:
        result = json.loads(result_str)
    except json.JSONDecodeError:
        error_tasks.append(name)
        continue

    total_with_result += 1
    reward = result.get('reward', 0)
    instance_id = result.get('instance_id', name)
    output_lines.append(json.dumps(result))

    if reward == 1:
        passed += 1
    else:
        failed_tasks.append(instance_id)

if total_with_result > 0:
    rate = passed / total_with_result * 100
    print(f'Oracle pass rate: {passed}/{total_with_result} ({rate:.1f}%)')
else:
    print('No results collected yet')

if failed_tasks:
    print(f'\nFailed tasks ({len(failed_tasks)}):')
    for t in sorted(failed_tasks):
        print(f'  - {t}')

if error_tasks:
    print(f'\nParse errors ({len(error_tasks)}):')
    for t in error_tasks:
        print(f'  - {t}')

# Write output file if requested
output_path = '$OUTPUT'
if output_path and output_path != '--output':
    with open(output_path, 'w') as f:
        for line in output_lines:
            f.write(line + '\n')
    print(f'\nResults written to {output_path}')
"
