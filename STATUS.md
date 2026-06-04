# SWE-benchify — Current Status

**As of 2026-06-04**

---

## TL;DR

The Go producer is **capability-complete but not yet run**. No Go instances exist in any output file. The M0 fidelity gate (≥85% F2P agreement vs rh-swe-bench known-good) has not been measured. Step 2 is the emission run, which requires an Anthropic API key.

---

## What is done

### Python path
- Phase 1 complete: spec generation (86% field match), instance overlap (99.7%), Docker harness compat (5/5 gold resolve), agent ranking monotonic.
- 78 validated Python instances in `output/swebenchify-dataset.jsonl` (Flask + Requests).

### Go producer (Epic 1 — all code merged)
- **Hunk classifier**: `*_test.go` + `testdata/` correctly routed; tested on 20 real etcd PRs, 0 leaks into gold patch.
- **`GoEnvironmentSpec` + discovery prompt**: covers `go.mod`, Makefile/`hack/` entry points, vendor detection, system deps from CI YAML.
- **`GoSpecRegistry`**: persistent JSON registry; `env_spec_hash → (version, era_commit)`; stable across re-runs.
- **`GoJSONParser`** (standalone, stdlib-only): subtests, parallel packages, compile-error detection; 24 unit tests.
- **Deterministic Docker validation**: `_parse_go_validation_output` uses `GoJSONParser`, not agent interpretation.
- **ID normalisation** (`normalize_go_f2p`): strips Go module path prefix, collapses subtests, excludes e2e/integration tests — IDs now match Multi-SWE-bench grader format.
- **Flake quarantine**: N-run validation with `quarantined_tests` / `flake_count` / `n_runs` on `ValidationResult`.
- **Per-`(repo, era)` image cache**: `GoImageCache` + deterministic `GoDockerfile.generate()`.
- **MSB harness cross-check**: 5 real etcd gold-patch runs; 1/5 unit-test instances resolved; parser gaps (SUBTEST_COLLAPSE, ID_PREFIX, E2E_TIMEOUT) found and fixed.

### RH dataset shaping (Epic 2 — all code merged)
- `fix_merge_date`, `provenance`, `link_confidence` on every emitted instance.
- RH issue-linking patterns: `rhbz#`, `OCPBUGS-`, `Resolves:` / `Fixes:` trailers, `Change-Id:`.
- Segmentation columns: `repo_language`, `product`, `n_fail_to_pass`, `patch_lines`, `files_touched`, `cross_file`, `env_spec_hash`, `image_name`, `n_runs`, `flake_count`, `quarantined_tests`.
- Decontamination overlap flag: `decontamination_overlap` + `decontamination_overlap_source`, configurable reference sets.
- `repo_products.json`: `kubernetes/kubernetes → OpenShift`, `etcd-io/etcd → OpenShift`.

### CI
- GitHub Actions: `pytest tests/ -q` on Python 3.11 + 3.12. **628 tests, 0 failures.**

---

## What is NOT done

### M0 fidelity gate — ⚠ NOT CLEARED

The M0 criterion: *deterministic Docker validation reproduces recorded F2P at ≥85% exact agreement on both repos.*

Blocked on:

| Prerequisite | Status |
|---|---|
| `ANTHROPIC_API_KEY` | **Not available** — Stage 3 (env discovery) and Stage 4 (validation) both require it |
| rh-swe-bench known-good instances | **Not in this repo** — need a JSONL with `pre_fix_output` + `post_fix_output` fields |
| End-to-end pipeline execution | **Never run for Go** — `output/` has 0 Go instances |

### Go dataset — ⚠ DOES NOT EXIST

`output/swebenchify-dataset.jsonl` contains **78 Python instances only** (Flask, Requests).  
There are **zero Go instances** in any output file.

---

## To emit the v1 slice

```bash
# 1. Set credentials
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...

# 2. Configure swebenchify.yaml (repos: kubernetes/kubernetes, etcd-io/etcd)
#    go_repos: [kubernetes/kubernetes, etcd-io/etcd]
#    pipeline.pr_after: "2024-01-01T00:00:00Z"   # post-cutoff
#    decontam_reference_paths:
#      - "swe-bench:./output/official-subset.jsonl"

# 3. Run the pipeline
swebenchify run -c swebenchify.yaml

# 4. Measure M0 fidelity against rh-swe-bench known-good
python scripts/validate_go_epic1.py m0 \
    --known-good /path/to/rh_swe_bench_go.jsonl

# 5. Full validation
python scripts/validate_go_epic1.py all \
    --known-good /path/to/rh_swe_bench_go.jsonl \
    --config swebenchify.yaml
```

`validate_go_epic1.py` auto-skips any check whose prerequisites are missing and reports clearly what passed vs. what was skipped.

---

## Known findings from pre-production validation

| Finding | Impact | Resolution |
|---|---|---|
| `kubernetes/kubectl` has 4 issue-linked PRs (all 2019) | Zero contamination-clean instances | Switched target to `kubernetes/kubernetes` |
| etcd is multi-module (`server/`, `pkg/`, `tests/`) | MSB's `go test ./...` from root misses all sub-module tests | Harness check script uses `cd {submodule}` |
| MSB regex collapses `TestFoo/case1` → `TestFoo` | F2P set mismatch on direct comparison | `normalize_go_f2p()` in `parsers.py` normalises our IDs |
| e2e/integration tests timeout at 5 min | Those instances appear invalid to both harnesses | `is_e2e_test_id()` excludes them from F2P |
| etcd requires Go ≥ 1.23; `golang:1.22` fails silently | Build succeeds, zero test output | MSB harness check uses `golang:latest` (1.26) |
