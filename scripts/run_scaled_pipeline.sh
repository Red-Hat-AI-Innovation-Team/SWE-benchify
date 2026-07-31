#!/usr/bin/env bash
set -euo pipefail

# Master pipeline: synthesis → enrichment → validation → eval (haiku, sonnet, opus)
#
# Usage:
#   bash scripts/run_scaled_pipeline.sh                          # Full pipeline
#   bash scripts/run_scaled_pipeline.sh --skip-synthesis         # Resume from enrichment
#   bash scripts/run_scaled_pipeline.sh --skip-to-validation     # Resume from validation
#   bash scripts/run_scaled_pipeline.sh --skip-to-eval           # Resume from eval (uses latest eval-ready)
#   bash scripts/run_scaled_pipeline.sh --eval-only FILE         # Eval existing validated JSONL
#   bash scripts/run_scaled_pipeline.sh --models haiku,sonnet    # Only eval specific models

NAMESPACE="${NAMESPACE:-swebenchify}"
IMAGE="${IMAGE:-ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DATA_DIR="data"
MODELS="haiku,sonnet,opus"

SKIP_SYNTHESIS=false
SKIP_ENRICHMENT=false
SKIP_VALIDATION=false
EVAL_ONLY=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-synthesis) SKIP_SYNTHESIS=true; shift ;;
    --skip-to-validation) SKIP_SYNTHESIS=true; SKIP_ENRICHMENT=true; shift ;;
    --skip-to-eval) SKIP_SYNTHESIS=true; SKIP_ENRICHMENT=true; SKIP_VALIDATION=true; shift ;;
    --eval-only) EVAL_ONLY="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

export NAMESPACE IMAGE

echo "============================================"
echo "  SWE-benchify Scaled Pipeline"
echo "============================================"
echo "Timestamp:  $TIMESTAMP"
echo "Namespace:  $NAMESPACE"
echo "Models:     $MODELS"
echo "Data dir:   $DATA_DIR"
echo

# Helper: count lines in file
count_lines() { wc -l < "$1" 2>/dev/null | tr -d ' '; }

# ── Stage 1: Synthesis ─────────────────────────────────────────
if [ -n "$EVAL_ONLY" ]; then
  echo "=== Skipping pipeline stages, using eval-only input: $EVAL_ONLY ==="
  EVAL_READY="$EVAL_ONLY"
elif $SKIP_SYNTHESIS; then
  echo "=== Skipping synthesis ==="
else
  echo "=== Stage 1: Synthesis ==="
  echo "Launching synthesis jobs for all repos..."
  bash k8s/launch-all.sh

  echo "Waiting for synthesis jobs to complete..."
  SYNTH_OUTPUT="$DATA_DIR/synth-raw-$TIMESTAMP.jsonl"
  bash k8s/collect-results.sh synthesis-exp "$SYNTH_OUTPUT" --watch

  synth_count=$(count_lines "$SYNTH_OUTPUT")
  echo "Synthesis complete: $synth_count raw instances"
  echo
fi

# ── Stage 2: Enrichment ────────────────────────────────────────
if [ -n "$EVAL_ONLY" ]; then
  : # skip
elif $SKIP_ENRICHMENT; then
  echo "=== Skipping enrichment ==="
else
  echo "=== Stage 2: Enrichment ==="
  echo "Launching enrichment jobs..."
  # Pass synthesis results if available, otherwise enrichment script collects from cluster
  ENRICH_INPUT="${SYNTH_OUTPUT:-}"
  if [ -n "$ENRICH_INPUT" ] && [ -f "$ENRICH_INPUT" ]; then
    bash k8s/launch-enrichment.sh "$ENRICH_INPUT"
  else
    bash k8s/launch-enrichment.sh
  fi

  echo "Waiting for enrichment jobs to complete..."
  ENRICH_OUTPUT="$DATA_DIR/enriched-$TIMESTAMP.jsonl"
  bash k8s/collect-results.sh enrichment "$ENRICH_OUTPUT" --watch

  enrich_count=$(count_lines "$ENRICH_OUTPUT")
  echo "Enrichment complete: $enrich_count enriched instances"
  echo
fi

# ── Stage 3: Validation ───────────────────────────────────────
if [ -n "$EVAL_ONLY" ]; then
  : # skip
elif $SKIP_VALIDATION; then
  echo "=== Skipping validation ==="
else
  echo "=== Stage 3: Validation ==="
  echo "Launching validation jobs..."
  bash k8s/launch-validation.sh

  echo "Waiting for validation jobs to complete..."
  VALIDATE_OUTPUT="$DATA_DIR/validated-$TIMESTAMP.jsonl"
  OUTPUT="$VALIDATE_OUTPUT" bash k8s/collect-validation.sh --watch

  valid_count=$(count_lines "$VALIDATE_OUTPUT")
  echo "Validation complete: $valid_count validated instances"
  echo

  # ── Stage 3.5: Prepare eval-ready JSONL ──────────────────────
  echo "=== Preparing eval-ready instances ==="
  EVAL_READY="$DATA_DIR/eval-ready-$TIMESTAMP.jsonl"

  # Find the enrichment output (from this run or most recent)
  if [ -z "${ENRICH_OUTPUT:-}" ]; then
    ENRICH_OUTPUT=$(ls -t "$DATA_DIR"/enriched-*.jsonl 2>/dev/null | head -1)
    if [ -z "$ENRICH_OUTPUT" ]; then
      ENRICH_OUTPUT=$(ls -t "$DATA_DIR"/opus-enriched-*.jsonl 2>/dev/null | head -1)
    fi
  fi

  python3 -c "
import json, sys

# Load validation results — only 'valid' instances
valid_by_id = {}
with open('${VALIDATE_OUTPUT}') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get('status') == 'valid':
            valid_by_id[d['instance_id']] = d

# Load enriched instances and merge with validation data
count = 0
with open('${ENRICH_OUTPUT}') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            inst = json.loads(line)
        except json.JSONDecodeError:
            continue
        iid = inst.get('instance_id', '')
        if iid not in valid_by_id:
            continue
        vr = valid_by_id[iid]
        inst['FAIL_TO_PASS'] = json.dumps(vr.get('FAIL_TO_PASS', []))
        inst['PASS_TO_PASS'] = json.dumps(vr.get('PASS_TO_PASS', []))
        inst.setdefault('version', '1.0')
        inst.setdefault('repo_language', 'go')
        inst.setdefault('hints_text', '')
        print(json.dumps(inst))
        count += 1

print(f'Prepared {count} eval-ready instances', file=sys.stderr)
" > "$EVAL_READY"

  eval_ready_count=$(count_lines "$EVAL_READY")
  echo "Eval-ready: $eval_ready_count instances saved to $EVAL_READY"
  echo
fi

# ── Stage 4: Eval (sequential by model) ─────────────────────
if [ -z "${EVAL_READY:-}" ]; then
  # Find the most recent eval-ready file
  EVAL_READY=$(ls -t "$DATA_DIR"/eval-ready-*.jsonl 2>/dev/null | head -1)
  if [ -z "$EVAL_READY" ]; then
    EVAL_READY="$DATA_DIR/opus-eval-ready.jsonl"
  fi
fi

if [ ! -f "$EVAL_READY" ]; then
  echo "ERROR: No eval-ready file found at $EVAL_READY"
  exit 1
fi

eval_ready_count=$(count_lines "$EVAL_READY")
echo "=== Stage 4: Eval ==="
echo "Input: $EVAL_READY ($eval_ready_count instances)"
echo "Models: $MODELS"
echo

IFS=',' read -ra MODEL_LIST <<< "$MODELS"
for model in "${MODEL_LIST[@]}"; do
  model=$(echo "$model" | tr -d ' ')
  echo "--- Eval: $model ---"

  EVAL_OUTPUT="$DATA_DIR/eval-results-${model}-${TIMESTAMP}.jsonl"

  MODEL="$model" bash k8s/launch-eval.sh "$EVAL_READY"

  echo "Waiting for $model eval jobs to complete..."
  MODEL="$model" OUTPUT="$EVAL_OUTPUT" bash k8s/collect-eval.sh --watch

  eval_count=$(count_lines "$EVAL_OUTPUT")
  resolved=$(python3 -c "
import json
results = [json.loads(l) for l in open('$EVAL_OUTPUT') if l.strip()]
resolved = sum(1 for r in results if r.get('resolved'))
print(resolved)
" 2>/dev/null || echo "?")

  echo "$model eval complete: $resolved/$eval_count resolved ($(python3 -c "print(f'{100*${resolved}/${eval_count}:.1f}' if ${eval_count} > 0 else '0')" 2>/dev/null || echo "?")%)"
  echo
done

# ── Stage 5: Summary ──────────────────────────────────────────
echo "============================================"
echo "  Pipeline Complete — Summary"
echo "============================================"
echo

for model in "${MODEL_LIST[@]}"; do
  model=$(echo "$model" | tr -d ' ')
  result_file="$DATA_DIR/eval-results-${model}-${TIMESTAMP}.jsonl"
  if [ -f "$result_file" ]; then
    python3 -c "
import json
results = [json.loads(l) for l in open('$result_file') if l.strip()]
n = len(results)
resolved = sum(1 for r in results if r.get('resolved'))
rate = 100 * resolved / n if n else 0
print(f'  {\"$model\":>8s}: {resolved:>4d}/{n:<4d} resolved ({rate:.1f}%)')
" 2>/dev/null || echo "  $model: error reading results"
  fi
done

echo
echo "Generate detailed report: python3 scripts/eval_report.py --timestamp $TIMESTAMP"
