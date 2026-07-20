#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/lambdabaa/swebenchify-synthesis:latest}"
NAMESPACE="${NAMESPACE:-swebenchify}"

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

echo "=== Creating synthesis jobs in namespace $NAMESPACE ==="
echo "Image: $IMAGE"
echo "Repos: ${#REPOS[@]}"
echo

oc project "$NAMESPACE" 2>/dev/null || oc new-project "$NAMESPACE"

# Create PVC for output if it doesn't exist
oc get pvc synth-output -n "$NAMESPACE" 2>/dev/null || \
  oc create -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: synth-output
  namespace: $NAMESPACE
spec:
  accessModes: [ReadWriteMany]
  resources:
    requests:
      storage: 10Gi
EOF

for repo in "${REPOS[@]}"; do
  slug="${repo//\//-}"
  echo "Launching: $repo -> $slug"

  export REPO_FULL="$repo" REPO_SLUG="$slug" IMAGE="$IMAGE"
  envsubst < k8s/synthesis-job.yaml | oc apply -n "$NAMESPACE" -f -
done

echo
echo "=== Launched ${#REPOS[@]} jobs ==="
echo "Monitor with: oc get jobs -n $NAMESPACE"
echo "Logs: oc logs job/synth-<slug> -n $NAMESPACE"
