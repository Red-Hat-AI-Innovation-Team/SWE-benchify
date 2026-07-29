#!/usr/bin/env bash
set -euo pipefail

# Launch parallel synthesis jobs: N jobs per repo, each producing 1 instance.
# Uses synthesis-experiment-job.yaml (1 mutation per job, ~1h deadline).
# Injects local synthesizer.py via ConfigMap code overlay.
#
# Usage:
#   bash k8s/launch-all.sh                    # 50 jobs per repo (default)
#   JOBS_PER_REPO=100 bash k8s/launch-all.sh  # 100 jobs per repo

IMAGE="${IMAGE:-ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming}"
NAMESPACE="${NAMESPACE:-swebenchify}"
JOBS_PER_REPO="${JOBS_PER_REPO:-100}"

REPOS=(
  argoproj/argo-cd
  containers/image
  containers/podman
  containers/storage
  coreos/go-oidc
  grpc/grpc-go
  kubernetes/kubernetes
  moby/moby
  open-telemetry/opentelemetry-go
  openshift/cluster-version-operator
  openshift/installer
  openshift/origin
  openshift/router
  operator-framework/operator-lifecycle-manager
  prometheus/prometheus
  rook/rook
  stolostron/hypershift
  tektoncd/pipeline
  thanos-io/thanos
  operator-framework/operator-registry
  cri-o/cri-o
  openshift/oc
)

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Parallel synthesis: ${JOBS_PER_REPO} jobs × ${#REPOS[@]} repos = $((JOBS_PER_REPO * ${#REPOS[@]})) total jobs ==="
echo "Image: $IMAGE"
echo

oc project "$NAMESPACE" 2>/dev/null || oc new-project "$NAMESPACE"

# Push local synthesizer.py as ConfigMap code overlay
CODE_CM="synth-code-scale"
oc delete configmap "$CODE_CM" -n "$NAMESPACE" 2>/dev/null || true
oc create configmap "$CODE_CM" \
  --from-file="synthesizer.py=$PROJECT_ROOT/src/swebenchify/synthesizer.py" \
  --from-file="validate_and_prepare.py=$PROJECT_ROOT/scripts/validate_and_prepare.py" \
  -n "$NAMESPACE"
echo "Pushed code overlay as ConfigMap $CODE_CM"
echo

# Template for injecting code overlay into rendered YAML
inject_overlay() {
  local yaml="$1"
  # Add volume mount entries after volumeMounts:
  yaml=$(echo "$yaml" | sed '/^          volumeMounts:$/a\
            - name: code-overlay\
              mountPath: /app/src/swebenchify/synthesizer.py\
              subPath: synthesizer.py\
              readOnly: true\
            - name: code-overlay\
              mountPath: /app/scripts/validate_and_prepare.py\
              subPath: validate_and_prepare.py\
              readOnly: true')
  # Add volume entry after volumes:
  yaml=$(echo "$yaml" | sed "/^      volumes:$/a\\
        - name: code-overlay\\
          configMap:\\
            name: $CODE_CM")
  echo "$yaml"
}

launched=0

for repo in "${REPOS[@]}"; do
  repo_slug="${repo//\//-}"
  echo "Launching $JOBS_PER_REPO jobs for $repo..."

  for j in $(seq 0 $((JOBS_PER_REPO - 1))); do
    job_slug="${repo_slug}-${j}"

    export REPO_FULL="$repo" REPO_SLUG="$job_slug" IMAGE="$IMAGE" NAMESPACE="$NAMESPACE" MAX_MUTATIONS="1"
    rendered=$(envsubst '${REPO_FULL} ${REPO_SLUG} ${IMAGE} ${NAMESPACE} ${MAX_MUTATIONS}' < k8s/synthesis-experiment-job.yaml)
    rendered=$(inject_overlay "$rendered")

    echo "$rendered" | oc apply -n "$NAMESPACE" -f - 2>/dev/null || continue
    launched=$((launched + 1))
  done

  echo "  $repo: $JOBS_PER_REPO jobs launched"
done

echo
echo "=== Launched $launched synthesis jobs ==="
echo "Monitor with: oc get jobs -l component=synthesis-exp -n $NAMESPACE"
echo "Collect results: bash k8s/collect-results.sh synthesis-exp data/synth-raw.jsonl --watch"
