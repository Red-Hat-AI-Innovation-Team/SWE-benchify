# SWE-benchify Service Specification

Status: Draft v1

Purpose: Define a harness that dispatches coding agents to transform GitHub
repositories into SWE-bench-compatible benchmarks.

## Normative Language

The key words `MUST`, `MUST NOT`, `REQUIRED`, `SHOULD`, `SHOULD NOT`,
`RECOMMENDED`, `MAY`, and `OPTIONAL` in this document are to be interpreted
as described in RFC 2119.

`Implementation-defined` means the behavior is part of the implementation
contract, but this specification does not prescribe one universal policy.
Implementations MUST document the selected behavior.

## 1. Problem Statement

SWE-benchify is a batch pipeline service that takes a list of GitHub
repositories, collects merged pull requests with linked issues, and produces
a validated dataset of benchmark instances compatible with the
[SWE-bench](https://github.com/princeton-nlp/SWE-bench) evaluation harness.

The service solves three problems:

- It automates the production of SWE-bench-compatible datasets from arbitrary
  repositories, including private and internal ones, without hand-authored
  per-repo installation specs or version-mapping tables.
- It delegates the hard, judgment-intensive parts of the pipeline —
  environment discovery and test validation — to a coding agent (Claude Code)
  that can explore a repository, install dependencies, run tests, and debug
  failures.
- It provides a resumable, observable pipeline so operators can process
  repositories at scale with bounded cost and clear progress.

Important boundary:

- SWE-benchify is a dataset producer. It does not evaluate coding agents
  against the produced dataset; use SWE-bench's evaluation harness for that.
- SWE-benchify is a harness, not an agent framework. It does not implement
  agent loops, tool use, or prompt management. It dispatches Claude Code
  sessions via the Agent SDK and collects their structured output.

## 2. Goals and Non-Goals

### 2.1 Goals

- Collect merged pull requests with linked issues from GitHub repositories.
- Extract gold patches (code changes) and test patches (test changes) from
  each pull request.
- Dispatch a coding agent to discover the build, install, and test setup for
  each repository at each relevant commit.
- Dispatch a coding agent to validate each candidate instance by running
  tests before and after applying the gold patch.
- Produce output conforming to the `SWEbenchInstance` schema from
  `swebench.harness.constants`.
- Support public and private GitHub repositories via token-based auth.
- Support resumption after interruption without reprocessing completed work.
- Track and report agent cost (tokens, dollars) per session and in aggregate.
- Support any language ecosystem whose repositories have a testable PR
  history (Python, TypeScript, Go, Rust, Java, etc.).

### 2.2 Non-Goals

- Evaluation harness or coding-agent benchmark runner.
- Model inference or LLM-generated patches. Gold patches come from real
  merged PRs.
- Web UI, leaderboard, or dashboard.
- General-purpose workflow engine or job scheduler.
- Custom agent framework, tool implementations, or prompt management beyond
  what Claude Code provides.
- Mandating a specific container runtime or sandbox technology.

## 3. System Overview

### 3.1 Main Components

1. **Pipeline Controller**
   - Owns the stage sequencing for each repository.
   - Manages concurrency across repositories and validation runs.
   - Handles resumption by checking for existing stage outputs.

2. **PR Collector**
   - Fetches merged pull requests from the GitHub API.
   - Extracts linked issue references.
   - Produces candidate PR records.

3. **Patch Extractor**
   - Downloads PR diffs and splits them into gold patches and test patches.
   - Extracts problem statements and hints from linked issues.

4. **Agent Dispatcher**
   - Prepares workspaces for agent sessions.
   - Launches Claude Code sessions via the Agent SDK.
   - Reads structured output files written by the agent.
   - Handles retries with prompt amendments on failure.

5. **Workspace Manager**
   - Maintains a bare clone per repository.
   - Creates per-commit worktrees for agent sessions.
   - Caches environment specs by repository version.
   - Cleans up completed workspaces.

6. **Quality Filter**
   - Applies configurable deterministic filters to validated instances.

7. **Dataset Emitter**
   - Serializes validated, filtered instances to SWE-bench-compatible JSONL.

### 3.2 Abstraction Levels

1. **Configuration Layer**
   - Parses user-provided repo list, credentials, and pipeline settings.
   - Resolves environment variable indirection for secrets.

2. **Collection Layer** (mechanical)
   - GitHub API interaction, diff parsing, issue extraction.
   - Deterministic; no agent involvement.

3. **Agent Layer** (agentic)
   - Environment discovery and instance validation.
   - Claude Code sessions dispatched via Agent SDK.

4. **Output Layer** (mechanical)
   - Quality filtering and JSONL serialization.
   - Deterministic; no agent involvement.

### 3.3 External Dependencies

- GitHub API (REST v3) for PR and issue data.
- Claude Code Agent SDK (Python) for dispatching coding agent sessions.
- Git CLI for repository cloning and worktree management.
- Container runtime (OPTIONAL) for sandboxing agent sessions.
- Local filesystem for workspaces, caches, and output.

## 4. Core Domain Model

### 4.1 Entities

#### 4.1.1 Repository

A GitHub repository to process.

Fields:

- `full_name` (string)
  - Owner/repo format (e.g., `django/django`).
- `access_token` (string or null)
  - GitHub token for API access. Resolved from environment variables.

#### 4.1.2 CandidatePR

A merged pull request that references at least one issue.

Fields:

- `repo` (string)
  - Repository `full_name`.
- `pr_number` (integer)
- `title` (string)
- `body` (string or null)
- `base_commit` (string)
  - SHA of the commit the PR branches from.
- `merge_commit` (string)
- `diff_url` (string)
- `resolved_issues` (list of integers)
  - Issue numbers extracted from PR text and commit messages.
- `created_at` (string, ISO 8601)
- `merged_at` (string, ISO 8601)

#### 4.1.3 CandidateInstance

A CandidatePR augmented with extracted patches and problem statement.

Fields (in addition to CandidatePR fields):

- `instance_id` (string)
  - Format: `{owner}__{repo}-{pr_number}`.
- `patch` (string or null)
  - Gold patch: unified diff of non-test file changes.
- `test_patch` (string or null)
  - Test patch: unified diff of test file changes.
- `problem_statement` (string or null)
  - Concatenation of linked issue title and body.
- `hints_text` (string or null)
  - Issue comments posted before the first PR commit.

#### 4.1.4 EnvironmentSpec

Build and test configuration discovered by the agent for a specific
repository version.

Fields:

- `language` (string)
  - Primary language (e.g., `python`, `typescript`, `go`).
- `language_version` (string)
  - Runtime version (e.g., `3.11`, `20`, `1.21`).
- `package_manager` (string)
  - Package manager used (e.g., `pip`, `conda`, `npm`, `cargo`).
- `install_cmd` (string)
  - Command to install the project in development mode.
- `test_cmd` (string)
  - Command to run the test suite or a relevant subset.
- `pre_install` (list of strings)
  - Additional setup commands to run before install.
- `system_dependencies` (list of strings)
  - System packages to install (e.g., via `apt-get`).

#### 4.1.5 RepoVersion

Version of a repository at a specific commit.

Fields:

- `repo` (string)
- `commit` (string)
- `version` (string)
  - Extracted from metadata files (e.g., `setup.py`, `pyproject.toml`,
    `package.json`).

#### 4.1.6 ValidationResult

Output of the validation agent for one candidate instance.

Fields:

- `status` (enum: `valid`, `invalid`, `error`)
- `FAIL_TO_PASS` (list of strings)
  - Test identifiers that fail before the gold patch and pass after.
- `PASS_TO_PASS` (list of strings)
  - Test identifiers that pass before and after the gold patch.
- `error_message` (string or null)
  - Description of failure if `status` is `error`.

#### 4.1.7 TaskInstance

A validated benchmark instance conforming to the SWE-bench schema.

Fields:

- `repo` (string)
- `instance_id` (string)
- `base_commit` (string)
- `patch` (string)
- `test_patch` (string)
- `problem_statement` (string)
- `hints_text` (string)
- `created_at` (string, ISO 8601)
- `version` (string)
- `FAIL_TO_PASS` (list of strings)
- `PASS_TO_PASS` (list of strings)
- `environment_setup_commit` (string or null)

This schema MUST conform to the `SWEbenchInstance` TypedDict from
`swebench.harness.constants`.

## 5. Pipeline Specification

### 5.1 Stage Overview

The pipeline processes each repository through six sequential stages.
Stages 1, 2, 5, and 6 are mechanical (deterministic code, no agent).
Stages 3 and 4 are agentic (Claude Code sessions).

| Stage | Name | Type | Input | Output |
|-------|------|------|-------|--------|
| 1 | PR Collection | Mechanical | Repository | CandidatePR records |
| 2 | Patch Extraction | Mechanical | CandidatePR records | CandidateInstance records |
| 3 | Environment Discovery | Agentic | Repository + commit | EnvironmentSpec + RepoVersion |
| 4 | Instance Validation | Agentic | CandidateInstance + EnvironmentSpec | ValidationResult |
| 5 | Quality Filtering | Mechanical | Validated instances | Filtered instances |
| 6 | Dataset Emission | Mechanical | Filtered instances | JSONL files |

### 5.2 Stage 1: PR Collection

Input: Repository `full_name` + access token.
Output: CandidatePR records.

The collector MUST fetch all closed, merged pull requests from the GitHub
REST API. For each PR, the collector MUST extract referenced issue numbers
using keyword patterns searched in the PR title, PR body, and commit
messages:

```
(close[sd]?|fix(e[sd])?|resolve[sd]?) #?(\d+)
```

A PR is a candidate if `merged_at` is not null and `resolved_issues`
contains at least one entry.

Rate limiting: The collector MUST handle GitHub API rate limits (HTTP 403
with `X-RateLimit-Remaining: 0`) by backing off exponentially, starting at
60 seconds.

Resumption: If output for a repository already exists, the collector MUST
skip already-processed PRs identified by `pr_number`.

### 5.3 Stage 2: Patch Extraction

Input: CandidatePR records.
Output: CandidateInstance records.

For each CandidatePR, the extractor MUST download the full diff via
`diff_url` and split hunks into two categories:

- **test_patch**: Hunks in files matching test patterns. At minimum:
  `test/`, `tests/`, `e2e/`, `testing/`, `*_test.*`, `test_*.*`,
  `*_spec.*`, `*.test.*`, `*.spec.*`.
- **patch** (gold): All other hunks.

The extractor MUST also fetch the problem statement (linked issue title +
body) and hints (issue comments posted before the first PR commit) from the
GitHub API.

A CandidateInstance is **viable** if both `patch` and `problem_statement`
are non-empty. Viable candidates with non-empty `test_patch` proceed to
Stage 3. Viable candidates with empty `test_patch` SHOULD be written to a
separate output file for potential fine-tuning use.

### 5.4 Stage 3: Environment Discovery

Input: Repository clone + base commit SHA.
Output: EnvironmentSpec + RepoVersion, written as JSON files in the
workspace.

This is the first agentic stage. For each unique `(repo, version)` pair,
the harness MUST:

1. Prepare a workspace with the repository checked out at the target commit.
2. Launch a Claude Code session with a prompt instructing the agent to:
   - Identify the language, build system, and package manager.
   - Install the project and its dependencies in development mode.
   - Determine and verify the test command.
   - Extract the project version from metadata files.
   - Write structured output files (`env_spec.json`, `version.json`) to the
     workspace.
3. Read and validate the structured output files.

Agent session configuration:

- Allowed tools MUST include at minimum: `Bash`, `Read`, `Write`, `Glob`,
  `Grep`.
- Permission mode MUST allow the agent to install packages and run commands
  without interactive prompts.
- `max_turns` and `max_budget_usd` SHOULD be configurable. Defaults are
  implementation-defined.

Caching: Environment specs MUST be cached by `(repo, version)`. Multiple
candidate instances at the same version MUST share the cached spec. The
agent MUST run at most once per unique `(repo, version)`.

Failure handling: If the agent session does not produce valid output files,
the harness MUST retry up to a configurable `max_attempts` (default 3).
On retry, the harness SHOULD amend the prompt with information about the
previous failure. After exhausting retries, the version is marked
unsupported and all candidate instances at that version are skipped.

### 5.5 Stage 4: Instance Validation

Input: CandidateInstance (with patches) + EnvironmentSpec.
Output: ValidationResult, written as a JSON file in the workspace.

For each candidate instance, the harness MUST:

1. Prepare a workspace with the repository at `base_commit`, the test patch
   file, and the gold patch file.
2. Launch a Claude Code session with a prompt instructing the agent to:
   - Set up the environment per the EnvironmentSpec.
   - Apply the test patch and run the test command. Record failing tests.
   - Apply the gold patch and run the test command again. Record passing
     tests.
   - Compute FAIL_TO_PASS (tests that failed before and pass after) and
     PASS_TO_PASS (tests that passed before and still pass after).
   - Write a `validation_result.json` to the workspace.
3. Read and validate the structured output file.

Agent session configuration:

- Allowed tools MUST include at minimum: `Bash`, `Read`, `Write`.
- Permission mode MUST allow the agent to install packages and run tests
  without interactive prompts.

A candidate instance is **valid** if `FAIL_TO_PASS` contains at least one
test identifier and all `PASS_TO_PASS` tests remain passing.

Validation is agentic (rather than a deterministic script) because:

- The EnvironmentSpec from Stage 3 may need adjustment for specific commits.
- Test output formats vary across projects and need interpretation.
- The agent can distinguish test failures caused by the bug from failures
  caused by environment issues, and debug the latter.

Parallelism: Validation runs are independent per instance and SHOULD be
parallelized up to a configurable concurrency limit.

Isolation: Each validation run MUST execute in a separate workspace. If
container-based sandboxing is used, each run SHOULD execute in a fresh
container.

### 5.6 Stage 5: Quality Filtering

Input: Validated TaskInstances.
Output: Filtered TaskInstances.

The filter MUST apply configurable quality rules with the following
defaults:

| Rule | Default | Rationale |
|------|---------|-----------|
| Min `problem_statement` word count | 40 | Too-short descriptions are ambiguous |
| No bare URLs in `problem_statement` | on | Forces self-contained descriptions |
| No commit SHAs in `problem_statement` | on | Prevents trivial lookup |
| No image-only `problem_statement` | on | Text-based agents cannot use images |
| Min `FAIL_TO_PASS` count | 1 | Must have verifiable signal |
| Max `patch` line count | 500 | Extremely large patches are noise |
| Min `patch` line count | 1 | Empty patches are useless |

All rules MUST be individually configurable. Implementations MAY add
additional rules.

### 5.7 Stage 6: Dataset Emission

Input: Filtered TaskInstances.
Output: JSONL files.

The emitter MUST write one JSON object per line. Each object MUST conform
to the `SWEbenchInstance` schema.

Output files:

- Per-repository: `{output_dir}/{repo_slug}-task-instances.jsonl`
- Combined: `{output_dir}/all-task-instances.jsonl`

OPTIONAL: Upload to HuggingFace Datasets Hub.

## 6. Configuration Specification

### 6.1 Configuration Sources

Configuration is provided via a YAML file. The file path is specified at
invocation; default is `swebenchify.yaml` in the working directory.

### 6.2 Configuration Schema

Top-level keys:

- `repos` (list of strings)
  - REQUIRED.
  - Repository identifiers in `owner/repo` format.
- `github` (object)
  - `token` (string or `$VAR`)
    - Default GitHub token. MUST support `$VAR` environment variable
      indirection.
  - `tokens` (map of string to string or `$VAR`)
    - Per-repository token overrides. Keys are `owner/repo` identifiers.
- `pipeline` (object)
  - `max_concurrent_repos` (integer, default 4)
  - `max_concurrent_validations` (integer, default 8)
  - `max_prs_per_repo` (integer or null, default null meaning all)
  - `pr_date_range` (object, OPTIONAL)
    - `after` (string, ISO 8601 date)
    - `before` (string, ISO 8601 date)
- `agent` (object)
  - `max_attempts` (integer, default 3)
    - Retry limit for failed agent sessions.
  - `env_discovery` (object)
    - `max_turns` (integer, implementation-defined default)
    - `budget_usd` (float, implementation-defined default)
  - `validation` (object)
    - `max_turns` (integer, implementation-defined default)
    - `budget_usd` (float, implementation-defined default)
- `filters` (object)
  - Override defaults from Section 5.6.
- `output` (object)
  - `dir` (path string, default `./output`)
  - `upload_to_hf` (boolean, default false)
  - `hf_repo` (string or null)

### 6.3 Environment Variable Resolution

Fields that contain `$VAR_NAME` as their value MUST be resolved from the
corresponding environment variable. If the variable is unset or empty, the
field is treated as missing.

Environment variables do not globally override YAML values. They are used
only when a config value explicitly references them via `$VAR` syntax.

### 6.4 Validation

At startup, the service MUST validate:

- `repos` is present and non-empty.
- At least one GitHub token is available (global or per-repo) after `$VAR`
  resolution.
- `output.dir` is writable.

Invalid configuration MUST prevent the pipeline from starting.

## 7. Agent Dispatcher Protocol

### 7.1 Agent Session Contract

The Agent Dispatcher uses the Claude Code Agent SDK to launch coding agent
sessions. Each session is a one-shot query: the harness provides a prompt
and a workspace directory, and the agent writes structured output files.

For each agent session, the dispatcher MUST:

1. Prepare the workspace directory with all required input files.
2. Invoke the Agent SDK `query()` with:
   - A task-specific prompt.
   - The workspace path as `cwd`.
   - An allowed-tools list appropriate to the task.
   - A permission mode that does not require interactive approval.
   - Configurable `max_turns` and `max_budget_usd`.
3. Await the `ResultMessage` and inspect its `subtype`.
4. Read structured output files from the workspace.
5. Validate the output against the expected schema.

### 7.2 Agent Output Contract

Agents communicate results by writing JSON files to their workspace
directory. The harness MUST NOT rely on parsing the agent's conversational
output for structured data.

Environment Discovery output files:

- `env_spec.json` conforming to the EnvironmentSpec schema (Section 4.1.4).
- `version.json` conforming to the RepoVersion schema (Section 4.1.5).

Validation output files:

- `validation_result.json` conforming to the ValidationResult schema
  (Section 4.1.6).

### 7.3 Prompt Construction

The harness MUST construct task-specific prompts for each agent session.
Prompts MUST include:

- The repository name and commit SHA.
- Clear instructions for what to do.
- The expected output file names and JSON schemas.
- Constraints (e.g., time limits for test suites, preference for dev
  installs).

For validation sessions, the prompt MUST additionally include:

- The EnvironmentSpec (from Stage 3).
- The file paths of the test patch and gold patch within the workspace.

For retry sessions, the prompt SHOULD include information about the
previous failure to help the agent avoid the same mistake.

### 7.4 Failure Classification

Agent session outcomes, derived from `ResultMessage.subtype`:

- `success`: Agent completed. Check for output files.
- `error_max_turns`: Agent exhausted turn limit. Retry with higher limit
  (1.5x) up to `max_attempts`.
- `error_max_budget_usd`: Agent exceeded cost budget. Log and skip.
- `error_during_execution`: Agent encountered an error. Retry up to
  `max_attempts`.

If the agent completes successfully but output files are missing or
malformed, treat as a retryable failure with prompt amendment.

### 7.5 Cost Tracking

Every `ResultMessage` from the Agent SDK includes `total_cost_usd`,
`usage` (token counts), and `duration_ms`. The harness MUST aggregate:

- Cost per agent session.
- Cost per pipeline stage (environment discovery vs. validation).
- Cost per repository.
- Total pipeline cost.

Aggregate cost MUST be available to the operator at any time during and
after the pipeline run.

## 8. Workspace Management

### 8.1 Workspace Layout

```
{workspace_root}/
  {repo_slug}/
    repo.git/                          # bare clone
    envs/
      {version}/
        env_spec.json                  # cached EnvironmentSpec
        version.json                   # cached RepoVersion
    instances/
      {instance_id}/
        repo/                          # worktree at base_commit
        test.patch
        gold.patch
        validation_result.json
    output/
      {repo_slug}-task-instances.jsonl
```

### 8.2 Workspace Lifecycle

1. `repo.git/` is created once per repository via `git clone --bare`.
   Reused across all stages.
2. `envs/{version}/` is created per unique version during Stage 3.
   Persists for the duration of the pipeline run as a cache.
3. `instances/{instance_id}/` is created per validation run during Stage 4.
   The `repo/` subdirectory is a git worktree from `repo.git/`.
4. Completed instance workspaces SHOULD be removed after Stage 6 unless
   a keep-workspaces option is set.

### 8.3 Safety Invariants

- Agent sessions MUST run with `cwd` set to their assigned workspace
  directory.
- Workspace paths MUST reside under the configured `workspace_root`.
- Repository slug directory names MUST be sanitized: only `[A-Za-z0-9._-]`
  characters allowed; all others replaced with `_`.

## 9. Resumption and Error Handling

### 9.1 Stage Checkpoints

Each stage writes its output to a well-known file path. On resumption,
the pipeline MUST check for existing output and skip completed stages:

| Stage | Checkpoint |
|-------|-----------|
| PR Collection | `{repo_slug}-prs.jsonl` exists |
| Patch Extraction | `{repo_slug}-candidates.jsonl` exists |
| Environment Discovery | `envs/{version}/env_spec.json` exists and valid |
| Instance Validation | `instances/{id}/validation_result.json` exists |
| Quality Filtering + Emission | `{repo_slug}-task-instances.jsonl` exists |

### 9.2 Failure Modes

| Failure | Behavior |
|---------|----------|
| GitHub rate limit | Exponential backoff starting at 60s |
| GitHub auth error | Skip repository, log error, continue with others |
| Agent exceeds `max_turns` | Retry with 1.5x turns, up to `max_attempts` |
| Agent exceeds `max_budget_usd` | Log warning, skip instance |
| Agent execution error | Retry up to `max_attempts` |
| Agent produces invalid output | Retry with amended prompt, up to `max_attempts` |
| No FAIL_TO_PASS tests | Mark instance invalid (not retryable) |
| Disk full | Abort with operator-visible error |

## 10. Observability

### 10.1 Logging

All log entries MUST include:

- `timestamp` (ISO 8601)
- `level` (debug, info, warn, error)
- `stage` (collect, extract, env-discovery, validate, filter, emit)
- `repo` (when applicable)
- `instance_id` (when applicable)

### 10.2 Progress

The service MUST report progress showing, per repository:

- PRs collected
- Candidates extracted
- Instances validated (completed / total)
- Instances emitted

And in aggregate:

- Repositories completed / total
- Total instances emitted
- Total agent cost

### 10.3 Agent Session Logs

Agent session transcripts SHOULD be persisted to the workspace directory
for debugging. The harness SHOULD NOT log full repository contents in
plaintext beyond structured diffs.

## 11. Security and Operational Safety

### 11.1 Secret Handling

- GitHub tokens MUST be resolved from environment variables via `$VAR`
  indirection, never stored as literals in configuration files.
- Tokens MUST NOT appear in log output.

### 11.2 Private Repository Considerations

- Claude Code sessions send repository code to the configured LLM provider.
  Operators MUST be informed of this.
- For air-gapped or compliance-sensitive environments, Claude Code supports
  Amazon Bedrock and Google Vertex AI deployments.
- Problem statements and hints are extracted from GitHub issues verbatim
  and may contain sensitive information. Operators SHOULD review output
  before publishing datasets from private repositories.

### 11.3 Agent Sandboxing

- Agent sessions run with permissions that allow package installation and
  command execution. The harness SHOULD run agent sessions inside containers
  to contain side effects.
- Container configuration is implementation-defined.
- Network access MUST be available for dependency installation but MAY be
  restricted via container network policies.

## 12. Reference Algorithms

### 12.1 Pipeline Controller

```text
function run_pipeline(config):
  repos = config.repos
  for repo in repos (bounded concurrency: config.pipeline.max_concurrent_repos):
    run_repo_pipeline(repo, config)
  emit_combined_dataset(config.output.dir)

function run_repo_pipeline(repo, config):
  candidates = collect_prs(repo)                          # Stage 1
  instances = extract_patches(candidates)                 # Stage 2
  versions = unique_versions(instances)
  for version in versions:
    env_spec = discover_environment(repo, version)        # Stage 3
  validated = validate_instances(instances, env_specs)    # Stage 4
  filtered = apply_quality_filters(validated)             # Stage 5
  emit_dataset(filtered)                                  # Stage 6
```

### 12.2 Environment Discovery (Stage 3)

```text
function discover_environment(repo, commit):
  cache_key = (repo, version_at_commit(commit))
  if cache_key in cache:
    return cache[cache_key]

  workspace = prepare_workspace(repo, commit)
  for attempt in 1..max_attempts:
    prompt = build_env_discovery_prompt(repo, commit, previous_error)
    result = agent_sdk.query(prompt, cwd=workspace, tools=ENV_TOOLS)
    if result.status == "success" and valid_output_files(workspace):
      env_spec = read_json(workspace / "env_spec.json")
      cache[cache_key] = env_spec
      return env_spec
    previous_error = describe_failure(result, workspace)

  mark_version_unsupported(cache_key)
  return null
```

### 12.3 Instance Validation (Stage 4)

```text
function validate_instance(candidate, env_spec):
  workspace = prepare_validation_workspace(candidate)
  write_file(workspace / "test.patch", candidate.test_patch)
  write_file(workspace / "gold.patch", candidate.patch)

  for attempt in 1..max_attempts:
    prompt = build_validation_prompt(candidate, env_spec, previous_error)
    result = agent_sdk.query(prompt, cwd=workspace, tools=VALIDATION_TOOLS)
    if result.status == "success" and valid_output_files(workspace):
      return read_json(workspace / "validation_result.json")
    previous_error = describe_failure(result, workspace)

  return ValidationResult(status="error", error_message="exhausted retries")
```

## 13. Conformance

### 13.1 Output Conformance

A conforming implementation MUST produce JSONL output where every line
parses as a valid `SWEbenchInstance` with all required fields populated.

### 13.2 SWE-bench Reproduction Test

When run against the repositories in the SWE-bench dataset with matching
date ranges, a conforming implementation SHOULD produce a dataset with
>=80% overlap on `instance_id` values with the published SWE-bench dataset.
Differences are expected due to GitHub API changes over time, filtering
heuristic differences, and non-deterministic agent behavior.

## 14. Open Questions

1. **Docker image strategy.** Should the harness build one Docker image per
   repository version (dependencies baked in) or use a generic image and
   let the agent install dependencies each time? The former amortizes setup
   cost across many validation runs; the latter is simpler.

2. **Test subset selection.** For repositories with test suites exceeding
   30 minutes, should the agent select a relevant subset of tests per
   instance, or always run the full suite?

3. **SWE-bench data reuse.** When processing repositories already in
   SWE-bench, should the agent receive `MAP_VERSION_TO_INSTALL` data as a
   hint, or always discover from scratch for consistency?

4. **Multi-language repositories.** How should the harness handle
   repositories with mixed languages? Should the agent produce multiple
   EnvironmentSpecs?

5. **Agent model selection.** Should environment discovery (exploratory,
   harder) and validation (procedural, more structured) use different
   Claude models?
