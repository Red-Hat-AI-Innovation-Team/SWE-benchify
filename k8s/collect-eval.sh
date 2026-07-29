#!/bin/bash
# Collect eval results from job annotations.
# Usage: bash k8s/collect-eval.sh [--watch]
#
# Environment:
#   MODEL    - filter by model label (haiku, sonnet, opus). Default: collect all.
#   OUTPUT   - output file path. Default: data/eval-results-${MODEL}.jsonl (or data/eval-results.jsonl if no MODEL)

MODEL="${MODEL:-}"
NAMESPACE="${NAMESPACE:-swebenchify}"

if [ -n "$MODEL" ]; then
  OUTPUT="${OUTPUT:-data/eval-results-${MODEL}.jsonl}"
  LABEL_SELECTOR="component=eval,model=${MODEL}"
else
  OUTPUT="${OUTPUT:-data/eval-results.jsonl}"
  LABEL_SELECTOR="component=eval"
fi

COLLECTED="${OUTPUT}.collected"
touch "$COLLECTED" "$OUTPUT"

collect_once() {
  local new=0
  local total_jobs
  total_jobs=$(oc get jobs -l "$LABEL_SELECTOR" -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')

  for job in $(oc get jobs -l "$LABEL_SELECTOR" -n "$NAMESPACE" --no-headers 2>/dev/null | grep "Complete" | awk '{print $1}'); do
    # Skip old jobs from previous runs (e.g. eval-ev-* from eval_difficulty.py)
    if [ -n "$MODEL" ] && [[ ! "$job" =~ ^eval-${MODEL}- ]]; then
      continue
    fi
    grep -q "^${job}$" "$COLLECTED" && continue

    result=$(oc get job "$job" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations.result}' 2>/dev/null || true)

    if [ -n "$result" ]; then
      echo "$result" >> "$OUTPUT"
      new=$((new + 1))
    fi
    echo "$job" >> "$COLLECTED"
  done

  local done_or_failed
  done_or_failed=$(oc get jobs -l "$LABEL_SELECTOR" -n "$NAMESPACE" --no-headers 2>/dev/null | grep -cE "Complete|Failed" || true)
  local running
  running=$(oc get jobs -l "$LABEL_SELECTOR" -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "Running" || true)

  if [ "$new" -gt 0 ]; then
    echo "$(date +%H:%M:%S) [${MODEL:-all}] Collected $new new (total: $(wc -l < "$OUTPUT" | tr -d ' ') saved, $done_or_failed/$total_jobs done, $running running)"
  fi

  [ "$running" -gt 0 ] && return 1
  return 0
}

echo "Collecting eval results${MODEL:+ for model=$MODEL} to $OUTPUT..."

if [ "${1:-}" = "--watch" ]; then
  while true; do
    if collect_once; then
      echo "$(date +%H:%M:%S) All eval jobs${MODEL:+ for $MODEL} finished. Collection complete."
      break
    fi
    sleep 30
  done
else
  collect_once || true
  echo "Collection pass complete. $(wc -l < "$OUTPUT" | tr -d ' ') total results in $OUTPUT"
fi
