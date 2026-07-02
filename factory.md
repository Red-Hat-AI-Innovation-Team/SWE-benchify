# SWE-benchify

Transform GitHub repositories into SWE-bench-compatible benchmarks. Mines real pull requests from open-source repos, extracts problem instances, and validates them in Docker sandboxes.

## Goal

Generate synthetic SWE-bench instances that:
1. Pass structural validation (non-empty patches, test patches, and issue text with ≥2 changed lines)
2. Produce patches that apply cleanly and pass F2P/P2P Docker validation (tests fail before fix, pass after)
3. Are textually indistinguishable from real instances (Opus 4.6 judge evasion rate >50%)
4. Exhibit diversity in bug types, affected files, and patch complexity across repos and languages (Python, Go, Java, Rust)

Score = 0.7 × judge_evasion + 0.3 × diversity. Structural, F2P, and diversity failures gate the score to 0.0.

Adversarial GAN loop: eval alternates between generator (optimize evasion) and discriminator (optimize detection) phases.
Generator phase: optimize synthesizer code to fool the judge (score = evasion × f2p × 0.7 + diversity × 0.3).
Discriminator phase: optimize judge prompt/logic to detect fakes (score = recall × specificity, multiplicative — no degenerate strategies).
Phase switches when threshold is crossed (generator ≥ 0.4 → discriminator, discriminator ≥ 0.8 → generator).
State tracked in .factory/adversarial_state.json.

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
  command: python3 scripts/eval_synthesizer.py --mode adversarial
  parse: json
  weight: 1.0
  timeout: 3600
  description: Adversarial GAN loop. Generator phase optimizes evasion, discriminator phase optimizes detection. Auto-switches when thresholds crossed.

## Eval Weights

- hygiene: 0.30
- growth: 0.20
- project: 0.50

## Target Branch

main
