#!/usr/bin/env bash
set -euo pipefail

# Launch enrichment jobs for synthesis results.
#
# Usage:
#   bash k8s/launch-enrichment.sh <input-jsonl>       # From a pre-collected JSONL file
#   bash k8s/launch-enrichment.sh                     # Auto-collect from cluster synthesis-exp jobs

IMAGE="${IMAGE:-ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming}"
NAMESPACE="${NAMESPACE:-swebenchify}"
LIMIT="${LIMIT:-0}"  # 0 = no limit
SKIP_SCREENING="${SKIP_SCREENING:-1}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

oc project "$NAMESPACE" 2>/dev/null || true

# Map slug -> repo full name (for fixing instance_id/repo fields from synthesis output)
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

if [ -n "${1:-}" ] && [ -f "${1:-}" ]; then
  # Input JSONL provided — use it directly
  echo "=== Using provided input: $1 ==="
  cp "$1" "$TMPDIR/all-instances.jsonl"
else
  # Auto-collect from cluster synthesis-exp jobs
  echo "=== Collecting synthesis results from cluster ==="
  bash k8s/collect-results.sh synthesis-exp "$TMPDIR/raw-synth.jsonl"

  # Also collect from annotations directly for any jobs whose logs are gone
  touch "$TMPDIR/all-instances.jsonl"
  for job in $(oc get jobs -l component=synthesis-exp -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | sort); do
    ann=$(oc get job "$job" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations.result}' 2>/dev/null || true)
    [ -z "$ann" ] && continue
    echo "$ann" | grep '^{' >> "$TMPDIR/all-instances.jsonl" 2>/dev/null || true
  done

  # Merge with log-based results
  if [ -f "$TMPDIR/raw-synth.jsonl" ]; then
    cat "$TMPDIR/raw-synth.jsonl" >> "$TMPDIR/all-instances.jsonl"
  fi
fi

# Fix repo and instance_id fields, deduplicate
python3 -c "
import json, sys, re

slug_to_repo = dict(line.split('=', 1) for line in '''$(for k in "${!SLUG_TO_REPO[@]}"; do echo "$k=${SLUG_TO_REPO[$k]}"; done)'''.strip().split('\n') if '=' in line)

seen = set()
with open('$TMPDIR/all-instances.jsonl') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Fix repo field if it's a local path
        repo = d.get('repo', '')
        if 'local' in repo or '/' not in repo or '/clones/' in repo:
            # Try to infer repo from instance_id or job name
            iid = d.get('instance_id', '')
            matched = False
            for slug, full in sorted(slug_to_repo.items(), key=lambda x: -len(x[0])):
                if slug in iid or slug in d.get('_job_name', ''):
                    d['repo'] = full
                    matched = True
                    break
            if not matched:
                continue

        # Fix instance_id
        old_id = d.get('instance_id', '')
        if old_id.startswith('local__'):
            num = old_id.rsplit('-', 1)[-1] if '-' in old_id else old_id
            repo_slug = d['repo'].replace('/', '-')
            d['instance_id'] = f'{repo_slug}-{num}'

        iid = d.get('instance_id', '')
        if iid and iid not in seen:
            seen.add(iid)
            print(json.dumps(d))
" > "$TMPDIR/deduped.jsonl" 2>/dev/null || true

total=$(wc -l < "$TMPDIR/deduped.jsonl" | tr -d ' ')
echo "Found $total unique instances"

# Get existing enrichment jobs to skip
existing=$(oc get jobs -l component=enrichment -n "$NAMESPACE" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

launched=0
skipped=0

while IFS= read -r line; do
  [ -z "$line" ] && continue

  read -r instance_id repo_full < <(echo "$line" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
print(d['instance_id'], d['repo'])
")

  instance_slug=$(echo "$instance_id" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sed 's/[^a-z0-9-]/-/g' | cut -c1-63 | sed 's/-$//')

  if [ -z "$instance_slug" ]; then
    echo "WARN: empty slug for instance_id=$instance_id, skipping"
    continue
  fi

  if echo "$existing" | grep -q "^enrich-${instance_slug}$"; then
    skipped=$((skipped + 1))
    continue
  fi

  echo "$line" > "$TMPDIR/instance-${instance_slug}.jsonl"

  oc delete configmap "enrich-input-$instance_slug" -n "$NAMESPACE" &>/dev/null || true
  oc create configmap "enrich-input-$instance_slug" \
    --from-file="instances.jsonl=$TMPDIR/instance-${instance_slug}.jsonl" \
    -n "$NAMESPACE"

  export REPO_FULL="$repo_full" INSTANCE_SLUG="$instance_slug" IMAGE="$IMAGE" NAMESPACE="$NAMESPACE" SKIP_SCREENING="$SKIP_SCREENING"
  envsubst '${REPO_FULL} ${INSTANCE_SLUG} ${IMAGE} ${NAMESPACE} ${SKIP_SCREENING}' < k8s/enrichment-job.yaml | oc apply -n "$NAMESPACE" -f -
  launched=$((launched + 1))
  echo "Launched: enrich-$instance_slug ($repo_full)"

  if [ $((launched % 50)) -eq 0 ]; then
    echo "  ... $launched jobs launched so far"
  fi

  if [ "$LIMIT" -gt 0 ] && [ "$launched" -ge "$LIMIT" ]; then
    echo "Reached limit of $LIMIT jobs"
    break
  fi
done < "$TMPDIR/deduped.jsonl"

echo
echo "=== Launched $launched enrichment jobs ($skipped already existed, $total total instances) ==="
echo "Monitor with: oc get jobs -l component=enrichment -n $NAMESPACE"
