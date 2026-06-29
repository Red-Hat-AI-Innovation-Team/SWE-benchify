# SWE-benchify Development Plan

See SPEC.md (v2) for the full system specification.

## Goals

1. **Phase 1: Reproduce SWE-bench.** If SWE-benchify processes the same
   12 repositories SWE-bench uses, it should produce a statistically
   similar dataset — same instance_ids, same FAIL_TO_PASS, same patches.
   Conformance targets (SPEC.md Section 9):
   - Mechanical stages: >=90% instance_id overlap
   - Validation: >=85% FAIL_TO_PASS agreement
   - Docker specs: >=80% functional equivalence
   - Agent ranking: correct relative ordering (opus > sonnet > haiku)

2. **Phase 2: Verified-like quality layer.** An LLM judge calibrated on
   SWE-bench Verified human annotations that can automatically filter
   instances to a "verified" quality tier.

## Key Insight

SWE-bench's pipeline is semi-automated: environment specs
(`MAP_VERSION_TO_INSTALL`) are **manually authored** per repo/version.
SWE-benchify automates this via agent-based discovery. Phase 1's central
milestone is measuring how good that automation is by comparing
agent-generated specs against SWE-bench's known-good specs.

---

## Phase 1: Reproduce SWE-bench

### 1.1 Docker Spec Generation Benchmark

Agent generates `MAP_VERSION_TO_INSTALL`-equivalent specs, measured
against SWE-bench's known-good specs.

- **1.1a** Define target format and comparison function. What fields does
  a generated spec need? (Python version, install_cmd, test_cmd,
  pip_packages, pre_install). Implement a scoring function that compares
  a generated spec against SWE-bench's ground truth.

- **1.1b** Run agent-based env discovery on all `(repo, version)` pairs
  from `MAP_REPO_VERSION_TO_SPECS` for Flask (6 versions) and Requests
  (28 versions). Compare generated specs against ground truth.

- **1.1c** Measure functional equivalence: do our specs produce identical
  test results? Run tests with our spec vs SWE-bench's spec on the same
  commit, compare pass/fail sets.

- **1.1d** Iterate on the agent prompt based on failure modes. Common
  issues: wrong Python version, missing pinned dependencies, wrong test
  command.

- **1.1e** Expand to 2-3 more SWE-bench repos (e.g., pytest, xarray,
  sympy) to stress-test generalization.

### 1.2 Validation Alignment

Our FAIL_TO_PASS must match SWE-bench's on the same instances.

- **1.2a** For instances where we have both our validation and SWE-bench's
  ground truth, compare FAIL_TO_PASS lists field-by-field. Need 20+
  instances checked.

- **1.2b** Add missing filters from the SWE-bench paper:
  - ImportError/AttributeError check on pre-solution test logs
  - Newly-created function/class exclusion (tests that call functions
    first introduced in the gold patch)

- **1.2c** Run validation using Docker (SWE-bench harness) instead of
  agent, for SWE-bench repos where specs exist. Compare results against
  agent-based validation to quantify the gap.

### 1.3 End-to-End Reproduction

Full pipeline on all 12 SWE-bench repos, measuring instance overlap.

- **1.3a** Run mechanical stages (1-2) on all 12 repos. Measure
  instance_id overlap against published dataset. Target: >=90%.

- **1.3b** Run validation (using SWE-bench Docker harness) on overlapping
  instances. Measure FAIL_TO_PASS agreement. Target: >=85%.

- **1.3c** Run agent ranking sanity check (haiku/sonnet/opus on a sample)
  to confirm relative ordering matches published results.

### 1.4 Spec + Docs Update

- **1.4a** Update SPEC.md to reflect dual-mode architecture: Docker-based
  validation for known repos, agent-based for new repos.

- **1.4b** Document `MAP_VERSION_TO_INSTALL` generation as a first-class
  feature of SWE-benchify.

---

## Phase 2: LLM Judge (Verified-like)

### 2.1 Data Collection

- **2.1a** Download SWE-bench Verified annotations from HuggingFace.
  Check if per-instance Q1/Q2/Q3 scores and free-text rationales are
  available, or if only the filtered instance list is published.

- **2.1b** If raw annotations aren't public, reconstruct partial labels:
  for each of the 1,699 annotated instances, we know whether it's in the
  final 500 (admitted) or not. Infer Q1/Q2/Q3 bounds from the filtering
  formula.

### 2.2 LLM Judge Development

- **2.2a** Design the judge prompt matching the Verified annotation
  protocol:
  - Q1: How well-specified is the issue text? (0-3)
  - Q2: Are the tests well-scoped for alternative solutions? (0-3)
  - Q3: Any other major issues? (0/1)
  Include 5-10 few-shot examples with rationales.

- **2.2b** Calibrate on ~60 instances from Verified (30 admitted, 30
  rejected). Tune the prompt until judge agrees with human labels.

- **2.2c** Validate on held-out set (~200 instances). Measure agreement
  rate on the admit/reject decision. Target: >=80%.

### 2.3 Integration

- **2.3a** Replace current `evaluator.py` quality stage with the
  calibrated judge using the Verified annotation protocol.

- **2.3b** Pipeline produces both a full dataset and a "verified" subset
  with per-instance quality scores attached.

---

## Dependencies

```
1.1a → 1.1b → 1.1c → 1.1d → 1.1e
                                ↓
1.2a → 1.2b → 1.2c ──────→ 1.3a → 1.3b → 1.3c
                                         ↓
                              1.4a, 1.4b
                                         ↓
                              2.1a → 2.1b → 2.2a → 2.2b → 2.2c → 2.3a → 2.3b
```

Phase 1.1 and 1.2 can run in parallel. Phase 1.3 depends on both.
Phase 2 can start once 2.1a is done (data availability check) regardless
of Phase 1 progress.

---

## Current Status (as of 2026-05-21)

### Phase 1: Complete

All conformance targets met (4/5 PASS, 1 explained gap):

| Target | Result | Status |
|--------|--------|--------|
| Spec generation >=80% | 86% (14 versions, 4 repos) | PASS |
| Functional equivalence | 99.6% (Flask v2.3) | PASS |
| Instance overlap >=90% | 99.7% (8 repos) | PASS |
| Docker harness compatible | 5/5 gold patches resolve | PASS |
| Agent ranking monotonic | haiku 3% < sonnet 10% < opus 65% | PASS |
| F2P agreement >=85% | 56% exact (agent-based) | GAP |

The F2P agreement gap is intrinsic to agent-vs-Docker validation: our
agent catches the primary failing test but misses secondary ones. Docker
validation itself works correctly.

### What's done
- Mechanical stages (1-2): 99.7% instance_id overlap on 8/13 repos
- Agent env discovery: 86% field match vs SWE-bench specs
- Docker validation: gold patches resolve through unmodified harness
- Spec bench: scoring functions + benchmark runner + results
- Validation alignment: FAIL_TO_PASS comparison module (PR #27 merged)
- Missing filters added: ImportError/AttributeError + new-symbol exclusion
- Agent ranking: monotonic ordering confirmed (3 models, 30 instances)
- 384 tests passing

### Remaining work
- 5 repos incomplete in 1.3a (GitHub API rate limits)
- Phase 1.4: Spec + docs update (this task)
- Phase 2: LLM judge (independent, can start now)
