# Difficulties Encountered Mining Valid SWE-bench Instances

**Project:** SWE-benchify
**Date:** 2026-06-29
**Author:** Ari Aye

---

## Executive Summary

Mining valid SWE-bench instances — extracting real bug-fix pull requests from GitHub and converting them into reproducible coding-agent benchmark tasks — proved significantly harder than anticipated. What appears conceptually simple (find a bug fix, extract the patch, run the tests) runs headlong into the messy realities of software repositories: flaky tests, garbage-collected git objects, language-specific test conventions, silent toolchain failures, and a fundamental accuracy gap between agent-based and deterministic validation. This report catalogs the difficulties encountered across four supported languages (Python, Go, Rust, Java) and 182 commits of iterative fixes.

---

## 1. The Fundamental Validation Fidelity Gap

**The single biggest difficulty:** agent-based validation achieves only **56% exact FAIL_TO_PASS agreement** vs. Docker ground truth (81% subset match). The agent consistently catches the primary failing test but misses secondary ones that Docker finds.

This is not a prompt-engineering problem — it is intrinsic to the difference between an agent interpreting test output in a conversational loop vs. a deterministic parser processing structured output in a container. The gap meant that every instance validated by agent alone had a ~44% chance of having an incomplete or inaccurate FAIL_TO_PASS set, undermining the benchmark's trustworthiness.

**Resolution:** We had to build deterministic Docker-based validation pipelines for each language (Go, Rust, Java, Python), each with its own structured test output parser. This was a large investment that was not part of the original plan.

---

## 2. Patch Extraction: Separating Gold from Test

### 2.1 Language-Specific Test File Conventions

The original SWE-bench pipeline assumes Python conventions for identifying test files (paths containing `test/`, `tests/`, `e2e/`). Every new language brought surprises:

- **Go** uses `*_test.go` files co-located with source files in the same package. The substring-based detector false-positived on files like `latest.go`, `attestation/...`, and `contest.go`, while — more dangerously — missing legitimate `*_test.go` files entirely. Test hunks leaked into the gold patch, silently corrupting instances.

- **Rust** puts unit tests *inline* in source files via `#[cfg(test)] mod tests { ... }`. File-level classification is fundamentally wrong here — you need **hunk-level** detection that examines `@@` diff headers and surrounding context to determine whether a hunk belongs to a `#[cfg(test)]` block or production code.

- **Java/Maven** uses the `src/test/` directory convention, which at least is path-based, but still required explicit handling.

**Resolution:** We introduced a `LanguageBackend` abstraction with an `is_test_hunk` callback, and a `refine_patch_split()` pass that re-examines individual diff hunks using language-specific logic. This was one of the last features added (the Rust hunk-level splitting landed in the most recent commit).

### 2.2 False Positives from Generic Test Detection

The substring `test` in a file path is absurdly overloaded. Files matching the pattern that are not tests: `contest.go`, `latest.go`, `attestation_test_helper.go`, `testdata/` fixtures, `testing/` utility packages. Each false positive either excluded real code from the gold patch or incorrectly included non-test code in the test patch, either of which invalidates the instance.

---

## 3. GitHub API and Git Infrastructure Fragility

### 3.1 Garbage-Collected Merge Commits

GitHub's `merge_commit_sha` field on a PR points to a temporary test-merge commit that gets **garbage-collected** after the PR is merged. When we tried to `git checkout` that SHA weeks or months later during Docker image builds, the commit didn't exist. This cascaded into multiple failures:

- Docker builds failed during `git checkout`
- The `base_commit` derived from the merge commit was also unreachable
- Commit API calls to GitHub returned 404

**Resolution:** Required two separate fallbacks:
1. Fall back to GitHub's archive API to download code as a tarball and initialize a fresh git repo (sufficient for `git apply` operations)
2. Fall back to `pr.base.sha` (the base branch tip when the PR was opened) instead of deriving base_commit from the merge commit

### 3.2 Rate Limiting on Large Repositories

Collecting PR data from repositories like `kubernetes/kubernetes` (with tens of thousands of PRs) repeatedly hit GitHub API rate limits, leaving 5 repos with incomplete collection. Even with exponential backoff on 403/429 responses, the sheer volume of data required careful throttling and resumable checkpoints.

### 3.3 Issue-Linked PR Scarcity

Not every repository has a culture of linking PRs to issues. `kubernetes/kubectl` had only **4 issue-linked PRs, all from 2019** — yielding zero usable instances after freshness and contamination filters. We had to switch targets to `kubernetes/kubernetes` entirely.

---

## 4. Test Non-Determinism and Flakiness

### 4.1 The Flaky Test Problem

Flaky tests are the bane of benchmark mining. A test that passes sometimes and fails sometimes can appear in FAIL_TO_PASS on one validation run and disappear on the next. This is especially severe for:

- **etcd's raft and integration tests** — inherently timing-sensitive
- **Go tests using `t.Parallel()`** — race conditions surface non-deterministically
- **Any test touching the network or filesystem** — environment-dependent behavior

A single-run validation cannot distinguish a legitimate fix-induced test flip from random flakiness. Including flaky tests in FAIL_TO_PASS creates benchmark instances that are unreproducible.

**Resolution:** N-run flake quarantine — run each validation 3 times (configurable), intersect the result sets, and quarantine any test that appears in FAIL_TO_PASS on some runs but not all. If quarantining removes the instance's only FAIL_TO_PASS test, the instance is dropped entirely. This multiplies validation cost by 3x but is unavoidable.

### 4.2 E2E and Integration Test Timeouts

E2E and integration tests routinely exceeded the 5-minute validation timeout. These tests require live clusters, network access, or complex infrastructure that doesn't exist inside a validation container. Instances built around these tests appear invalid to both our harness and Multi-SWE-bench's.

**Resolution:** Regex-based exclusion of e2e/integration test IDs from FAIL_TO_PASS, restricting v1 to unit tests only.

---

## 5. Toolchain Version Hell

### 5.1 Silent Go Version Failures

etcd requires Go >= 1.23. When run with `golang:1.22`, the build **succeeds silently** but produces **zero test output**. The instance appears to have no tests at all — a completely misleading failure mode with no error message.

**Resolution:** `GoEnvironmentSpec` now detects the exact Go version from `go.mod`'s `go` directive and ensures the correct toolchain version. But discovering this failure mode required extensive debugging because there was literally no error to go on.

### 5.2 Python Version Detection Pitfalls

Auto-detection from `pyproject.toml` can pick ancient versions (e.g., Python 2.7) whose `python:X.Y-slim` Docker images don't exist on Docker Hub, causing 100% build failures for those instances.

**Resolution:** Clamp detected versions to >= 3.9, with a fallback to 3.11 if the detected version is older. Also: use the highest CI/tox version, not the minimum.

### 5.3 Multi-Module Go Repositories

etcd is a multi-module Go repository with code split across `server/`, `pkg/`, and `tests/` directories. Running `go test ./...` from the repository root misses all sub-module tests because Go treats each `go.mod` as a separate module boundary.

**Resolution:** The test runner must `cd` into each sub-module directory and run tests separately, then aggregate results.

---

## 6. Test ID Format Incompatibilities

### 6.1 Go Subtest Normalization

Multi-SWE-bench's regex collapses Go subtests like `TestFoo/case1` into `TestFoo`, stripping the subtest suffix. When comparing FAIL_TO_PASS sets directly, every subtest-level test ID appears as a mismatch even though the same tests are being described.

**Resolution:** `normalize_go_f2p()` normalizes our IDs to match Multi-SWE-bench's format — but this is a lossy normalization that makes it impossible to distinguish which subtest actually failed.

### 6.2 Go Module Path Prefixes

Go test IDs include the full module path (`github.com/etcd-io/etcd/server/v3/...`), which needs to be stripped for comparison with other harnesses that use shorter relative paths.

---

## 7. Test Output Parsing Fragility

### 7.1 Regex-Based Parsing is Unreliable

Parsing `go test -v` verbose text output with regex is fragile. Subtests, parallel package output, build errors vs. test failures, and stdout noise all create ambiguous cases. This was a known failure mode that directly contributed to the validation fidelity gap.

**Resolution:** `GoJSONParser` uses `go test -json`, which emits structured NDJSON events with explicit `Action` (pass/fail/skip/output), `Test`, and `Package` fields. This required 24 unit tests to get right but eliminated the parsing ambiguity.

### 7.2 Rust Compile Errors vs. Test Failures

Rust compile errors produce `error[E...]` output, not `FAILED`. The original `failure_grep` pattern only looked for `FAILED`, meaning pre-fix compile errors were missed and incorrectly classified.

**Resolution:** Include Rust compile error patterns (`error[E` prefix) in the failure detection regex.

---

## 8. Docker and Container Infrastructure

### 8.1 Podman Rootless Mode Incompatibility

Dockerfiles written for Docker didn't work under podman's rootless mode (used by Red Hat's ATIF trajectory generation). Issues included `git safe.directory` not being set, detached HEAD vs. branch reference handling, and `main` branch creation assumptions.

### 8.2 Artifact Name Sanitization

GitHub Actions artifact names cannot contain forward slashes. Repository names like `ansible/galaxy_ng` were used directly as artifact names, causing 100% upload failure for all pipeline runs until the slashes were replaced with underscores.

### 8.3 Batch Size Overflow

Large patches (hypershift repository produced ~466KB per candidate) caused manifest files to exceed GitHub's 100MB file size limit during remote validation. Fixed by splitting batches by estimated serialized size (90MB cap) instead of fixed candidate count.

### 8.4 Image Visibility

GHCR images don't inherit repository visibility automatically. Every pushed image required explicit visibility setting to `public` after push, plus OCI source labels to link back to the repository.

### 8.5 Docker Build Timeouts

15 out of 20 instances timed out during Docker validation in early runs. Timeout escalation from 50 minutes to 8 hours was needed for complex multi-agent workflows.

---

## 9. Unsolvable Instance Detection

### 9.1 New Symbol Introduction

FAIL_TO_PASS tests that call functions or classes first introduced in the gold patch are unsolvable — a coding agent cannot guess the exact function name the developer chose. These tests are test-dependent on the specific implementation, not on the bug fix behavior.

**Resolution:** `check_new_symbol_in_tests()` and `check_go_introduced_symbol()` filters parse the gold patch for newly introduced symbols and check whether FAIL_TO_PASS tests reference them. If so, the instance is excluded.

### 9.2 Pre-Fix Dependency Errors

Pre-solution test logs containing `ImportError` or `AttributeError` indicate environment/dependency issues, not real bugs fixable by a code patch. These are the original SWE-bench paper's filters — but they were **missing from our initial implementation** and had to be added retroactively.

### 9.3 Problem Statement Quality

Instances with vague or content-free problem statements (< 40 words) are effectively unsolvable. Additional filters exclude problem statements containing raw URLs or commit SHAs, which would leak hints about the solution.

---

## 10. Rust-Specific Difficulties

### 10.1 The Revert

The entire initial Rust support PR (1,711 lines) was reverted after integration issues. The revert deleted `RustDockerfile`, `RustImageCache`, `rust_grader`, and all Rust tests. Rust support had to be rebuilt from scratch using the newer `LanguageBackend` abstraction.

### 10.2 Inline Test Blocks

Rust's `#[cfg(test)]` convention means tests live *inside* the source file, not in separate test files. This breaks every assumption about file-level patch splitting. Hunk-level analysis of `@@` headers was required to correctly identify which parts of a diff are test code vs. production code — a fundamentally harder problem than file-level classification.

---

## 11. Cross-System Contract Maintenance

### 11.1 Parser-Contract Drift

SWE-benchify validates instances; Multi-SWE-bench grades agent solutions against them. Both must use the **identical** `GoJSONParser`. If the parser implementations diverge, an instance validated in this pipeline could grade differently downstream — a silent correctness bug in the benchmark itself.

**Mitigation:** The parser is a single shared module with its own test suite, imported (not reimplemented) by both sides. Any parser change is treated as a cross-repository contract change.

### 11.2 Schema Evolution Constraints

All schema changes must be additive-only — never breaking. Go instances must remain valid `SWEbenchInstance` rows even though they can't pass through the Python-only `make_test_spec` machinery. This required a carefully defined "producer-only Go" conformance target separate from the Python conformance target.

---

## 12. Cost and Scale Challenges

### 12.1 Agent Budget Consumption

Environment discovery costs up to $5.00 per repository version (80 turns). Validation costs up to $3.00 per instance (60 turns). At scale across hundreds of PRs and multiple repositories, agent costs become significant — especially when validation must run 3x for flake quarantine.

### 12.2 The Long Tail of Edge Cases

Every new repository and every new language surfaced novel edge cases. The git history shows a pattern: a capability is built, tested on one or two repos, then breaks on the third in ways that required fundamental rethinking (not just bug fixes). kubectl → kubernetes target switch, etcd multi-module discovery, Rust inline tests, hypershift batch overflow — each was a surprise that consumed days of debugging.

---

## Summary: Why Instance Mining is Hard

The core difficulty is that SWE-bench instances must satisfy a conjunction of many properties simultaneously:

1. The PR must fix a real bug (not a refactor, feature, or docs change)
2. The PR must be linked to an issue (with a sufficiently detailed problem statement)
3. The patch must be cleanly separable into gold code and test code
4. The test code must fail before the fix and pass after
5. The test failures must be deterministic (not flaky)
6. The environment must be reproducible in a container
7. The correct toolchain version must be detected and available
8. The test output must be parseable into individual test pass/fail verdicts
9. The failing tests must not reference symbols introduced by the fix
10. The instance must not overlap with existing benchmark datasets

Each property has a non-trivial failure rate. When you multiply them together, the yield from raw PRs to valid instances is low — and debugging *which* property failed on a specific instance requires understanding the full pipeline end-to-end.

The project's 182 commits, 628 tests, and four language backends are testament to the iterative discovery of these failure modes. What looked like a mechanical extraction task turned out to require deep understanding of each language's testing conventions, each repository's build system, and the many ways that git, Docker, and GitHub's API can produce subtly incorrect results.
