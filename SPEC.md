# SWE-benchify Service Specification

Status: Draft v2

Purpose: Define a system that automatically transforms GitHub repositories
into SWE-bench-compatible benchmarks, producing datasets that are
evaluable through the standard SWE-bench Docker-based harness.

## Normative Language

The key words `MUST`, `MUST NOT`, `REQUIRED`, `SHOULD`, `SHOULD NOT`,
`RECOMMENDED`, `MAY`, and `OPTIONAL` in this document are to be interpreted
as described in RFC 2119.

## 1. Problem Statement

[SWE-bench](https://github.com/princeton-nlp/SWE-bench) is the standard
benchmark for evaluating coding agents on real-world software engineering
tasks. Its pipeline produces high-quality datasets but relies on
**manually authored environment specs** (`MAP_VERSION_TO_INSTALL`) for
each repository and version — a bottleneck that limits the benchmark to
a curated set of repositories.

SWE-benchify automates this bottleneck. Given a list of GitHub
repositories, it produces a dataset that:

1. Conforms to the `SWEbenchInstance` schema.
2. Passes `swebench.harness.test_spec.make_test_spec` validation.
3. Is evaluable through `swebench.harness.run_evaluation` with Docker
   (or podman).
4. When run against the same repositories SWE-bench uses, produces a
   statistically similar dataset — same instance_ids, comparable
   FAIL_TO_PASS, comparable difficulty distribution.

The system delegates environment discovery and test validation to a
coding agent (Claude Code) that explores repositories, installs
dependencies, runs tests, and debugs failures — replacing the manual
curation that SWE-bench requires.

### 1.1 Design Principles

1. **SWE-bench compatibility is the target.** Output MUST be usable with
   the unmodified SWE-bench evaluation harness. We are a dataset producer,
   not an alternative evaluation framework.

2. **Dual-mode validation.** For repositories already in SWE-bench, the
   system SHOULD validate using Docker with SWE-bench's own specs (to
   ensure identical results). For new repositories, the system uses
   agent-based discovery and validation.

3. **Agent as curator.** The coding agent replaces manual curation, not
   deterministic scripts. It handles the judgment-intensive parts:
   environment setup, test debugging, version detection.

4. **Reproducibility through containers.** Validation and evaluation MUST
   run in isolated containers to ensure reproducible results across
   environments.

### 1.2 Non-Goals

- Evaluation harness or coding-agent benchmark runner. Use SWE-bench's
  harness for evaluation.
- Model inference or LLM-generated patches.
- Web UI, leaderboard, or dashboard.
- Custom agent framework. Claude Code provides all agent capabilities.

## 2. Architecture

### 2.1 Two Modes of Operation

**Known-repo mode** (repositories already in SWE-bench):

The system uses SWE-bench's existing `MAP_REPO_VERSION_TO_SPECS` and
`environment_setup_commit` data. Validation runs through Docker using
SWE-bench's harness directly. This mode exists to verify that our
mechanical stages (PR collection, patch extraction) produce datasets
equivalent to SWE-bench's.

**New-repo mode** (arbitrary repositories):

The system dispatches a Claude Code agent to discover the environment
setup. The agent produces a spec equivalent to `MAP_VERSION_TO_INSTALL`
entries. Validation runs through the agent or through Docker using the
agent-generated spec.

### 2.2 Components

| Component | Responsibility |
|-----------|---------------|
| **Pipeline Controller** | Stage sequencing, concurrency, resumption |
| **PR Collector** | GitHub API: fetch merged PRs with linked issues |
| **Patch Extractor** | Split diffs into gold/test patches, fetch problem statements |
| **Version Detector** | Mechanical version detection from metadata files |
| **Agent Dispatcher** | Launch Claude Code sessions, collect output, handle retries |
| **Environment Discovery Agent** | Discover build/test/install setup for a repo version |
| **Instance Validator** | Compute FAIL_TO_PASS and PASS_TO_PASS |
| **SWE-bench Compatibility Layer** | Version snapping, environment_setup_commit, TestSpec validation |
| **Quality Filter** | Deterministic filters + LLM judge (quality assessment) |
| **Dataset Emitter** | JSONL serialization conforming to SWEbenchInstance |

### 2.3 External Dependencies

- GitHub API (REST v3) for PR and issue data.
- Claude Code Agent SDK (Python) for dispatching agent sessions.
- Git CLI for repository cloning and worktree management.
- SWE-bench package for TestSpec validation, Docker evaluation, and
  known-repo environment specs.
- Container runtime (Docker or podman) for sandboxed validation and
  evaluation.

## 3. Core Domain Model

### 3.1 CandidatePR

A merged pull request that references at least one issue.

Fields: `repo`, `pr_number`, `title`, `body`, `base_commit`,
`merge_commit`, `diff_url`, `resolved_issues`, `created_at`, `merged_at`.

### 3.2 CandidateInstance

A CandidatePR augmented with extracted patches and problem statement.

Fields: `instance_id` (`{owner}__{repo}-{pr_number}`), `patch` (gold),
`test_patch`, `problem_statement`, `hints_text`, plus CandidatePR fields.

### 3.3 EnvironmentSpec

Build and test configuration for a repository version. This is the
agent-generated equivalent of a `MAP_VERSION_TO_INSTALL` entry.

Fields: `language`, `language_version`, `package_manager`, `install_cmd`,
`test_cmd`, `pre_install`, `system_dependencies`.

For SWE-bench compatibility, an EnvironmentSpec SHOULD be convertible to
a `MAP_VERSION_TO_INSTALL` entry with fields: `python`, `packages`,
`install`, `pip_packages`, `test_cmd`.

### 3.4 TaskInstance

A validated benchmark instance conforming to the SWE-bench schema.

Fields: `repo`, `instance_id`, `base_commit`, `patch`, `test_patch`,
`problem_statement`, `hints_text`, `created_at`, `version`,
`FAIL_TO_PASS` (JSON-encoded list), `PASS_TO_PASS` (JSON-encoded list),
`environment_setup_commit`.

This schema MUST conform to the `SWEbenchInstance` TypedDict from
`swebench.harness.constants`. Every emitted instance MUST produce a valid
`TestSpec` via `swebench.harness.test_spec.make_test_spec`.

### 3.5 QualityScore

LLM judge assessment following the SWE-bench Verified annotation protocol.

Fields: `q1_specificity` (0-3), `q2_test_scope` (0-3), `q3_other_issues`
(0/1), `difficulty` (enum), `reasoning` (string).

An instance is "verified quality" if max(q1) <= 1, max(q2) <= 1,
q3 = 0 across multiple judge passes.

## 4. Pipeline Specification

### 4.1 Stage Overview

| Stage | Name | Type | Description |
|-------|------|------|-------------|
| 1 | PR Collection | Mechanical | Fetch merged PRs with linked issues |
| 2 | Patch Extraction | Mechanical | Split diffs, fetch problem statements |
| 3 | Environment Discovery | Agentic | Discover build/test setup per version |
| 4 | Instance Validation | Agentic or Docker | Compute FAIL_TO_PASS / PASS_TO_PASS |
| 4.5 | Quality Assessment | Agentic | LLM judge scores instance quality |
| 5 | Quality Filtering | Mechanical | Deterministic + quality-score filters |
| 6 | Dataset Emission | Mechanical | Write SWE-bench-compatible JSONL |

### 4.2 Stages 1-2: PR Collection and Patch Extraction

Mechanical stages. See SPEC v1 Sections 5.2-5.3 for detailed behavior.

Key requirements:
- Issue extraction regex: `(close[sd]?|fix(e[sd])?|resolve[sd]?) #?(\d+)`
- Test file detection: path contains `test`, `tests`, `e2e`, `testing`,
  or `src/test/` (Java convention)
- `base_commit`: first parent of the merge commit (not base branch HEAD)
- Rate limiting with exponential backoff on 403 and 429
- Resumable via checkpoint files

### 4.3 Stage 3: Environment Discovery

For each unique `(repo, version)` pair, the harness discovers the
build/test environment.

**Known-repo mode:** Look up the spec from
`MAP_REPO_VERSION_TO_SPECS`. No agent needed.

**New-repo mode:** Dispatch a Claude Code agent to:
1. Identify language, build system, package manager.
2. Install the project and dependencies.
3. Find and verify the test command.
4. Extract the version from metadata files.
5. Write `env_spec.json` and `version.json`.

The agent's output SHOULD be validated by actually running the test
command and confirming it produces parseable output.

Caching: specs are cached by `(repo, version)`.

### 4.4 Stage 4: Instance Validation

For each candidate instance, compute FAIL_TO_PASS and PASS_TO_PASS by
running tests before and after applying the gold patch.

**Docker-based validation** (preferred for known repos):

1. Build a Docker image per the SWE-bench spec.
2. Apply test_patch to the codebase at base_commit.
3. Run tests → record failures (FAIL_TO_PASS candidates).
4. Apply gold patch.
5. Run tests → record passes.
6. FAIL_TO_PASS = tests that failed in step 3 and pass in step 5.

**Agent-based validation** (for new repos):

Same logic, but the agent handles environment setup, test execution,
and output parsing inside a workspace.

**Post-validation filters** (from the SWE-bench paper):

- Discard instances where pre-solution test logs contain `ImportError`
  or `AttributeError` (indicates dependency issues, not real bugs).
- Discard instances where FAIL_TO_PASS tests call functions or classes
  first introduced in the gold patch (arbitrary naming, unsolvable).

### 4.5 Stage 4.5: Quality Assessment

An LLM judge evaluates each instance following the SWE-bench Verified
annotation protocol:

- **Q1 (Specificity, 0-3):** How well-specified is the problem statement?
- **Q2 (Test Scope, 0-3):** Are tests well-scoped for alternative
  solutions, or do they only accept the exact gold patch?
- **Q3 (Other Issues, 0/1):** Any other problems (e.g., tests gameable,
  solution leakage)?

The judge prompt SHOULD include few-shot examples from SWE-bench Verified
annotations for calibration.

Instances with q1 > 1 or q2 > 1 or q3 = 1 are flagged for review or
exclusion.

### 4.6 Stages 5-6: Filtering and Emission

See SPEC v1 Sections 5.6-5.7. Additional filter: exclude instances
flagged by the quality assessment (Stage 4.5).

Output MUST include `environment_setup_commit` for every instance.
For known repos, use the value from SWE-bench's dataset. For new repos,
derive from git tags or version-specific commits.

## 5. SWE-bench Compatibility

### 5.1 Output Conformance

Every emitted instance MUST:

1. Parse as a valid `SWEbenchInstance` TypedDict.
2. Produce a valid `TestSpec` via `make_test_spec()`.
3. Have a `version` that exists in `MAP_REPO_VERSION_TO_SPECS` (for known
   repos) or in an agent-generated spec registry (for new repos).
4. Have a non-null `environment_setup_commit`.

### 5.2 Version Snapping

For known repos, detected versions MUST be snapped to the closest
version supported by `MAP_REPO_VERSION_TO_SPECS`. For example, detected
version `2.3.1` snaps to `2.3` if `2.3` is a supported version.

Instances whose version cannot be snapped to a supported version are
excluded from the output (for known repos) or require an agent-generated
spec (for new repos).

### 5.3 Docker Spec Generation (New Repos)

For new repositories, the environment discovery agent MUST produce a
spec that is functionally equivalent to a `MAP_VERSION_TO_INSTALL`
entry. This spec MUST include:

- Python version (or equivalent runtime version)
- Installation command
- Test command
- Pinned dependency versions (RECOMMENDED)
- Pre-install steps (OPTIONAL)

The generated spec MUST be sufficient for the SWE-bench harness to build
a Docker image and run tests in isolation.

### 5.4 Evaluation

Evaluation of coding agents against the generated dataset is performed
using `swebench.harness.run_evaluation`. SWE-benchify provides:

1. The dataset file (`swebenchify-dataset.jsonl`).
2. A prediction generation script that dispatches Claude Code (or any
   agent) to produce patches in SWE-bench's prediction format.

The evaluation itself runs in Docker containers managed by SWE-bench,
ensuring sandboxed, reproducible results.

## 6. Configuration

### 6.1 Schema

```yaml
repos:
  - owner/repo

github:
  token: $GITHUB_TOKEN
  tokens:
    owner/private-repo: $PRIVATE_TOKEN

pipeline:
  max_concurrent_repos: 4
  max_concurrent_validations: 8
  max_prs_per_repo: null
  pr_after: "2020-01-01T00:00:00Z"
  pr_before: "2025-01-01T00:00:00Z"

agent:
  max_attempts: 3
  env_discovery:
    max_turns: 80
    budget_usd: 5.0
  validation:
    max_turns: 60
    budget_usd: 3.0
  quality_eval:
    max_turns: 20
    budget_usd: 0.50

filters:
  min_problem_statement_words: 40
  max_patch_lines: 500
  no_urls_in_problem: true
  no_shas_in_problem: true

output:
  dir: ./output
```

## 7. Agent Dispatcher Protocol

The Agent Dispatcher uses the Claude Code Agent SDK (Python) to launch
coding agent sessions. See SPEC v1 Section 7 for detailed protocol.

Key additions:

- The SDK raises an exception after emitting `ResultMessage` on
  `error_max_turns`. The dispatcher MUST check for a received
  `ResultMessage` before treating the exception as a failure.
- `max_budget_usd` is passed via `extra_args={"max-budget-usd": ...}`,
  not as a named `ClaudeCodeOptions` field.

## 8. Quality Assessment Protocol

### 8.1 Annotation Dimensions

Following SWE-bench Verified (OpenAI, 2024):

**Q1 — Problem Statement Specificity (0-3):**
- 0: Well-specified, clear what a successful solution requires
- 1: Some blanks, but a sensible interpretation exists
- 2: Vague, unclear what success looks like
- 3: Almost impossible to understand without more information

**Q2 — Test Scope (0-3):**
- 0: Tests cover all possible correct solutions
- 1: Tests cover most solutions, unusual ones may be missed
- 2: Some reasonable solutions would fail the tests
- 3: Tests are too narrow/broad or test something different

**Q3 — Other Issues (0/1):**
- 0: No major issues
- 1: Major issues (e.g., tests gameable, solution leakage)

### 8.2 LLM Judge Calibration

The judge SHOULD be calibrated on instances from SWE-bench Verified
where human annotations are available. Target: >=80% agreement with
human annotators on the admit/reject decision (max Q1 <= 1,
max Q2 <= 1, Q3 = 0).

## 9. Conformance Tests

### 9.1 Mechanical Stage Conformance

When run against the repositories in the SWE-bench dataset with matching
date ranges, the mechanical stages (1-2) SHOULD produce a dataset with
>=90% overlap on `instance_id` values with the published SWE-bench
dataset.

### 9.2 Validation Conformance

For instances that overlap with SWE-bench, the `FAIL_TO_PASS` lists
SHOULD match with >=85% agreement.

### 9.3 Docker Spec Generation Conformance

For known repositories, agent-generated environment specs SHOULD produce
test results identical to SWE-bench's manually authored specs on >=80%
of test instances.

### 9.4 Evaluation Conformance

When three models of known relative capability (e.g., haiku < sonnet <
opus) are evaluated against the generated dataset using the SWE-bench
Docker harness, the resolve rates SHOULD reflect the expected ordering.
