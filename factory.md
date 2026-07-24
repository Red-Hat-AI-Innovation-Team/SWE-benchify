# SWE-benchify

Transform GitHub repositories into SWE-bench-compatible benchmarks. Mines real pull requests from open-source repos, extracts problem instances, and validates them in Docker sandboxes.

## Goal

Make synthetic SWE-bench instances HARDER for Claude Haiku to solve. We have 504 validated Go instances where Haiku currently resolves 79% — too easy. Iterate on the enrichment logic (problem statement generation, hints, framing) to increase the Haiku failure rate above 50% while keeping instances valid and realistic.

Score = 0.7 × haiku_failure_rate + 0.15 × diversity + 0.15 × judge_evasion. Target: haiku_failure > 0.5.

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
  timeout: 3600
  description: Re-enriches a sample of 20 existing Go instances on OpenShift, evals with Haiku, measures failure rate. Score = 0.7 × haiku_failure + 0.15 × diversity + 0.15 × judge_evasion.

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
