# SWE-benchify

Transform GitHub repositories into SWE-bench-compatible benchmarks. Mines real pull requests from open-source repos, extracts problem instances, and validates them in Docker sandboxes.

## Goal

Generate synthetic SWE-bench instances that:
1. Pass structural validation (non-empty patches, test patches, and issue text with ≥2 changed lines)
2. Are textually indistinguishable from real instances (Opus 4.6 judge evasion rate >50%)
3. Exhibit diversity in bug types, affected files, and patch complexity across repos (Flask + requests)

Score = 0.7 × judge_evasion + 0.3 × diversity. Structural failures gate the score to 0.0.

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

- name: synthetic_detectability
  command: python3 /tmp/eval_synthesizer.py
  parse: json
  weight: 1.0
  timeout: 1800
  description: Multi-repo eval (Flask + requests). Structural gate (score=0 if any instance has empty patch/test_patch). Score = 0.7 × judge_evasion + 0.3 × diversity.

## Eval Weights

- hygiene: 0.30
- growth: 0.20
- project: 0.50

## Target Branch

main
