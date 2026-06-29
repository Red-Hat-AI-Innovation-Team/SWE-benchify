# Project Plan: Synthetic SWE-bench Instance Generator

## Context

Mining valid SWE-bench instances from real GitHub PRs has proven extremely difficult — 10 constraints must hold simultaneously, and the yield from raw PRs to valid instances is low (see `DIFFICULTIES_REPORT.md`). Synthetic generation removes 5 of 10 constraints entirely and simplifies a 6th, making it a fundamentally better approach for producing benchmark data at scale.

**SWE-Smith** (NeurIPS 2025 D&B Spotlight, [swesmith.com](https://swesmith.com/)) has already proven this approach works: 50K instances across 128 Python repos at $1,360 total cost. It uses the same environment-first inversion we identified independently. Our project builds on this insight but targets a different goal.

### SWE-Smith vs. Our Approach: Different Optimization Targets

| Dimension | SWE-Smith | Our Project |
|-----------|-----------|-------------|
| **Primary goal** | Training data volume for fine-tuning | Benchmark quality for model evaluation |
| **Scale target** | 50K+ instances | 500+ high-quality instances |
| **Validation rigor** | 1 broken test + 2min timeout | `compute_f2p()` with N-run flake quarantine + all SWE-bench paper filters |
| **Realism measurement** | Difficulty classifier only | LLM discriminator (real vs. synthetic) |
| **Model separation** | Not measured | First-class criterion (haiku < sonnet < opus) |
| **Improvement loop** | One-shot pipeline | Autonomous iteration via remote-factory |
| **Flake handling** | None | Multi-run determinism with quarantine |
| **Quality filters** | Minimal (≥1 broken test) | Full SWE-bench paper filters (new-symbol, ImportError, problem statement quality) |
| **Issue text** | LM-generated from F2P test + output (leaks hints) | LM-generated from symptoms only (no test leakage) |

**Our thesis:** SWE-Smith optimized for quantity; we optimize for quality. A smaller set of high-fidelity, discriminator-validated, separation-producing instances is more valuable as a benchmark than a larger set of loosely-validated ones. remote-factory's autonomous improvement loop is the mechanism that drives quality up iteratively.

### SWE-Smith Techniques We Should Adopt

- **Environment-first architecture** — build Docker image per repo, not per instance (SWE-Smith reduced 50-150TB to 295GB this way)
- **Multiple synthesis strategies** — SWE-Smith found PR Mirror most training-effective (9.2%) but LM Modify highest yield (56%); we should compare strategies too
- **Bug merging / combination** — SWE-Smith's "Combine" strategy (96.9% yield) merges validated bugs from the same file for harder instances

### SWE-Smith Gaps We Exploit

1. **No flake quarantine** — SWE-Smith has no multi-run validation. Flaky tests can appear as valid F2P.
2. **No realism discriminator** — They measure difficulty but never ask "does this look like a real bug?"
3. **No separation criterion** — They show training effectiveness but don't verify instances create ranking between models.
4. **Hint leakage in issue text** — SWE-Smith's issue prompt includes F2P test source code and execution output, potentially leaking the solution approach.
5. **Weak validation** — Only ≥1 broken test with 2-minute timeout. No `check_new_symbol_in_tests()`, no ImportError/AttributeError filter, no problem statement quality checks.
6. **No improvement loop** — Pipeline runs once; no mechanism to learn which strategies/repos/bug-types produce the best instances.

---

## Architecture

```
                     REMOTE-FACTORY (Orchestrator)
                     ============================
                     CEO Agent: Observe → Hypothesize → Build → Measure → Decide → Learn

                                      |
                                      v
               .-----------------------------------------.
               |     SYNTH-SWE-BENCH (separate repo)      |
               |                                          |
               |  +------------------------------------+  |
               |  | Environment Library                |  |
               |  | Pre-built Docker images per repo   |  |
               |  | Known-green test suite per commit  |  |
               |  +-----------------||-----------------+  |
               |                    ||                    |
               |          .---------vv----------.         |
               |          |                     |         |
               |          v                     v         |
               |  +---------------+  +----------------+  |
               |  | Strategy A    |  | Strategy B     |  |
               |  | AST Mutation  |  | Agent-Authored |  |
               |  | + Agent       |  | Semantic Bugs  |  |
               |  | Curation      |  |                |  |
               |  +------||-------+  +-------||-------+  |
               |         ||                  ||           |
               |         vv                  vv           |
               |  +------------------------------------+  |
               |  | In-Loop Validator                  |  |
               |  | swebenchify.grader.compute_f2p()   |  |
               |  | + 3-run determinism check          |  |
               |  | + swebenchify.filters.*            |  |
               |  +-----------------||-----------------+  |
               |                    ||                    |
               |                    vv                    |
               |  +------------------------------------+  |
               |  | swebenchify.emitter.emit_dataset() |  |
               |  +------------------------------------+  |
               '-----------------------------------------'
                                      |
                                      v
               .-----------------------------------------.
               |     QUALITY MEASUREMENT SUITE            |
               |                                          |
               |  1. Realism discriminator (LLM judge)    |
               |  2. Validity (compute_f2p + filters)     |
               |  3. Separation (haiku/sonnet/opus eval)  |
               |  4. SWE-Smith comparison baseline        |
               '-----------------------------------------'
```

**Data flow per instance:**
1. Select target (repo, commit, source file) from environment library
2. Inject bug via Strategy A or B → produces `bug_patch`, `gold_patch`, `test_patch`, `problem_statement`
3. Validate in Docker via `compute_f2p()` (3 runs, flake quarantine)
4. Apply quality filters (`get_filter_reasons()`, `check_new_symbol_in_tests()`)
5. Emit valid instance as `TaskInstance` → JSONL

---

## Phases

### Phase 0: Scaffolding + Environment Library (Weeks 1-2)

**Goal:** Stand up the repo, import SWE-benchify, build the environment library.

**New repo structure:**
```
synth-swe-bench/
  pyproject.toml                  # depends on swebenchify, remote-factory
  src/synth_bench/
    config.py                     # SynthConfig
    env_library.py                # Registry of repo@commit → (EnvironmentSpec, image, green_tests)
    env_builder.py                # Build/validate Docker images, record green test sets
    target_selector.py            # Pick (repo, commit, file) triples with test coverage
    models.py                     # SyntheticCandidate, BugInjectionResult, GenerationMetrics
  data/
    target_repos.yaml             # Curated repo list with Python versions
  tests/
  .factory/                       # remote-factory project state
```

**Key modules:**

- `env_library.py` — `EnvironmentLibrary` class backed by JSONL registry. Each entry: repo, commit, python_version, env_spec, docker_image, green_tests (all passing test IDs), build_timestamp. Methods: `register()`, `get()`, `list_repos()`, `validate_entry()`.

- `env_builder.py` — Reuses `swebenchify.backends._python_make_dockerfile()` to build images. Runs full test suite 3x in Docker to identify the deterministic green test set (excluding flaky tests). This is SWE-Smith's approach but with flake quarantine added.

- `target_selector.py` — Picks source files with existing test coverage, non-trivial logic (>20 lines, has branches/loops). Returns `TargetContext` with repo, commit, env_spec, source content, related test files.

**Initial target repos:** 5-10 well-known Python repos (flask, requests, pytest, xarray, sympy) where SWE-benchify already has validated specs.

**Exit criteria:**
- Environment library populated for ≥5 repos with ≥1 validated commit each
- Green test sets are deterministic across 3 runs
- Target selector can pick 10+ source files per repo

### Phase 1: Mutation-Based Generator — Strategy A (Weeks 3-5)

**Goal:** Build the first working generator using AST mutations with agent curation.

**New modules:**

- `mutator.py` — Python `ast`-based mutation engine. Mutation types (aligned with SWE-Smith's "Procedural" category for comparison): BoundaryMutation (`<` → `<=`), OffByOneMutation, NegationMutation, DefaultValueMutation, ReturnValueMutation, ExceptionHandlerMutation, ConditionalMutation. Each implements `applicable(node)`, `apply(node)`, `describe()`. Uses complexity scoring to prefer non-trivial targets (same concept as SWE-Smith's complexity filter).

- `mutation_runner.py` — Applies mutation, runs tests in Docker via `swebenchify.grader.compute_f2p()`. Filters: reject 0-test-breaking mutations (equivalent), reject >20-test-breaking mutations (catastrophic), reject non-deterministic results (2 runs). The gold_patch is the reverse of the mutation.

- `curator.py` — Agent curation step (via `swebenchify.dispatcher.run_agent_task()`). Agent receives original code, mutated code, and broken tests. Tasks: (1) rate realism 1-5, reject if <3; (2) write problem statement describing SYMPTOMS only, 40-200 words, no code paths or file names; (3) rate difficulty. Budget: $0.50, max 10 turns. **Key difference from SWE-Smith:** problem statement is generated from behavioral symptoms, not from F2P test source code — avoids hint leakage.

- `generator_a.py` — Orchestrator: select targets → generate mutations → run in Docker → curate survivors → validate via `compute_f2p()` with n_runs=3 → apply `get_filter_reasons()` → emit.

**Exit criteria:**
- ≥20 valid instances from the 5-repo library
- 100% pass `compute_f2p()` and filters
- ≥50% mutation curation accept rate

### Phase 2: Semantic Bug Generator — Strategy B (Weeks 5-7)

**Goal:** Build agent-authored bug injection (aligned with SWE-Smith's "LM Modify"/"LM Rewrite" but with tighter validation).

**New modules:**

- `semantic_generator.py` — Agent studies a source file, introduces a realistic behavioral bug, writes tests that catch it, writes a problem statement from user perspective. Budget: $2.00, max 30 turns. Outputs: bug_patch, gold_patch, test_patch, problem_statement, difficulty, bug_category.

- `semantic_validator.py` — Validates agent output: (1) bug_patch applies cleanly, (2) code compiles, (3) `compute_f2p()` confirms fail-then-pass with n_runs=3, (4) bug doesn't break >5 existing green tests (subtle, not catastrophic), (5) passes all `get_filter_reasons()` including `check_new_symbol_in_tests()`.

- `generator_b.py` — Orchestrator for Strategy B, same output format as Strategy A.

**Exit criteria:**
- ≥10 valid instances from the 5-repo library
- ≥20% agent yield rate (valid instance per attempt)

### Phase 3: Quality Measurement Suite + SWE-Smith Comparison (Weeks 7-9)

**Goal:** Build all three success metrics and establish baselines against SWE-Smith.

**New modules:**

- `realism_discriminator.py` — LLM judge receives an instance (problem statement, gold patch, test patch, repo name) and predicts real vs. synthetic. Mix N synthetic + N real (from SWE-bench Verified). Measures: accuracy, precision, recall, average confidence. **Target:** discriminator accuracy ≤60% (near-random = indistinguishable). **Comparison:** run the same discriminator on SWE-Smith instances to establish their realism baseline.

- `validity_checker.py` — Wraps `compute_f2p()` with n_runs=3 + `get_filter_reasons()`. **Target:** 100% pass. **Comparison:** run SWE-Smith instances through the same pipeline — how many survive our stricter validation?

- `separation_evaluator.py` — Run haiku, sonnet, opus on generated instances via `swebenchify.eval_harness`. Compute per-model resolve rates, check monotonic ordering, measure inter-tier gaps. **Target:** monotonic ordering with ≥10pp gap between tiers. **Comparison:** measure separation on a matched-size sample of SWE-Smith instances.

- `quality_dashboard.py` — Aggregates all metrics into a `QualityReport` with strategy breakdown and SWE-Smith comparison column. JSON format compatible with remote-factory's evaluation framework.

**Exit criteria:**
- All three metrics run end-to-end
- Baseline numbers established for both our instances and SWE-Smith instances
- Head-to-head comparison documented

### Phase 4: Remote-Factory Integration (Weeks 9-11)

**Goal:** Wire into remote-factory's autonomous improvement loop.

**Deliverables:**

- `SKILL.md` — Defines the synthetic generation skill for remote-factory
- `factory_adapter.py` — Maps quality report to remote-factory's scoring dimensions. `run_experiment(hypothesis)` executes a generation run with changed parameters and measures quality. `compare_strategies(a_config, b_config)` runs both strategies head-to-head.

- **Hypothesis templates** for the CEO agent:
  - "Increase curation realism threshold from 3/5 to 4/5"
  - "Target files with higher cyclomatic complexity for better separation"
  - "Add multi-file bug injection for harder instances"
  - "Add SWE-Smith's Combine strategy (merge validated bugs from same file)"
  - "Switch problem statement prompt to include more contextual repo information"

**Exit criteria:**
- CEO can autonomously propose change → run experiment → measure quality → render verdict
- ≥3 improvement cycles complete without intervention
- Quality score improves across iterations

### Phase 5: Scale and Publish (Weeks 11-14)

**Goal:** Scale to 50+ repos, 500+ instances, publish comparison results.

**Deliverables:**
- Expanded environment library (50+ repos, 2-3 commits each)
- Parallelized generation (concurrent Docker validation, batch agent dispatch)
- Cost optimization (Docker image reuse, agent result caching)
- Decontamination check via `swebenchify.decontam.DecontaminationChecker`
- HuggingFace dataset upload with `provenance: "synthetic"`
- Comparison report: our instances vs. SWE-Smith on all three quality criteria

**Exit criteria:**
- 500+ valid instances across 50+ repos
- Realism: discriminator accuracy ≤60%
- Validity: 100% compute_f2p pass rate
- Separation: monotonic model ordering with ≥10pp gaps
- Head-to-head with SWE-Smith shows quality advantage on realism + separation
- Cost per valid instance <$5.00

---

## SWE-benchify Import Surface

| Module | Imports | Purpose |
|--------|---------|---------|
| `swebenchify.grader` | `compute_f2p()` | Docker-based F2P/P2P validation |
| `swebenchify.models` | `EnvironmentSpec`, `CandidateInstance`, `TaskInstance`, `ValidationResult` | Data models |
| `swebenchify.backends` | `get_backend("python")`, `LanguageBackend` | Python Dockerfile generation |
| `swebenchify.parsers` | `PytestVerboseParser` | Parse pytest output |
| `swebenchify.filters` | `get_filter_reasons()`, `check_new_symbol_in_tests()` | Quality filters |
| `swebenchify.emitter` | `emit_dataset()` | JSONL output |
| `swebenchify.dispatcher` | `run_agent_task()`, `CostTracker` | Agent dispatch |
| `swebenchify.eval_harness` | `eval_instance()` | Model separation eval |
| `swebenchify.decontam` | `DecontaminationChecker` | Overlap detection |

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Agent-written problem statements have detectable "AI voice" | Few-shot with 10+ real SWE-bench issues as style examples; measure with discriminator; iterate |
| Semantic agent produces catastrophic bugs (>20 tests broken) | Validate that bug_patch alone breaks <5 existing green tests; reject catastrophic mutations |
| Separation criterion fails (all models solve or none solve) | Mix difficulty levels deliberately; mutation strategy produces easy bugs, semantic strategy produces harder ones |
| SWE-Smith instances pass our quality checks too (no differentiation) | Focus comparison on realism discriminator and separation — even if validity is similar, realism and separation may differ |
| Cost per instance too high for semantic strategy | Budget cap per attempt; if yield <10%, lean on mutation strategy which is cheaper |

---

## Verification Plan

1. **Unit tests** — Each module (mutator, curator, discriminator, etc.) has its own test suite
2. **Integration test** — End-to-end: environment library → target selection → bug injection → validation → emission → quality measurement
3. **SWE-Smith comparison** — Download SWE-Smith dataset from HuggingFace, run through our validity checker and realism discriminator to establish their baseline
4. **Separation test** — Run haiku/sonnet/opus on ≥30 generated instances, verify monotonic ordering
5. **Factory loop test** — remote-factory CEO completes 3 autonomous improvement cycles
