#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming}"
NAMESPACE="${NAMESPACE:-swebenchify}"
MODEL="${MODEL:-haiku}"
INPUT="${1:?Usage: launch-eval.sh <input-jsonl> [--limit N]}"
LIMIT="${LIMIT:-0}"

# Model name → full model ID mapping
declare -A MODEL_IDS
MODEL_IDS=(
  [haiku]="claude-haiku-4-5"
  [sonnet]="claude-sonnet-4-5"
  [opus]="claude-opus-4-6"
)

MODEL_ID="${MODEL_IDS[$MODEL]:-}"
if [ -z "$MODEL_ID" ]; then
  echo "ERROR: Unknown model '$MODEL'. Valid: haiku, sonnet, opus"
  exit 1
fi

echo "=== Launching eval jobs (model=$MODEL, model_id=$MODEL_ID) ==="

oc project "$NAMESPACE" 2>/dev/null || true

# Get existing eval jobs for this model to skip
existing=$(oc get jobs -l component=eval,model="$MODEL" -n "$NAMESPACE" \
  --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

launched=0
skipped=0
total=0

while IFS= read -r line; do
  [ -z "$line" ] && continue
  total=$((total + 1))

  read -r instance_id repo_full < <(echo "$line" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
print(d.get('instance_id', ''), d.get('repo', ''))
" 2>/dev/null) || continue

  instance_slug=$(echo "$instance_id" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sed 's/[^a-z0-9-]/-/g' | cut -c1-63 | sed 's/-$//')

  [ -z "$instance_slug" ] && continue

  job_name="eval-${MODEL}-${instance_slug}"

  # Skip if job already exists
  if echo "$existing" | grep -q "^${job_name}$"; then
    skipped=$((skipped + 1))
    continue
  fi

  # Write instance to temp file
  tmpf=$(mktemp)
  echo "$line" > "$tmpf"

  # Create ConfigMap (model-namespaced)
  cm_name="eval-input-${MODEL}-${instance_slug}"
  oc delete configmap "$cm_name" -n "$NAMESPACE" &>/dev/null || true
  oc create configmap "$cm_name" \
    --from-file="instance.jsonl=$tmpf" \
    -n "$NAMESPACE" 2>/dev/null || { rm -f "$tmpf"; continue; }
  rm -f "$tmpf"

  # Launch eval job
  export REPO_FULL="$repo_full" INSTANCE_SLUG="$instance_slug" IMAGE="$IMAGE" NAMESPACE="$NAMESPACE" MODEL="$MODEL" MODEL_ID="$MODEL_ID"
  envsubst '${REPO_FULL} ${INSTANCE_SLUG} ${IMAGE} ${NAMESPACE} ${MODEL} ${MODEL_ID}' < k8s/eval-job.yaml \
    | oc apply -n "$NAMESPACE" -f - 2>/dev/null || continue

  launched=$((launched + 1))
  echo "Launched: $job_name ($repo_full)"

  if [ $((launched % 50)) -eq 0 ]; then
    echo "  ... $launched jobs launched so far"
  fi

  if [ "$LIMIT" -gt 0 ] && [ "$launched" -ge "$LIMIT" ]; then
    echo "Reached limit of $LIMIT jobs"
    break
  fi
done < "$INPUT"

echo
echo "=== Launched $launched eval jobs for $MODEL ($skipped already existed, $total total instances) ==="
echo "Monitor with: oc get jobs -l component=eval,model=$MODEL -n $NAMESPACE"
