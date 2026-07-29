# SWE-benchify

Transform GitHub repositories into SWE-bench-compatible benchmarks. Mines real pull requests from open-source repos, extracts problem instances, and validates them in Docker sandboxes.

## Goal

Make synthetic SWE-bench instances HARDER for Claude models to solve. Baseline Haiku resolve rate was 79% on Go instances — too easy. Iterate on the synthesizer's mutation strategies, bug categories, multi-file coordination, and patch complexity to produce bugs that require deeper reasoning.

Primary optimization target: Haiku failure rate (Score = 0.7 × haiku_failure + 0.15 × diversity + 0.15 × 0.5, target: haiku_failure > 0.5). Sonnet and Opus resolve rates are tracked for difficulty calibration across model tiers.

The eval runs the full pipeline on OpenShift: synthesis → enrichment → validation → eval (Haiku, Sonnet, Opus). Local synthesizer.py changes are injected into cluster pods via ConfigMap overlay — no image rebuild needed. Scale pipeline: `bash scripts/run_scaled_pipeline.sh`.

## Language

Python

## Modifiable Files

src/swebenchify/**/*.py
tests/**/*.py
scripts/**/*.py
configs/**/*.yaml

## Test Command

python -m pytest -v

## Lint Command

python -m ruff check .

## Type Check Command

python -m mypy ./

## Project Eval

- name: difficulty
  command: python3 scripts/eval_difficulty.py
  parse: json
  weight: 1.0
  timeout: 7200
  description: Synthesizes + enriches + validates + evals on OpenShift via oc. Injects local synthesizer.py changes via ConfigMap overlay. Score = 0.7 × haiku_failure + 0.15 × diversity + 0.15 × 0.5.

## Eval Weights

- hygiene: 0.30
- growth: 0.20
- project: 0.50

## adversarial

- generator.eval_command: python3 scripts/eval_difficulty.py --role generator
- generator.metric_name: haiku_failure
- generator.threshold: 0.5
- generator.scope: src/swebenchify/synthesizer.py
- generator.timeout: 3600
- discriminator.eval_command: python3 scripts/eval_difficulty.py --role discriminator
- discriminator.metric_name: haiku_failure
- discriminator.threshold: 0.5
- discriminator.scope: src/swebenchify/synthesizer.py
- discriminator.timeout: 3600
- hysteresis: 2
- max_rounds: 30
- convergence_window: 3

## Target Branch

main
