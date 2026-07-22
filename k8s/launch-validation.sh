#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming}"
NAMESPACE="${NAMESPACE:-swebenchify}"
LIMIT="${LIMIT:-0}"  # 0 = no limit
LANGUAGE="${LANGUAGE:-go}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "=== Collecting enriched instances ==="

oc project "$NAMESPACE" 2>/dev/null || true

# Collect enrichment results (handles pod GC by grabbing logs early)
bash k8s/collect-results.sh enrichment "$TMPDIR/all-enriched.jsonl"

if [ ! -f "$TMPDIR/all-enriched.jsonl" ] || [ ! -s "$TMPDIR/all-enriched.jsonl" ]; then
  echo "No enriched instances found. Are enrichment jobs complete?"
  exit 1
fi

# Deduplicate by instance_id
python3 -c "
import json
seen = set()
with open('$TMPDIR/all-enriched.jsonl') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        iid = d.get('instance_id', '')
        if iid and iid not in seen:
            seen.add(iid)
            print(line)
" > "$TMPDIR/deduped.jsonl" 2>/dev/null || true

total=$(wc -l < "$TMPDIR/deduped.jsonl" | tr -d ' ')
echo "Found $total unique enriched instances"

# Get existing validation jobs to skip
existing=$(oc get jobs -l component=validation -n "$NAMESPACE" \
  --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

launched=0
skipped=0

while IFS= read -r line; do
  [ -z "$line" ] && continue

  # Extract fields
  read -r instance_id repo_full < <(echo "$line" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
print(d.get('instance_id', ''), d.get('repo', ''))
")

  # Sanitize for k8s naming
  instance_slug=$(echo "$instance_id" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sed 's/[^a-z0-9-]/-/g' | cut -c1-63 | sed 's/-$//')

  if [ -z "$instance_slug" ]; then
    echo "WARN: empty slug for instance_id=$instance_id, skipping"
    continue
  fi

  # Derive repo URL from instance if not already in owner/repo format
  if [[ "$repo_full" != *"/"* ]] || [[ "$repo_full" == *"/clones/"* ]]; then
    # Try to fix local path to owner/repo format
    slug=$(echo "$repo_full" | rev | cut -d/ -f1 | rev)
    parts=(${slug//__/ })
    if [ ${#parts[@]} -eq 2 ]; then
      repo_full="${parts[0]}/${parts[1]}"
    else
      # Try slug-to-repo lookup
      slug_key=$(echo "$slug" | tr '_' '-')
      repo_full="${SLUG_TO_REPO[$slug_key]:-}"
      if [ -z "$repo_full" ]; then
        echo "WARN: can't determine repo for $instance_id (slug=$slug), skipping"
        continue
      fi
    fi
  fi

  # Skip if job already exists
  if echo "$existing" | grep -q "^validate-${instance_slug}$"; then
    skipped=$((skipped + 1))
    continue
  fi

  # Write instance to temp file
  echo "$line" > "$TMPDIR/instance-${instance_slug}.jsonl"

  # Create ConfigMap from file
  oc delete configmap "validate-input-$instance_slug" -n "$NAMESPACE" &>/dev/null || true
  oc create configmap "validate-input-$instance_slug" \
    --from-file="instance.jsonl=$TMPDIR/instance-${instance_slug}.jsonl" \
    -n "$NAMESPACE"

  # Launch validation job
  export REPO_FULL="$repo_full" INSTANCE_SLUG="$instance_slug" IMAGE="$IMAGE" LANGUAGE="$LANGUAGE"
  envsubst < k8s/validation-job.yaml | oc apply -n "$NAMESPACE" -f -
  launched=$((launched + 1))
  echo "Launched: validate-$instance_slug ($repo_full)"

  if [ $((launched % 50)) -eq 0 ]; then
    echo "  ... $launched jobs launched so far"
  fi

  if [ "$LIMIT" -gt 0 ] && [ "$launched" -ge "$LIMIT" ]; then
    echo "Reached limit of $LIMIT jobs"
    break
  fi
done < "$TMPDIR/deduped.jsonl"

echo
echo "=== Launched $launched validation jobs ($skipped already existed, $total total instances) ==="
echo "Monitor with: oc get jobs -l component=validation -n $NAMESPACE"
echo "Logs: oc logs job/validate-<instance-slug> -n $NAMESPACE"
