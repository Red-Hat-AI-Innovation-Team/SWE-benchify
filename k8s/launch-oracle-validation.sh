#!/usr/bin/env bash
set -euo pipefail

# Run oracle validation on a Harbor dataset using OpenShift.
# Each task gets a K8s Job that: introduces the bug, applies the oracle fix,
# runs test.sh, and checks the reward.
#
# Usage:
#   bash k8s/launch-oracle-validation.sh data/harbor/haiku-hard-fixed
#   LIMIT=5 bash k8s/launch-oracle-validation.sh data/harbor/haiku-hard-fixed

DATASET_DIR="${1:?Usage: $0 <harbor-dataset-dir>}"
TASKS_DIR="$DATASET_DIR/tasks"
NAMESPACE="${NAMESPACE:-swebenchify}"
LIMIT="${LIMIT:-0}"

if [ ! -d "$TASKS_DIR" ]; then
  echo "ERROR: tasks directory not found at $TASKS_DIR"
  exit 1
fi

oc project "$NAMESPACE" 2>/dev/null || true

# Get existing oracle jobs to skip
existing=$(oc get jobs -l component=oracle-validation -n "$NAMESPACE" \
  --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

launched=0
skipped=0
errors=0
total=$(ls -d "$TASKS_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')

echo "=== Oracle validation: $total tasks in $DATASET_DIR ==="

for task_dir in "$TASKS_DIR"/*/; do
  task_name=$(basename "$task_dir")

  # Sanitize for k8s naming (lowercase, no underscores, max 63 chars)
  instance_slug=$(echo "$task_name" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | sed 's/[^a-z0-9-]/-/g' | cut -c1-53 | sed 's/-$//')

  if [ -z "$instance_slug" ]; then
    echo "WARN: empty slug for $task_name, skipping"
    errors=$((errors + 1))
    continue
  fi

  # Skip if job already exists
  if echo "$existing" | grep -q "^oracle-${instance_slug}$"; then
    skipped=$((skipped + 1))
    continue
  fi

  # Read image from task.toml
  image=$(grep 'base_image' "$task_dir/task.toml" 2>/dev/null | head -1 | sed 's/.*= *"//;s/".*//' || true)
  if [ -z "$image" ]; then
    image=$(grep 'docker_image' "$task_dir/task.toml" 2>/dev/null | head -1 | sed 's/.*= *"//;s/".*//' || true)
  fi
  if [ -z "$image" ]; then
    # Fall back to Dockerfile FROM line
    image=$(grep '^FROM ' "$task_dir/environment/Dockerfile" 2>/dev/null | head -1 | awk '{print $2}' || true)
  fi
  if [ -z "$image" ]; then
    echo "WARN: no image found for $task_name, skipping"
    errors=$((errors + 1))
    continue
  fi

  # Verify required files exist
  oracle_patch="$task_dir/solution/oracle.patch"
  if [ ! -f "$oracle_patch" ]; then
    # Try patch.diff (harbor_emitter format)
    oracle_patch="$task_dir/solution/patch.diff"
  fi
  if [ ! -f "$oracle_patch" ]; then
    echo "WARN: no oracle patch for $task_name, skipping"
    errors=$((errors + 1))
    continue
  fi

  test_sh="$task_dir/tests/test.sh"
  config_json="$task_dir/tests/config.json"
  test_patch="$task_dir/tests/test.patch"
  if [ ! -f "$test_sh" ] || [ ! -f "$config_json" ]; then
    echo "WARN: missing test.sh or config.json for $task_name, skipping"
    errors=$((errors + 1))
    continue
  fi

  # Create ConfigMaps
  oc delete configmap "oracle-patch-$instance_slug" -n "$NAMESPACE" &>/dev/null || true
  oc create configmap "oracle-patch-$instance_slug" \
    --from-file="oracle.patch=$oracle_patch" \
    -n "$NAMESPACE"

  # Build tests ConfigMap (test.sh + config.json + test.patch if exists)
  configmap_args=(
    --from-file="test.sh=$test_sh"
    --from-file="config.json=$config_json"
  )
  if [ -f "$test_patch" ]; then
    configmap_args+=(--from-file="test.patch=$test_patch")
  fi
  oc delete configmap "oracle-tests-$instance_slug" -n "$NAMESPACE" &>/dev/null || true
  oc create configmap "oracle-tests-$instance_slug" "${configmap_args[@]}" -n "$NAMESPACE"

  # Launch job
  export INSTANCE_SLUG="$instance_slug" IMAGE="$image" NAMESPACE="$NAMESPACE"
  envsubst '${INSTANCE_SLUG} ${IMAGE} ${NAMESPACE}' < k8s/oracle-validation-job.yaml | oc apply -n "$NAMESPACE" -f -
  launched=$((launched + 1))
  echo "Launched: oracle-$instance_slug ($image)"

  if [ $((launched % 20)) -eq 0 ]; then
    echo "  ... $launched/$total launched"
  fi

  if [ "$LIMIT" -gt 0 ] && [ "$launched" -ge "$LIMIT" ]; then
    echo "Reached limit of $LIMIT jobs"
    break
  fi
done

echo
echo "=== Launched $launched oracle validation jobs ($skipped already existed, $errors errors, $total total) ==="
echo "Monitor:  oc get jobs -l component=oracle-validation -n $NAMESPACE"
echo "Summary:  bash k8s/collect-oracle-results.sh"
