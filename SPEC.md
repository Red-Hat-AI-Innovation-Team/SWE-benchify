# SWE-benchify Service Specification

Status: v1.0

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

Conformance results (Phase 1):
- Mechanical stages: 99.7% instance_id overlap on 8 completed repos
- Docker validation: gold patches resolve through unmodified harness
- Agent ranking: haiku(3%) < sonnet(10%) < opus(65%)

**New-repo mode** (arbitrary repositories):

The system dispatches a Claude Code agent to discover the environment
setup. The agent produces a spec equivalent to `MAP_VERSION_TO_INSTALL`
entries. Validation runs through the agent or through Docker using the
agent-generated spec.

Conformance results (Phase 1):
- Spec generation: 86% field match vs SWE-bench ground truth (4 repos)
- Functional equivalence: 99.6% pass-set overlap (Flask v2.3)

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
- Go toolchain (for Go repositories): used during Docker-based validation;
  the discovery agent is read-only and requires no local Go installation.
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

Build and test configuration for a repository version. Two specialisations
exist, selected by the repository's detected language.

**Python — `EnvironmentSpec`:** agent-generated equivalent of a
`MAP_VERSION_TO_INSTALL` entry.

Fields: `language`, `language_version`, `package_manager`, `install_cmd`,
`test_cmd`, `pre_install`, `system_dependencies`.

For SWE-bench compatibility, an EnvironmentSpec SHOULD be convertible to
a `MAP_VERSION_TO_INSTALL` entry with fields: `python`, `packages`,
`install`, `pip_packages`, `test_cmd`.

**Go — `GoEnvironmentSpec`:** derived by inspecting `go.mod`, `Makefile`,
and CI configuration. No installation is performed during discovery.

Fields: `language` (`"go"`), `go_version` (from `go.mod` `go` directive,
e.g. `"1.22"`), `build_cmd`, `test_cmd`, `module_mode` (`"modules"` |
`"vendored"`), `goflags`, `system_dependencies`, `env_spec_hash` (stable
SHA-256 of all other fields — used as the Docker image cache key).

A `GoSpecRegistry` (persisted as `go-spec-registry.json` in the workspace)
maps each `env_spec_hash` to a stable `version_string` of the form
`"{go_version}-{hash[:8]}"` (e.g. `"1.22-ab3f1200"`) and to the
`era_commit` — the earliest commit at which that spec was valid.

### 3.4 TaskInstance

A validated benchmark instance conforming to the SWE-bench schema.

Core SWE-bench fields: `repo`, `instance_id`, `base_commit`, `patch`,
`test_patch`, `problem_statement`, `hints_text`, `created_at`, `version`,
`FAIL_TO_PASS` (JSON-encoded list), `PASS_TO_PASS` (JSON-encoded list),
`environment_setup_commit` (non-null for all emitted instances).

Additive columns (not required by SWE-bench, used for dataset shaping):
`fix_merge_date`, `provenance`, `link_confidence`, `repo_language`,
`product`, `n_fail_to_pass`, `patch_lines`, `files_touched`, `cross_file`,
`env_spec_hash`, `n_runs`, `flake_count`, `quarantined_tests`,
`decontamination_overlap`, `decontamination_overlap_source`.

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
build/test environment. The language is detected mechanically from the
repository root (presence of `go.mod` → Go; otherwise → Python).

**Known-repo mode (Python):** Look up the spec from
`MAP_REPO_VERSION_TO_SPECS`. No agent needed.

**New-repo mode — Python:** Dispatch a Claude Code agent to:
1. Identify language, build system, package manager.
2. Install the project and dependencies.
3. Find and verify the test command.
4. Extract the version from metadata files.
5. Write `env_spec.json` and `version.json`.

The agent's output SHOULD be validated by actually running the test
command and confirming it produces parseable output.

**New-repo mode — Go:** Dispatch a lightweight read-only Claude Code agent
to inspect `go.mod`, `Makefile`, and `.github/workflows/`. No installation
is performed. The agent writes `go_env_spec.json` and `version.json`.
The resulting `GoEnvironmentSpec` is registered in the `GoSpecRegistry`
(keyed on its `env_spec_hash`) to produce a stable `version_string` and
`era_commit` (used as `environment_setup_commit`). Budget is $2.00 /
40 turns vs $5.00 / 80 turns for Python discovery.

Caching: Python specs are cached by `(repo, version)`; Go specs are cached
by `(repo, env_spec_hash)`.

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
3. Have a `version` that exists in `MAP_REPO_VERSION_TO_SPECS` (for Python
   known repos), in an agent-generated spec registry (for new Python repos),
   or in the `GoSpecRegistry` (for Go repos, as a `"{go_version}-{hash[:8]}"` string).
4. Have a non-null `environment_setup_commit`. For Python known repos this
   comes from SWE-bench's dataset; for new Python repos it is derived from
   git tags or version-specific commits; for Go repos it is the `era_commit`
   from the `GoSpecRegistry` (earliest commit whose `go.mod` `go` directive
   matches the discovered `go_version`).

### 5.2 Version Snapping

For known repos, detected versions MUST be snapped to the closest
version supported by `MAP_REPO_VERSION_TO_SPECS`. For example, detected
version `2.3.1` snaps to `2.3` if `2.3` is a supported version.

Instances whose version cannot be snapped to a supported version are
excluded from the output (for known repos) or require an agent-generated
spec (for new repos).

### 5.3 Docker Spec Generation

#### Python (MAP_VERSION_TO_INSTALL)

For new Python repositories, the environment discovery agent produces a spec
that is functionally equivalent to a `MAP_VERSION_TO_INSTALL` entry.
This is a first-class feature of SWE-benchify — it automates the manual
curation step that limits SWE-bench to its curated repository set.

The agent MUST produce a spec with these fields:

| Field | Required | Description |
|-------|----------|-------------|
| `python` | YES | Target Python version (highest from CI/tox) |
| `install` | YES | Installation command (`pip install .`) |
| `test_cmd` | YES | Test command (`pytest -rA`) |
| `pip_packages` | RECOMMENDED | Pinned dependency versions from `pip freeze` |
| `pre_install` | OPTIONAL | System setup commands (apt-get only) |

The agent prompt instructs:
1. Detect Python version from CI matrix or tox envlist (highest version)
2. Install without virtual environments (runs in Docker)
3. Extract pinned deps via `pip freeze`
4. Use simplest test command form

**Benchmarked accuracy** (Phase 1.1, 14 versions across 4 repos):

| Field | Match Rate |
|-------|-----------|
| python | 75% |
| install | 100% |
| test_cmd | 95% |
| pip_packages | 75% |
| pre_install | 83% |
| **Overall** | **86%** |

#### Go (GoEnvironmentSpec)

For Go repositories, the discovery agent is read-only — it only inspects
`go.mod`, `Makefile`, and CI YAML. No installation or virtual environments
are involved.

The agent MUST produce a `go_env_spec.json` with these fields:

| Field | Required | Description |
|-------|----------|-------------|
| `go_version` | YES | Version from `go.mod` `go` directive (e.g. `"1.22"`) |
| `test_cmd` | YES | Test entry point (`go test ./...`, `make test`, etc.) |
| `module_mode` | YES | `"modules"` or `"vendored"` |
| `build_cmd` | RECOMMENDED | Build entry point (`make build`, `go build ./...`) |
| `goflags` | RECOMMENDED | Extra flags (e.g. `"-mod=vendor"` for vendored repos) |
| `system_dependencies` | OPTIONAL | apt packages discovered in CI YAML |

The `env_spec_hash` (SHA-256 of all other fields, sorted) serves as the
Docker image cache key. A per-spec image is built once and reused for all
instances that share the same Go toolchain configuration.

`environment_setup_commit` is derived by scanning `git log` for the
earliest commit whose `go.mod` `go` directive matches `go_version`, making
instances reproducible at the exact toolchain era they were authored against.

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

**Measured:** 99.7% overlap (1037/1039) on 8 completed repos. Per-repo
rates: astropy 100%, matplotlib 99%, seaborn 100%, flask 100%,
requests 98%, xarray 100%, sphinx 100%, sympy 100%.

### 9.2 Validation Conformance

For instances that overlap with SWE-bench, the `FAIL_TO_PASS` lists
SHOULD match with >=85% agreement.

**Measured (agent-based):** 56% exact match, 81% subset match on 16
instances. The gap is intrinsic to agent-vs-Docker validation
environments — the agent misses secondary failing tests that Docker
catches.

**Measured (Docker-based):** Gold patches resolve correctly through the
unmodified SWE-bench harness (5/5 tested). Docker validation produces
correct FAIL_TO_PASS when env images build successfully.

### 9.3 Docker Spec Generation Conformance

For known repositories, agent-generated environment specs SHOULD produce
test results identical to SWE-bench's manually authored specs on >=80%
of test instances.

**Measured:** 86% structural match across 14 versions (Flask, Requests,
pytest, xarray). 99.6% functional equivalence on Flask v2.3 (479/481
tests match).

### 9.4 Evaluation Conformance

When three models of known relative capability (e.g., haiku < sonnet <
opus) are evaluated against the generated dataset using the SWE-bench
Docker harness, the resolve rates SHOULD reflect the expected ordering.

**Measured:** haiku 3% (1/30) < sonnet 10% (1/10) < opus 65% (13/20).
Monotonic ordering confirmed.

## 10. Ground Truth Initialization

### 10.1 Purpose

Mine landed changes from a repository's git history into reusable JSONL
artifacts. These artifacts capture the full context of each change —
patches, descriptions, linked issues, and provenance — enabling
downstream tasks such as benchmark generation, taxonomy classification,
and dataset quality analysis.

The pipeline operates on **local git history first**, falling back to the
GitHub API only when metadata (issue bodies, PR descriptions, review
comments) is missing from the local clone.

### 10.2 Pipeline Stages

| Stage | Name | Description |
|-------|------|-------------|
| 1 | Repository Preparation | Clone or update the target repository; resolve branch |
| 2 | Landed Change Enumeration | Walk merge commits and direct pushes on the target branch |
| 3 | Change Normalization | Normalize each landed change into a `GroundTruthChange` |
| 4 | Patch Extraction & Categorization | Split the full diff into 5 categories: code, test, doc, tooling, agent_instruction |
| 5 | Description & Provenance Extraction | Gather descriptions from issues, PR bodies, commit messages, review comments, ADRs, docs, release notes |
| 6 | Quality Checks | Validate patch integrity, description completeness, link confidence |
| 7 | Emission | Write JSONL output artifacts and summary report |

### 10.3 Patch Categories

Each landed change's full diff is split into five non-overlapping patch
categories:

| Category | Description |
|----------|-------------|
| `code` | Production source code changes |
| `test` | Test file changes (files matching test detection heuristics) |
| `doc` | Documentation changes (README, docs/, *.md, *.rst, etc.) |
| `tooling` | Build system, CI/CD, configuration file changes |
| `agent_instruction` | Changes to AI agent instructions, prompts, or CLAUDE.md files |

### 10.4 Data Models

#### GroundTruthChange

Represents a single landed change extracted from repository history.

| Field | Type | Description |
|-------|------|-------------|
| `repo` | `str` | Repository full name (owner/repo) |
| `change_id` | `str` | Unique identifier: `pr:<number>`, `commit:<sha>`, `merge:<sha>` |
| `change_kind` | `str` | One of: `pull_request`, `direct_commit`, `merge_commit`, `squash_commit`, `patch_series`, `unknown` |
| `base_commit` | `str` | Commit SHA before the change |
| `head_commit` | `str` | Commit SHA after the change |
| `merge_commit` | `str` | Merge commit SHA (if applicable) |
| `landed_at` | `str` | ISO 8601 timestamp when the change landed |
| `title` | `str` | Change title (PR title or first commit message line) |
| `body` | `str` | Change body (PR body or commit message body) |
| `description_sources` | `list[DescriptionSource]` | All gathered description sources |
| `linked_issues` | `list[str]` | GitHub issue numbers, Jira IDs, or URLs |
| `review_sources` | `list[str]` | URLs or references to code review comments |
| `full_diff` | `str` | Complete unified diff |
| `code_patch` | `str \| None` | Production code portion of the diff |
| `test_patch` | `str \| None` | Test portion of the diff |
| `doc_patch` | `str \| None` | Documentation portion of the diff |
| `tooling_patch` | `str \| None` | Tooling/CI portion of the diff |
| `agent_instruction_patch` | `str \| None` | Agent instruction portion of the diff |
| `changed_files` | `list[str]` | List of all changed file paths |
| `link_confidence` | `float` | Confidence score for issue-PR linkage (0.0–1.0) |
| `extraction_warnings` | `list[str]` | Warnings generated during extraction |

#### DescriptionSource

Represents a single source of descriptive text for a change.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source_kind` | `str` | — | One of: `issue`, `pr_body`, `commit_message`, `review_comment`, `issue_comment`, `adr`, `doc`, `release_note`, `derived_summary` |
| `source_id` | `str` | — | URL, issue number, commit SHA, or file path |
| `created_at` | `str` | — | ISO 8601 timestamp |
| `text` | `str` | — | The descriptive text content |
| `allowed_for_task_prompt` | `bool` | `True` | Whether this source can be used in task prompts |
| `leakage_risk` | `str` | `'none'` | Risk of solution leakage: `none`, `low`, `medium`, `high` |
| `notes` | `str` | `''` | Additional notes about this source |

### 10.5 Output Contract

The ground truth pipeline produces four output artifacts:

| File | Format | Description |
|------|--------|-------------|
| `ground-truth-changes.jsonl` | JSONL | One `GroundTruthChange` per line |
| `ground-truth-descriptions.jsonl` | JSONL | One `DescriptionSource` per line (denormalized) |
| `ground-truth-files.jsonl` | JSONL | Per-file change records |
| `ground-truth-report.md` | Markdown | Human-readable summary with statistics |

### 10.6 CLI Commands

| Command | Description |
|---------|-------------|
| `swebenchify ground-truth collect` | Enumerate and normalize landed changes |
| `swebenchify ground-truth extract` | Extract patches, descriptions, and provenance |
| `swebenchify ground-truth emit` | Write JSONL output artifacts |
| `swebenchify ground-truth run` | Run the full ground truth pipeline (collect → extract → emit) |

### 10.7 Design Principles

1. **Local-first data access.** Extract as much as possible from the
   local git clone. Use the GitHub API only for metadata not available
   locally (issue bodies, PR review comments).

2. **Append/resume-friendly.** Each stage SHOULD be resumable. Output
   files use JSONL format to support incremental appending. Already-
   processed changes are detected via `change_id` and skipped on resume.

3. **Leakage-aware descriptions.** Each `DescriptionSource` carries a
   `leakage_risk` classification. Sources with `high` leakage risk
   (e.g., review comments that mention the exact fix) MUST NOT be used
   in task prompts without filtering.

## 11. Change Taxonomy

### 11.1 Purpose

Classify repository changes by their effect on the contribution
framework — the implicit and explicit rules, patterns, and mechanisms
that govern how contributions are made to a project. This classification
enables filtering, stratification, and quality assessment of benchmark
instances.

### 11.2 Framework Effect Lattice (F0–F4)

Changes are classified into five levels based on their structural impact
on the project's contribution framework:

| Level | Name | Description |
|-------|------|-------------|
| F0 | No Framework Effect | The change does not affect how future contributions are made. Pure bug fixes, feature additions that follow existing patterns. |
| F1 | Local Knowledge Addition | Adds new domain knowledge or data that future contributors must be aware of. New constants, configuration values, API endpoints. |
| F2 | Pattern or Invariant Encoding | Establishes or modifies a pattern that future contributions should follow. New coding conventions, test patterns, error handling approaches. |
| F3 | Framework Mechanism Change | Changes the mechanisms that enforce or enable contributions. Build system changes, CI/CD modifications, test infrastructure updates. |
| F4 | Governance or Architecture Shift | Alters the fundamental structure or governance of the project. Major refactors, architecture changes, process changes. |

### 11.3 Evaluation Questions

The taxonomy uses 23 binary (yes/no) evaluation questions organized by
framework level. Each question probes whether a change exhibits
characteristics of that level.

#### F1 Questions (Local Knowledge Addition)
- Q01: Does this change introduce new named constants, configuration keys, or feature flags?
- Q02: Does this change add new API endpoints, CLI commands, or user-facing entry points?
- Q03: Does this change add new error codes, status values, or enumeration members?
- Q04: Does this change introduce domain-specific terminology or concepts in code or documentation?
- Q05: Does this change add data schemas, database migrations, or data model fields?

#### F2 Questions (Pattern or Invariant Encoding)
- Q06: Does this change establish a new coding pattern that other code should follow?
- Q07: Does this change modify or add validation rules, input constraints, or invariant checks?
- Q08: Does this change introduce a new abstraction (interface, base class, trait) for others to implement?
- Q09: Does this change add or modify test patterns, fixtures, or testing utilities?
- Q10: Does this change establish conventions for error handling, logging, or observability?
- Q11: Does this change add or modify documentation templates, style guides, or contribution guidelines?

#### F3 Questions (Framework Mechanism Change)
- Q12: Does this change modify the build system, package configuration, or dependency management?
- Q13: Does this change alter CI/CD pipelines, GitHub Actions workflows, or automation scripts?
- Q14: Does this change modify test infrastructure, test runners, or test configuration?
- Q15: Does this change affect code generation, scaffolding, or templating tools?
- Q16: Does this change modify linting rules, formatting configuration, or static analysis settings?
- Q17: Does this change alter deployment configuration, infrastructure-as-code, or environment setup?

#### F4 Questions (Governance or Architecture Shift)
- Q18: Does this change restructure the project's directory layout or module organization?
- Q19: Does this change modify the project's public API surface in a breaking way?
- Q20: Does this change alter the project's versioning, release, or branching strategy?
- Q21: Does this change modify governance documents (CODEOWNERS, MAINTAINERS, decision records)?
- Q22: Does this change introduce or remove a major architectural component or subsystem?
- Q23: Does this change alter the project's license, security policy, or compliance requirements?

### 11.4 Classification Process

1. **Deterministic heuristic classifier.** A rule-based classifier
   answers each of the 23 questions using file-path patterns, diff
   content analysis, and keyword matching. This classifier is fast and
   deterministic.

2. **Optional LLM classifier.** An LLM-based classifier MAY be used to
   answer questions that the heuristic classifier cannot confidently
   resolve. The LLM classifier provides higher accuracy at the cost of
   latency and expense.

3. **Level assignment.** The framework level is determined by the highest
   level at which any question is answered affirmatively. If no questions
   are answered affirmatively, the change is classified as F0.

### 11.5 Data Model

#### TaxonomyQuestion

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | — | Question identifier (e.g., `q01`) |
| `text` | `str` | — | The binary question text |
| `category` | `str` | — | Framework level: `F1`, `F2`, `F3`, or `F4` |
| `weight` | `float` | `1.0` | Relative weight for confidence scoring |

#### TaxonomyEvaluation

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question_id` | `str` | — | Reference to a `TaxonomyQuestion.id` |
| `answer` | `bool` | — | Whether the question is answered affirmatively |
| `confidence` | `float` | `1.0` | Confidence in the answer (0.0–1.0) |
| `evidence` | `str` | `''` | Supporting evidence for the answer |

#### TaxonomyClassification

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `change_id` | `str` | — | Reference to a `GroundTruthChange.change_id` |
| `framework_level` | `str` | — | Assigned level: `F0`, `F1`, `F2`, `F3`, or `F4` |
| `level_confidence` | `float` | `0.0` | Confidence in the level assignment |
| `evaluations` | `list[TaxonomyEvaluation]` | `[]` | Individual question evaluations |
| `reasoning` | `str` | `''` | Summary reasoning for the classification |
