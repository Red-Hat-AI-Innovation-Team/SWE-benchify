#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming}"
NAMESPACE="${NAMESPACE:-swebenchify}"
LIMIT="${LIMIT:-0}"  # 0 = no limit
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "=== Extracting instances from synthesis pods ==="

oc project "$NAMESPACE" 2>/dev/null || true

# Map pod slug -> repo full name
declare -A SLUG_TO_REPO
SLUG_TO_REPO=(
  [argoproj-argo-cd]="argoproj/argo-cd"
  [containers-image]="containers/image"
  [containers-podman]="containers/podman"
  [containers-storage]="containers/storage"
  [coreos-go-oidc]="coreos/go-oidc"
  [cri-o-cri-o]="cri-o/cri-o"
  [grpc-grpc-go]="grpc/grpc-go"
  [kubernetes-kubernetes]="kubernetes/kubernetes"
  [moby-moby]="moby/moby"
  [open-telemetry-opentelemetry-go]="open-telemetry/opentelemetry-go"
  [openshift-cluster-version-operator]="openshift/cluster-version-operator"
  [openshift-installer]="openshift/installer"
  [openshift-oc]="openshift/oc"
  [openshift-origin]="openshift/origin"
  [openshift-router]="openshift/router"
  [operator-framework-operator-lifecycle-manager]="operator-framework/operator-lifecycle-manager"
  [operator-framework-operator-registry]="operator-framework/operator-registry"
  [prometheus-prometheus]="prometheus/prometheus"
  [rook-rook]="rook/rook"
  [stolostron-hypershift]="stolostron/hypershift"
  [tektoncd-pipeline]="tektoncd/pipeline"
  [thanos-io-thanos]="thanos-io/thanos"
)

# Extract instances from each pod, tagging with real repo info
for pod in $(oc get pods -l component=synthesis -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name | sort); do
  # Derive repo slug from pod name: synth-<slug>-<hash>
  slug=$(echo "$pod" | sed 's/^synth-//; s/-[a-z0-9]*$//')
  repo_full="${SLUG_TO_REPO[$slug]:-}"
  if [ -z "$repo_full" ]; then
    echo "WARN: unknown slug '$slug' from pod $pod, skipping"
    continue
  fi

  # Extract JSON lines, fix repo and instance_id fields
  oc logs "$pod" -n "$NAMESPACE" 2>/dev/null | grep '^{' | python3 -c "
import json, sys
repo_full = '$repo_full'
repo_slug = '$slug'
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    # Fix repo field
    d['repo'] = repo_full
    # Fix instance_id: replace local__repo with real slug
    old_id = d.get('instance_id', '')
    num = old_id.rsplit('-', 1)[-1] if '-' in old_id else old_id
    d['instance_id'] = f'{repo_slug}-{num}'
    print(json.dumps(d))
" >> "$TMPDIR/all-instances.jsonl" 2>/dev/null || true
done

# Deduplicate by instance_id
python3 -c "
import json
seen = set()
with open('$TMPDIR/all-instances.jsonl') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        iid = d.get('instance_id', '')
        if iid and iid not in seen:
            seen.add(iid)
            print(line)
" > "$TMPDIR/deduped.jsonl" 2>/dev/null || true

total=$(wc -l < "$TMPDIR/deduped.jsonl" | tr -d ' ')
echo "Found $total unique instances"

# Get existing enrichment jobs to skip
existing=$(oc get jobs -l component=enrichment -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

launched=0
skipped=0

while IFS= read -r line; do
  [ -z "$line" ] && continue

  # Extract fields with python (handles control chars safely)
  read -r instance_id repo_full < <(echo "$line" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
print(d['instance_id'], d['repo'])
")

  # Sanitize for k8s naming
  instance_slug=$(echo "$instance_id" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sed 's/[^a-z0-9-]/-/g' | cut -c1-63 | sed 's/-$//')

  if [ -z "$instance_slug" ]; then
    echo "WARN: empty slug for instance_id=$instance_id, skipping"
    continue
  fi

  # Skip if job already exists
  if echo "$existing" | grep -q "^enrich-${instance_slug}$"; then
    skipped=$((skipped + 1))
    continue
  fi

  # Write instance to temp file (avoids shell escaping issues with control chars)
  echo "$line" > "$TMPDIR/instance-${instance_slug}.jsonl"

  # Create ConfigMap from file
  oc delete configmap "enrich-input-$instance_slug" -n "$NAMESPACE" &>/dev/null || true
  oc create configmap "enrich-input-$instance_slug" \
    --from-file="instances.jsonl=$TMPDIR/instance-${instance_slug}.jsonl" \
    -n "$NAMESPACE"

  # Launch enrichment job
  export REPO_FULL="$repo_full" INSTANCE_SLUG="$instance_slug" IMAGE="$IMAGE"
  envsubst < k8s/enrichment-job.yaml | oc apply -n "$NAMESPACE" -f -
  launched=$((launched + 1))
  echo "Launched: enrich-$instance_slug ($repo_full)"

  # Progress update every 50
  if [ $((launched % 50)) -eq 0 ]; then
    echo "  ... $launched jobs launched so far"
  fi

  # Respect limit
  if [ "$LIMIT" -gt 0 ] && [ "$launched" -ge "$LIMIT" ]; then
    echo "Reached limit of $LIMIT jobs"
    break
  fi
done < "$TMPDIR/deduped.jsonl"

echo
echo "=== Launched $launched enrichment jobs ($skipped already existed, $total total instances) ==="
echo "Monitor with: oc get jobs -l component=enrichment -n $NAMESPACE"
echo "Logs: oc logs job/enrich-<instance-slug> -n $NAMESPACE"
