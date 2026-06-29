# Engineering Plan — SWE-benchify: Go Support & RH Instance Production

**Scope:** the portion of the cost/quality-routing workstream that lands *inside* SWE-benchify.
**Status:** Revised v2 — producer-only Go (option A) aligned · **Owner:** Ari
**Relationship to the broader plan:** SWE-benchify is the **dataset producer**. This plan extends it to emit the instances v1 needs (two Go repos, fresh, deterministically validated). The model panel, cost accounting, statistics, and dashboard live in the separate RH-org repo and consume this repo's JSONL.

---

## 0. Boundary (what is and isn't in this plan)

SWE-benchify's own SPEC (§1.2) lists as non-goals: an evaluation harness / agent benchmark runner, model inference, and any UI/leaderboard/dashboard. That is the same line we drew architecturally, so this plan stays strictly on the producer side and treats those non-goals as fixed.

**In scope (this repo):** multi-language environment specs + Go env discovery; deterministic Go validation with a pluggable test-log parser; Go post-validation filters; contamination/freshness + provenance metadata; segmentation columns in the emitter; per-`(repo, era)` image build/cache; conformance tests for Go.

**Out of scope (→ RH-org repo):** the multi-model eval orchestrator, k-attempt sampling, token/cost accounting, paired statistics, the Pareto frontier and memo, and all internal-source connectors (GitLab/Bugzilla/Jira) and internal data. These consume the dataset; they do not modify the producer.

**Hard constraints carried from the SPEC:**
- Output MUST remain a schema-valid `SWEbenchInstance`; all schema changes are **additive columns**, never breaking. *Python* instances additionally keep full `make_test_spec` / harness conformance unchanged; *Go* instances are conformance-defined by reproducible Docker validation (§2), not by `make_test_spec`.
- The Python path MUST be untouched; every Go change sits behind a language switch.
- v1 target repos: `kubernetes/kubectl`, `etcd-io/etcd` (public GitHub, Go).

---

## 1. Current state that this plan builds on

SWE-benchify already has the right bones: a staged pipeline (1 PR collection → 2 patch extraction → 3 env discovery → 4 validation → 4.5 quality judge → 5 filter → 6 emit), two operating modes (known-repo via SWE-bench's `MAP_REPO_VERSION_TO_SPECS` + Docker; new-repo via agentic discovery), named components (PR Collector, Patch Extractor, Environment Discovery Agent, Instance Validator, SWE-bench Compatibility Layer, Quality Filter, Dataset Emitter), and resumable, concurrency-bounded orchestration.

Three facts from the SPEC drive the work:

1. **Docker-spec generation is Python-only.** The required spec fields are `python`, `install`, `test_cmd`, `pip_packages`, `pre_install`, and the discovery agent is prompted to read the Python CI/tox matrix and `pip freeze`. There is no Go path.
2. **Test-file detection only looks multi-language-aware.** It matches paths containing `test`, `tests`, `e2e`, `testing`, `src/test/` — which both false-positives in Go (`latest.go`, `attestation/…`) and, more dangerously, *misses* Go's in-package `*_test.go` convention, so test hunks can leak into the gold patch and silently corrupt an instance. Fixing the hunk split for Go is a prerequisite for everything downstream (issue 1).
3. **Agent-based validation is lossy.** The SPEC's own conformance numbers show agent-based F2P at ~56% exact / ~81% subset agreement vs Docker ground truth, because the agent misses secondary failures. Docker-based validation, where it exists (Python known-repo), is faithful. For a *trustworthy* benchmark we must put Go on the deterministic Docker path, not the agentic one.

The SPEC also already records a monotonic cost-tier ordering on its generated data (haiku < sonnet < opus). That is the seed result this whole workstream generalizes — so we are extending, not replacing.

---

## 2. Design decision (resolved): producer-only Go

**Aligned approach.** SWE-benchify's stated compatibility target — "evaluable through the *unmodified* SWE-bench harness" — holds only for Python, because that harness evaluates Python only. We resolved this in favor of **producer-only Go**: SWE-benchify *produces and validates* Go instances deterministically in Docker, and its conformance target for Go is "schema-valid `SWEbenchInstance` + reproducible Docker F2P/P2P" — explicitly **not** "runs through vanilla `swebench.harness.run_evaluation`." Downstream Go *evaluation* is performed by a Go-capable harness (Multi-SWE-bench) owned by the RH-org repo, never by this one.

This keeps SWE-benchify's producer identity intact, leaves the Python path's harness conformance fully unchanged, and confines all Python-evaluation coupling to the Python language path. (The alternative — expanding this repo's charter to multi-harness *evaluation* — was considered and rejected as scope creep that blurs the producer/evaluator line the SPEC draws.)

**Consequences the rest of the plan depends on:**
- The Go conformance target is defined by reproducible Docker validation (WS-B / WS-F), not by `make_test_spec` + `run_evaluation`. Go instances remain schema-shaped `SWEbenchInstance` rows but are not required to satisfy the Python harness's `TestSpec` machinery.
- The Go **test-log parser** is factored as a standalone, dependency-light module (§4) and is the *shared seam* between this repo's validation and the RH-org evaluator's Multi-SWE-bench grading: both import the identical parser, so validation and grading cannot disagree about what "test X passed" means.
- Multi-SWE-bench becomes a named dependency of the *evaluation* side (RH-org repo). This repo takes no dependency on it for production, but the parser is the natural unit to upstream there if we want Go support to live in the broader community rather than only here.

---

## 3. Workstreams

Sizes are relative (S/M/L), not calendar estimates. Dependencies noted.

### WS-A — Multi-language environment spec + Go discovery (Stage 3) · M

Generalize the Python-bound spec into a language-tagged spec, and add a Go discovery path.

- Introduce a `language`-discriminated `EnvironmentSpec` (the field already exists; make the *spec-generation* honor it). Define `GoEnvironmentSpec`: `go_version` (from `go.mod` / `GOTOOLCHAIN`), `build_cmd`, `test_cmd`, `module_mode` (modules vs vendored), `GOFLAGS`, `system_dependencies`.
- Add a Go branch to the Environment Discovery Agent prompt: detect toolchain from `go.mod`, choose the repo's real test entry point (`make test` / `hack/` script / `go test ./...`), confirm it produces parseable `-json` output.
- Extend the SWE-bench Compatibility Layer so a non-Python spec still yields a valid `TestSpec` (or the (A)-mode Go equivalent). Python `MAP_VERSION_TO_INSTALL` conversion stays as-is.
- Populate the two required schema fields for Go without `MAP_REPO_VERSION_TO_SPECS`: a `version` resolvable in a per-`(repo, era)` spec registry keyed on `env_spec_hash`, and a non-null `environment_setup_commit` derived from a pinned setup/base commit (issue 4).
- **Acceptance:** for kubectl and etcd at a known base commit, discovery emits a `GoEnvironmentSpec` that builds and runs the repo's unit tests in a container with parseable output. Field-match ≥ the SPEC's Python baseline (~86%) measured against hand-written specs for ~5 versions.

### WS-B — Deterministic Go validation + pluggable test-log parser (Stage 4) · L · **centerpiece**

Put Go on the Docker-based validation path and replace agentic result interpretation with deterministic parsing.

- Define a `TestLogParser` protocol: `parse(raw_output) -> dict[test_id -> {passed|failed|skipped}]`, registered per language.
- Implement `GoJSONParser` over `go test -json` events: handle subtests/table-driven tests (`TestX/case` from `Action`/`Test` events), package-scoped runs, and the build-vs-test distinction.
- Wire the existing Docker validation flow (apply `test_patch` at `base_commit` → run → apply gold `patch` → run → diff) to use the registered parser for Go, instead of the agent reading output.
- Emit a distinct `compiled: bool` outcome: a non-compiling Go patch fails the whole package, which is a clean reject signal, not a test failure — record it as such.
- **Acceptance:** on the rh-swe-bench Go instances for kubectl/etcd (known-good F2P/P2P), deterministic Docker validation reproduces recorded F2P with ≥85% exact agreement — clearing the ~56% agentic baseline. This is the trustworthiness gate.
- **Depends on:** WS-A (needs a runnable Go spec).

### WS-C — Go post-validation filters + flake quarantine (Stages 4–5) · M

The SPEC's post-validation filters are Python-specific (drop instances whose pre-fix logs show `ImportError`/`AttributeError`). Add Go analogues and determinism guarantees.

- Go analogues: discard instances whose pre-fix failure is a build/compile error or missing-dependency error rather than a genuine test failure; discard F2P tests that reference symbols first introduced by the gold patch (unsolvable-by-naming, same rationale as the Python rule).
- **Flake quarantine:** run F2P/P2P *n* times at base and head; require a deterministic fail→pass flip; quarantine nondeterministic tests; drop the instance if quarantining removes its only F2P. (etcd integration/e2e tests make this non-optional; restrict v1 F2P to unit packages.)
- **Acceptance:** re-running validation on the same instance set yields identical F2P/P2P across runs; flaky tests are quarantined with a recorded reason.
- **Depends on:** WS-B.

### WS-D — Contamination/freshness + provenance + RH linking (Stages 1–2, 6) · S–M

- Freshness: `pr_after`/`pr_before` already exist; add per-instance `fix_merge_date` and `created_at` (latter already present) to the emit, and a config knob to filter to "after cutoff date" for the contamination-clean slice.
- Provenance tag: `provenance ∈ {public_upstream, internal}` column (v1 is all `public_upstream`); sets up the internal-source path without building it.
- Decontamination overlap flag: an additive emit-time column marking instances whose `instance_id` or gold patch overlaps published SWE-bench / rh-swe-bench, so downstream can stratify or exclude. Computed cheaply at emission, so it stays producer-side (issue 14).
- RH issue linking: extend the GitHub-style regex (`(close[sd]?|fix(e[sd])?|resolve[sd]?) #?\d+`) to also recognize RH conventions — `rhbz#`, Jira keys (`OCPBUGS-\d+`, project keys), and commit trailers (`Resolves:`, `Fixes:`, `Bug-Url:`, Gerrit `Change-Id`), with a `link_confidence` score. (kubectl/etcd mostly use the GitHub style, so this is forward-investment, low-risk additive.)
- **Acceptance:** emitted instances carry `fix_merge_date`, `provenance`, and `link_confidence`; the cutoff filter yields a non-empty fresh slice for both repos.

### WS-E — Segmentation metadata in the emitter (Stage 6) · S

Add the additive columns the downstream analysis slices on — precedent exists (rh-swe-bench already ships `difficulty`, `bug_type`, `repo_language`, `image_name`).

- New columns, all derivable mechanically from the patch/PR/spec: `repo_language`, `product` (from a `repo → product` map seeded from rh-swe-bench), `n_fail_to_pass`, `patch_lines`, `files_touched`, `cross_file: bool`, `env_spec_hash`, `image_name`.
- **Acceptance:** every emitted instance validates as `SWEbenchInstance` (extra keys ignored by the base schema) and carries all segmentation columns.

### WS-F — Per-`(repo, era)` image build/cache + Go conformance suite (cross-cutting) · M

- Build and cache a Docker/podman image per `(repo, era)` with the discovered Go spec baked in; surface `image_name` (mirrors rh-swe-bench's approach). Cache key includes `env_spec_hash` so toolchain/vendor drift invalidates correctly.
- Add Go to the conformance tests (SPEC §9) under the producer-only definition (§2): mechanical-stage `instance_id` overlap, deterministic Docker F2P/P2P agreement vs known-good, and spec-generation match. The Python `run_evaluation` gate is **not** part of the Go suite — Go evaluation conformance is the RH-org evaluator's responsibility via Multi-SWE-bench.
- **Acceptance:** `pytest tests/ -q` includes green Go conformance tests; images rebuild deterministically.

---

## 4. Interfaces & schema changes (summary)

| Surface | Change | Compatibility |
|---|---|---|
| `EnvironmentSpec` | Honor `language`; add `GoEnvironmentSpec` variant | Additive; Python variant unchanged |
| Test-log parsing | New `TestLogParser` protocol + `GoJSONParser`; register per language | New abstraction; Python parser slots in unchanged |
| `TaskInstance` emit | Add columns: `repo_language, product, fix_merge_date, provenance, link_confidence, n_fail_to_pass, patch_lines, files_touched, cross_file, env_spec_hash, image_name, compiled` | Additive only; base `SWEbenchInstance` still valid |
| Config | Per-language docker base images; cutoff-date filter; RH linking patterns | New optional keys; defaults preserve current behavior |
| Validation | Go uses Docker + deterministic parser, not agent | New code path behind language switch |

The `TestLogParser` module is **standalone and dependency-light** so the RH-org evaluator imports the identical parser — validation and grading must agree on test-level pass/fail. It is also the natural unit to upstream to Multi-SWE-bench if @xukai92 wants the Go support to live in the broader community rather than only here.

---

## 5. Sequencing & milestones

Maps onto the design doc's Phase 0 (harness ready) → Phase 1 (fresh result).

- **M0 — Known-good replication.** WS-A + WS-B against existing rh-swe-bench Go instances for kubectl/etcd. **Gate:** deterministic Docker validation reproduces recorded F2P at ≥85% on both repos. *(This is the Phase 0 exit gate.)*
- **M1 — kubectl green end-to-end.** WS-C flake handling + WS-E columns; clean run on kubectl producing valid instances with segmentation metadata.
- **M2 — etcd hardened.** Concurrency/e2e flake quarantine proven on etcd; both repos stable.
- **M3 — Fresh + tagged.** WS-D cutoff filter, provenance, RH linking; emit the contamination-clean v1 slice for both repos.
- **M4 — Conformance locked.** WS-F Go conformance suite green; images reproducible. *(Producer side of Phase 1 done; hand JSONL to the RH-org evaluator.)*

Critical path: WS-A → WS-B → WS-C → (WS-D, WS-E in parallel) → WS-F.

### 5.1 Epic structure

The 15 issues organize into two GitHub epics, cut by risk and definition-of-done rather than topic.

**Epic 1 — Go support** *(capability; repo-agnostic)* — issues **1–10, 15**.
Hunk split, environment spec + Go discovery, `version`/`environment_setup_commit`, the `TestLogParser` protocol + `GoJSONParser`, deterministic Docker validation, Go filters, flake quarantine, per-`(repo, era)` imaging, and the Go conformance suite. **Exit = M0–M2:** deterministic Docker validation reproduces known-good F2P on kubectl/etcd at ≥85%, both repos stable. Essentially all technical risk lives here. Because we landed on producer-only Go with a standalone parser, this epic is self-contained and **cleanly upstreamable** to SWE-benchify upstream or Multi-SWE-bench.

**Epic 2 — RH dataset shaping** *(metadata + contamination controls)* — issues **11–14**.
Segmentation + validation-evidence columns, freshness cutoff + provenance, RH issue-linking, decontamination flag. **Exit = M3–M4:** a fresh, tagged, analysis-ready slice for both repos. Mostly additive columns and regex — low risk, mechanical. Stays Red Hat-specific.

**Parallelism.** Epic 2's *code* is independent of Go (freshness, provenance, segmentation, linking would apply to a Python RH repo too), so it can be built against the existing Python path in parallel with Epic 1; only its *demonstration on kubectl/etcd* waits on Epic 1. Natural ownership: Epic 1 co-owned with @xukai92 (and the unit that would be upstreamed), Epic 2 owned by us.

**The asymmetry (11 vs 4 issues) is the honest signal** — effort and uncertainty are concentrated in Go support; RH shaping is cheap once the capability exists. Don't rebalance it.

**Cross-epic edge.** Issue 11 (Epic 2) bundles segmentation columns with the validation-evidence columns (`n_runs`, flake counts, quarantined tests) *produced by* issue 9's flake quarantine (Epic 1). Keep 11 in Epic 2, but it cannot fully close until 9 lands — the one place the epics touch at the emitter.

---

## 6. Risks specific to this repo

- **Go validation fidelity.** If deterministic validation can't clear ~85% F2P agreement, the trustworthiness gate fails. Mitigation: `go test -json` gives structured per-subtest events (avoids the stdout-scraping failure mode), and M0 measures fidelity against known-good answers before any fresh mining.
- **etcd flakiness.** Integration/raft tests are slow and nondeterministic. Mitigation: restrict v1 F2P to unit packages; aggressive quarantine (WS-C).
- **Spec-generation accuracy for Go.** Agent may misread build entry points (make vs raw `go test` vs Bazel). Mitigation: confirm by execution (spec is only accepted if its `test_cmd` yields parseable `-json`); cache per `(repo, era)`.
- **Parser-contract drift.** Under option A, producer validation and downstream Multi-SWE-bench grading must use the *identical* Go parser (§2); if they diverge, an instance validated here could grade differently downstream. Mitigation: the parser is a single shared module with its own test suite, imported by both sides rather than reimplemented; treat any parser change as a cross-repo contract change.
- **Backward compatibility.** All changes additive and language-gated; the Python conformance suite must stay green throughout as a regression guard.

---

## 7. Issue list (fileable on the repo)

Ordered by dependency; the parenthetical at the end of each item is its stage/workstream. Items 1, 4, and 14 were added in the §7 completeness audit and are marked **[audit]**.

1. **[audit]** Go-aware test/code hunk classification in the Patch Extractor: split on `*_test.go` suffix + `testdata/`, replacing the substring/path rule that both false-positives (`latest.go`, `attestation/…`, `contest.go`) and — the dangerous case — false-negatives on Go's in-package `*_test.go` convention, which would let test hunks leak into the gold `patch` and silently corrupt the instance. Lands before the validation work. *(Stage 2 — upstream of everything.)*
2. Generalize `EnvironmentSpec` to honor `language`; add `GoEnvironmentSpec`. *(Stage 3, WS-A.)*
3. Go branch in Environment Discovery Agent prompt (toolchain, test entry point, `-json` check). *(Stage 3, WS-A.)*
4. **[audit]** Go `version` + `environment_setup_commit` semantics: populate the two required schema fields for Go without `MAP_REPO_VERSION_TO_SPECS` — per-`(repo, era)` spec registry keyed on `env_spec_hash`, `environment_setup_commit` derived from a pinned setup/base commit. Required for Go instances to be schema-valid. *(Stage 3 / Compatibility Layer, WS-A.)*
5. `TestLogParser` protocol + register-by-language plumbing. *(Stage 4, WS-B.)*
6. `GoJSONParser` over `go test -json` (subtests, packages, build-vs-test). *(Stage 4, WS-B.)*
7. Wire Docker validation (Stage 4) to deterministic parser for Go; emit `compiled`. *(Stage 4, WS-B.)*
8. Go post-validation filters (build-error / introduced-symbol). *(Stages 4–5, WS-C.)*
9. N-run flake quarantine in validation. *(Stages 4–5, WS-C.)*
10. Per-`(repo, era)` image build + cache keyed on `env_spec_hash`. *(Cross-cutting, WS-F.)*
11. Additive columns in the Dataset Emitter (+ `repo → product` map): the segmentation set (`repo_language, product, n_fail_to_pass, patch_lines, files_touched, cross_file, env_spec_hash, image_name`) **plus validation-evidence columns** (`n_runs`, flake counts, quarantined-test list) so downstream audits can see how each F2P/P2P was established. *(Stage 6, WS-E.)*
12. Freshness cutoff filter + `fix_merge_date` / `provenance` / `link_confidence`. *(Stages 1–2, 6; WS-D.)*
13. RH issue-linking patterns (`rhbz#`, `OCPBUGS-`, trailers, Change-Id). *(Stages 1–2, WS-D.)*
14. **[audit]** Decontamination overlap flag (emit-time, producer-side): flag instances whose `instance_id` or gold patch overlaps published SWE-bench / rh-swe-bench, as an additive column so downstream can stratify or exclude. Cheap to compute at emission, so it lives here rather than analysis-side. *(Stage 6, WS-D/E.)*
15. Go conformance tests under the producer-only definition (§2): mechanical `instance_id` overlap, deterministic Docker F2P/P2P agreement vs known-good, spec-generation match. No `run_evaluation` gate. *(WS-F.)*
