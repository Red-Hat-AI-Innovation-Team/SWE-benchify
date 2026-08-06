#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-swebenchify}"
YAML="k8s/judge-evasion-job.yaml"

# Prepare samples: N per group, randomized
N="${N:-200}"
SEED="${SEED:-42}"

echo "=== Preparing judge evasion samples (N=$N per group, seed=$SEED) ==="

python3 -c "
import json, random, sys

N = int(sys.argv[1])
seed = int(sys.argv[2])
random.seed(seed)

groups = {
    'swebenchify': ('data/swebenchify-all.jsonl', 'synthetic'),
    'swesmith': ('data/swesmith-combined-200.jsonl', 'synthetic'),
    'real-python': ('data/swebench-verified-sample-100.jsonl', 'real'),
    'real-go': ('output/instances-go.jsonl', 'real'),
}

for group, (path, gt) in groups.items():
    instances = []
    for line in open(path):
        line = line.strip()
        if not line: continue
        try: instances.append(json.loads(line))
        except: continue
    random.shuffle(instances)
    sampled = instances[:N]
    out_path = f'/tmp/judge-{group}.jsonl'
    with open(out_path, 'w') as f:
        for inst in sampled:
            f.write(json.dumps(inst) + '\n')
    print(f'{group}: {len(sampled)} instances (gt={gt})', file=sys.stderr)
" "$N" "$SEED"

oc project "$NAMESPACE" 2>/dev/null || true

# Get existing judge jobs to skip
existing=$(oc get jobs -l component=judge-evasion -n "$NAMESPACE" \
  --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

launched=0

for group in swebenchify swesmith real-python real-go; do
    case "$group" in
        swebenchify|swesmith) GROUND_TRUTH="synthetic" ;;
        real-python|real-go) GROUND_TRUTH="real" ;;
    esac

    while IFS= read -r line; do
        [ -z "$line" ] && continue

        instance_id=$(echo "$line" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('instance_id',''))" 2>/dev/null) || continue
        [ -z "$instance_id" ] && continue

        instance_slug=$(echo "$instance_id" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sed 's/[^a-z0-9-]/-/g' | cut -c1-50 | sed 's/-$//')
        job_name="judge-${group}-${instance_slug}"

        if echo "$existing" | grep -q "^${job_name}$"; then
            continue
        fi

        tmpf=$(mktemp)
        echo "$line" > "$tmpf"
        cm_name="judge-input-${group}-${instance_slug}"
        oc delete configmap "$cm_name" -n "$NAMESPACE" &>/dev/null || true
        oc create configmap "$cm_name" --from-file="instance.jsonl=$tmpf" -n "$NAMESPACE" 2>/dev/null || { rm -f "$tmpf"; continue; }
        rm -f "$tmpf"

        export GROUP="$group" GROUND_TRUTH="$GROUND_TRUTH" INSTANCE_SLUG="$instance_slug" NAMESPACE="$NAMESPACE"
        envsubst '${GROUP} ${GROUND_TRUTH} ${INSTANCE_SLUG} ${NAMESPACE}' < "$YAML" \
            | oc apply -n "$NAMESPACE" -f - 2>/dev/null || continue

        launched=$((launched + 1))

        if [ $((launched % 50)) -eq 0 ]; then
            echo "  ... $launched jobs launched"
        fi
    done < "/tmp/judge-${group}.jsonl"

    echo "  $group: done"
done

echo
echo "=== Launched $launched judge-evasion jobs ==="
echo "Monitor: oc get jobs -l component=judge-evasion -n $NAMESPACE"
