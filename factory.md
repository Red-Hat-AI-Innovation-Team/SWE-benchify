# SWE-benchify

Transform GitHub repositories into SWE-bench-compatible benchmarks. Mines real pull requests from open-source repos, extracts problem instances, and validates them in Docker sandboxes.

## Goal

Generate synthetic SWE-bench instances that:
1. Pass structural validation (non-empty patches, test patches, and issue text with ≥2 changed lines)
2. Produce patches that apply cleanly and pass F2P/P2P Docker validation (tests fail before fix, pass after)
3. Are textually indistinguishable from real instances (Opus 4.6 judge evasion rate >50%)
4. Exhibit diversity in bug types, affected files, and patch complexity across repos and languages (Python, Go, Java, Rust)

Score = 0.7 × judge_evasion + 0.3 × diversity. Structural, F2P, and diversity failures gate the score to 0.0.

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
  command: python3 scripts/eval_synthesizer.py
  parse: json
  weight: 1.0
  timeout: 3600
  description: Multi-language eval (Python, Go, Java, Rust). Gates: structural → patch applies → diversity → F2P/P2P Docker → judge. Score = 0.7 × judge_evasion + 0.3 × diversity.

## Eval Weights

- hygiene: 0.30
- growth: 0.20
- project: 0.50

## adversarial

- generator.eval_command: python3 scripts/eval_synthesizer.py --role generator
- generator.metric_name: judge_evasion_score
- generator.threshold: 0.9
- generator.scope: src/swebenchify/, tests/
- generator.timeout: 3600
- discriminator.eval_command: python3 scripts/eval_synthesizer.py --role discriminator
- discriminator.metric_name: detection_recall
- discriminator.threshold: 0.8
- discriminator.scope: scripts/eval_synthesizer.py
- discriminator.timeout: 3600
- hysteresis: 2
- max_rounds: 30
- convergence_window: 3

## Target Branch

main
