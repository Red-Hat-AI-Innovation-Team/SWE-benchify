#!/usr/bin/env bash
set -euo pipefail

# Collect results from completed K8s jobs before pod GC destroys logs.
#
# Usage:
#   bash k8s/collect-results.sh <component> <output-file> [--watch]
#
# component: synthesis | enrichment | validation
# output-file: JSONL file to append results to
# --watch: keep polling every 30s until all jobs are Complete or Failed
#
# Tracks collected jobs in <output-file>.collected to avoid duplicates.

COMPONENT="${1:?Usage: collect-results.sh <component> <output-file> [--watch]}"
OUTPUT="${2:?Usage: collect-results.sh <component> <output-file> [--watch]}"
WATCH="${3:-}"
NAMESPACE="${NAMESPACE:-swebenchify}"

COLLECTED_FILE="${OUTPUT}.collected"
touch "$COLLECTED_FILE" "$OUTPUT"

collect_once() {
  local new=0
  local total_jobs
  local completed_jobs

  total_jobs=$(oc get jobs -l "component=$COMPONENT" -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  completed_jobs=$(oc get jobs -l "component=$COMPONENT" -n "$NAMESPACE" --no-headers 2>/dev/null | grep "Complete" | awk '{print $1}')

  for job in $completed_jobs; do
    # Skip if already collected
    grep -q "^${job}$" "$COLLECTED_FILE" && continue

    # Extract results from logs
    local results
    results=$(oc logs "job/$job" -n "$NAMESPACE" 2>/dev/null \
      | sed -n '/=== RESULTS ===/,$ p' \
      | tail -n +2 \
      | grep '^{' || true)

    if [ -n "$results" ]; then
      echo "$results" >> "$OUTPUT"
      new=$((new + 1))
    fi

    echo "$job" >> "$COLLECTED_FILE"
  done

  local collected
  collected=$(wc -l < "$COLLECTED_FILE" | tr -d ' ')
  local done_or_failed
  done_or_failed=$(oc get jobs -l "component=$COMPONENT" -n "$NAMESPACE" --no-headers 2>/dev/null | grep -cE "Complete|Failed" || true)

  if [ "$new" -gt 0 ]; then
    echo "$(date +%H:%M:%S) Collected $new new results (total saved: $(wc -l < "$OUTPUT" | tr -d ' '), jobs: $done_or_failed/$total_jobs done)"
  fi

  # Return 1 if there are still running jobs (used by --watch)
  local running
  running=$(oc get jobs -l "component=$COMPONENT" -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "Running" || true)
  [ "$running" -gt 0 ] && return 1
  return 0
}

echo "Collecting $COMPONENT results to $OUTPUT..."

if [ "$WATCH" = "--watch" ]; then
  while true; do
    if collect_once; then
      echo "$(date +%H:%M:%S) All $COMPONENT jobs finished. Collection complete."
      break
    fi
    sleep 30
  done
else
  collect_once || true
  echo "Collection pass complete. $(wc -l < "$OUTPUT" | tr -d ' ') total results in $OUTPUT"
fi
