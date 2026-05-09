# SWE-benchify: Service Specification

> A harness that dispatches Claude Code agents to transform GitHub
> repositories into SWE-bench-compatible benchmarks.

## 1. Problem Statement

[SWE-bench](https://github.com/princeton-nlp/SWE-bench) is the standard
benchmark for evaluating coding agents on real-world software engineering
tasks. Each task instance is a merged pull request with a linked issue, a
gold patch, a test patch, and environment setup instructions.

Building SWE-bench today requires **significant manual effort per repository**:
hand-authored installation specs (`MAP_VERSION_TO_INSTALL`), version-mapping
tables, and per-repo test commands. This limits SWE-bench to a curated set of
open-source Python projects.

SWE-benchify removes this bottleneck. Given a list of GitHub repositories
(public or private), it produces a SWE-bench-compatible dataset with minimal
human intervention. A Claude Code agent handles the parts that currently
require manual configuration: environment setup, build/test discovery, version
detection, and validation debugging.

### 1.1 Design Goals

1. **Reproduce SWE-bench.** When given the same 12 repositories SWE-bench
   uses, SWE-benchify SHOULD produce equivalent task instances.
2. **Generalize beyond Python.** Support any language with testable PRs
   (Python, TypeScript, Go, Rust, Java, etc.).
3. **Work on private repos.** Accept GitHub tokens with access to internal
   repositories; never leak source code to external services beyond the
   configured LLM provider.
4. **Minimize human configuration.** The user provides a repo list and
   credentials. The agent discovers everything else.
5. **Produce validated instances.** Every output instance has been tested:
   the gold patch turns FAIL_TO_PASS tests green, and PASS_TO_PASS tests
   remain green.

### 1.2 Non-Goals

- **Evaluation harness.** SWE-benchify produces datasets; it does not run
  coding agents against them. Use SWE-bench's existing harness for that.
- **Model inference.** No LLM-generates-patches step. The gold patches come
  from real merged PRs.
- **Leaderboard / UI.** Output is `.jsonl` files and optional HuggingFace
  dataset upload. No web dashboard.
- **Custom agent framework.** We do not build agent loops, tool
  implementations, or prompt management. Claude Code provides all of that.


## 2. Architecture: Harness + Claude Code Agents

### 2.1 Key Insight

SWE-benchify is **not** a custom agentic system. It is a **harness** — a
Python program that:

1. Prepares workspaces (clone repos, checkout commits, write instructions)
2. Launches Claude Code sessions via the Agent SDK with task-specific prompts
3. Collects structured output (JSON files the agent writes to disk)
4. Sequences pipeline stages and manages concurrency

The agent is Claude Code. It already has bash, file I/O, reasoning, retries,
and cost tracking. We don't reimplement any of that.

### 2.2 Agent SDK Integration

We use the [Claude Code Agent SDK (Python)](https://pypi.org/project/claude-agent-sdk/)
for programmatic control:

```python
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

async def run_agent_task(prompt: str, cwd: str, tools: list[str],
                         max_turns: int = 50, budget: float = 2.0) -> dict:
    result = {}
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=cwd,
            allowed_tools=tools,
            permission_mode="bypassPermissions",
            max_turns=max_turns,
            max_budget_usd=budget,
        ),
    ):
        if isinstance(message, ResultMessage):
            result = {
                "status": message.subtype,      # "success", "error_*"
                "output": message.result,
                "cost": message.total_cost_usd,
                "session_id": message.session_id,
                "duration_ms": message.duration_ms,
            }
    return result
```

This is the fundamental building block. Every agentic stage in the pipeline
is a call to `run_agent_task` with a different prompt and tool set.

### 2.3 System Diagram

```
                        +-----------------------+
                        |   User Configuration  |
                        |  (repo list, tokens)  |
                        +----------+------------+
                                   |
                                   v
                  +----------------+----------------+
                  |           Harness                |
                  |  Python async orchestrator       |
                  |  using Claude Agent SDK          |
                  +---+--------+--------+-------+---+
                      |        |        |       |
               Stage 1-2   Stage 3   Stage 4  Stage 5-6
               (Python)   (Agent)   (Agent)   (Python)
                      |        |        |       |
                      v        v        v       v
                  Collect   Discover  Validate  Emit
                  & Extract  Env      Instances Dataset
                   PRs      Setup
```

**Mechanical stages (pure Python, no agent):**
- Stage 1: PR Collection — GitHub API calls
- Stage 2: Patch Extraction — diff parsing
- Stage 5: Quality Filtering — deterministic rules
- Stage 6: Dataset Emission — JSONL serialization

**Agentic stages (Claude Code via Agent SDK):**
- Stage 3: Environment Discovery — agent explores repo, finds build/test setup
- Stage 4: Instance Validation — agent runs tests, debugs failures, extracts results

### 2.4 Components

| Component | What it is | Agent? |
|-----------|-----------|--------|
| **CLI** | Entry point. Parses config, launches orchestrator. | No |
| **Orchestrator** | `asyncio` event loop managing concurrency and sequencing. | No |
| **Collector** | Fetches merged PRs with linked issues from GitHub API. | No |
| **Patch Extractor** | Splits PR diffs into gold patch and test patch. | No |
| **Env Discovery** | Claude Code session that discovers build/test/install. | **Yes** |
| **Validator** | Claude Code session that runs tests and extracts results. | **Yes** |
| **Quality Filter** | Applies deterministic filters to validated instances. | No |
| **Emitter** | Writes SWE-bench-compatible JSONL. | No |
| **Workspace Manager** | Creates/cleans isolated directories per repo+commit. | No |


## 3. Domain Model

### 3.1 Entities

**Repository** — A GitHub repository to benchmark.
```
{
  owner: string          # e.g. "django"
  name: string           # e.g. "django"
  full_name: string      # "django/django"
  language: string       # primary language (auto-detected or configured)
  access_token?: string  # for private repos
}
```

**CandidatePR** — A merged pull request that references at least one issue.
```
{
  repo: string
  pr_number: int
  title: string
  body: string
  base_commit: string       # SHA the PR branches from
  merge_commit: string
  diff_url: string
  resolved_issues: int[]    # issue numbers extracted from PR text
  created_at: string        # ISO 8601
  merged_at: string
}
```

**TaskInstance** — A validated benchmark instance (SWE-bench schema).
```
{
  repo: string
  instance_id: string               # "{owner}__{name}-{pr_number}"
  base_commit: string
  patch: string                     # gold patch (unified diff)
  test_patch: string                # test changes (unified diff)
  problem_statement: string         # issue title + body
  hints_text: string                # issue comments before first PR commit
  created_at: string
  version: string
  FAIL_TO_PASS: string[]            # test IDs that must flip from fail to pass
  PASS_TO_PASS: string[]            # test IDs that must stay passing
  environment_setup_commit?: string
}
```

**EnvironmentSpec** — Discovered by the Environment Discovery agent.
```
{
  language: string              # "python", "typescript", "go", etc.
  language_version: string      # "3.11", "20", "1.21", etc.
  package_manager: string       # "pip", "conda", "npm", "cargo", etc.
  install_cmd: string           # "pip install -e .[dev]"
  test_cmd: string              # "pytest -x"
  pre_install?: string[]        # additional setup commands
  system_dependencies?: string[] # apt/brew packages needed
  docker_base_image?: string    # if a specific base is needed
}
```

**RepoVersion** — Version of a repository at a given commit.
```
{
  repo: string
  commit: string
  version: string      # e.g. "4.2", "3.0.1"
}
```


## 4. Pipeline Stages

### 4.1 Stage 1: PR Collection (Mechanical)

**Input:** Repository identifier + GitHub token.
**Output:** `{repo}-prs.jsonl` — one CandidatePR per line.

The Collector fetches all closed, merged PRs via the GitHub API. For each PR
it extracts referenced issue numbers using keyword patterns:

```
(close[sd]?|fix(e[sd])?|resolve[sd]?) #?(\d+)
```

searched in: PR title, PR body, and commit messages of the PR.

A PR is a **candidate** if:
- `merged_at` is not null
- `resolved_issues` has at least one entry

**Rate limiting:** The collector MUST handle GitHub API rate limits (403
responses) by backing off exponentially, starting at 60 seconds.

**Resumption:** If the output file already exists, the collector MUST skip
already-processed PRs (identified by `pr_number`).

### 4.2 Stage 2: Patch Extraction (Mechanical)

**Input:** CandidatePR records.
**Output:** CandidatePR records augmented with `patch` and `test_patch`.

The Patch Extractor downloads the full diff via `diff_url` and splits hunks:

- **test_patch**: Hunks in files matching test patterns:
  `test/`, `tests/`, `e2e/`, `testing/`, `*_test.*`, `test_*.*`,
  `*_spec.*`, `*.test.*`, `*.spec.*`
- **patch** (gold): All other hunks.

A candidate is **viable** if:
- `patch` is non-empty (there is an actual code change)
- `problem_statement` is non-empty (there is a linked issue with text)

Candidates with empty `test_patch` are written to `.jsonl.all` (usable for
fine-tuning) but excluded from the primary output (evaluation requires tests).

### 4.3 Stage 3: Environment Discovery (Agentic)

**Input:** Repository clone + base commit SHA.
**Output:** `env_spec.json` (EnvironmentSpec) + `version.json` (RepoVersion).

This is the first agentic stage. For each unique `(repo, version)` pair, the
harness:

1. Clones the repo and checks out the commit.
2. Writes a `CLAUDE.md` in the workspace root with task instructions.
3. Launches a Claude Code session via `query()`.
4. Reads the structured output files the agent writes.

#### Agent Invocation

```python
TOOLS_ENV_DISCOVERY = ["Bash", "Read", "Write", "Glob", "Grep"]

result = await run_agent_task(
    prompt=ENV_DISCOVERY_PROMPT.format(repo=repo, commit=commit),
    cwd=workspace_path,
    tools=TOOLS_ENV_DISCOVERY,
    max_turns=80,
    budget=5.0,
)
env_spec = json.loads((workspace_path / "env_spec.json").read_text())
```

#### Agent Prompt

```
You are setting up the build and test environment for {repo} at commit
{commit}.

Explore the repository. Find and read build configuration files (setup.py,
pyproject.toml, package.json, Cargo.toml, go.mod, Makefile, etc.).

Your tasks:
1. Identify the language, version, and package manager.
2. Install the project and its dependencies (prefer dev/editable installs).
3. Find the test command and run a quick smoke test to confirm it works.
4. Extract the project version from metadata files.

When done, write two JSON files:

1. `env_spec.json` with this schema:
   {{"language", "language_version", "package_manager", "install_cmd",
     "test_cmd", "pre_install": [], "system_dependencies": []}}

2. `version.json` with this schema:
   {{"repo", "commit", "version"}}

Constraints:
- You may install system packages with apt-get.
- Prefer editable/development installs.
- If the full test suite takes >5 minutes, find a fast subset command.
- If something fails, read error messages carefully and try alternatives.
```

#### Caching

Environment specs are cached by `(repo, version)`. Multiple PRs at the same
version reuse the cached spec. The agent runs once per unique environment.

#### Failure Handling

If the agent's `ResultMessage.subtype` is not `"success"`, or the output
files are missing/invalid, the harness retries up to `max_attempts` times
(default 3). After exhausting retries, the version is marked unsupported
and all candidate instances at that version are skipped.

### 4.4 Stage 4: Instance Validation (Agentic)

**Input:** CandidatePR (with patches) + EnvironmentSpec.
**Output:** `validation_result.json` with FAIL_TO_PASS and PASS_TO_PASS.

For each candidate instance, the harness:

1. Sets up a fresh workspace with the repo at `base_commit`.
2. Writes the `test_patch` and `patch` files into the workspace.
3. Writes a `CLAUDE.md` with validation instructions and the EnvironmentSpec.
4. Launches a Claude Code session.
5. Reads the structured result.

#### Agent Invocation

```python
TOOLS_VALIDATION = ["Bash", "Read", "Write"]

result = await run_agent_task(
    prompt=VALIDATION_PROMPT.format(
        repo=repo, commit=commit,
        env_spec=json.dumps(env_spec),
        test_patch_path="test.patch",
        gold_patch_path="gold.patch",
    ),
    cwd=workspace_path,
    tools=TOOLS_VALIDATION,
    max_turns=60,
    budget=3.0,
)
validation = json.loads(
    (workspace_path / "validation_result.json").read_text()
)
```

#### Agent Prompt

```
You are validating a benchmark instance for {repo} at commit {commit}.

The environment setup:
{env_spec}

Steps:
1. Set up the environment using the spec above.
2. Apply `test.patch` (new/modified tests): git apply test.patch
3. Run the test command. Record which tests FAIL. These are FAIL_TO_PASS
   candidates.
4. Apply `gold.patch` (the fix): git apply gold.patch
5. Run the test command again. Record which tests PASS now.
6. Compute:
   - FAIL_TO_PASS: tests that failed in step 3 and pass in step 5
   - PASS_TO_PASS: tests that passed in step 3 and still pass in step 5

Write `validation_result.json` with:
{{"status": "valid"|"invalid"|"error",
  "FAIL_TO_PASS": ["test.id.1", ...],
  "PASS_TO_PASS": ["test.id.2", ...],
  "error_message": null | "description if error"}}

Rules:
- An instance is VALID only if FAIL_TO_PASS has at least one test.
- If tests fail for environment reasons (not patch-related), debug and fix
  the environment before concluding.
- If you cannot get tests to run after reasonable effort, set status to
  "error" with a description.
```

#### Why Validation is Agentic

In SWE-bench, validation is a deterministic script because the environment
is pre-configured. In SWE-benchify, validation is agentic because:

- The EnvironmentSpec from Stage 3 may need adjustments for specific commits.
- Test output formats vary across projects and need interpretation.
- Flaky tests, missing dependencies, or build issues require debugging.
- The agent can distinguish "test fails because of the bug" from "test fails
  because the environment is broken."

#### Parallelism

Validation runs are independent per instance. The harness runs up to
`max_concurrent_validations` sessions concurrently using `asyncio.gather`
with a semaphore.

### 4.5 Stage 5: Quality Filtering (Mechanical)

**Input:** Validated TaskInstances.
**Output:** Filtered TaskInstances.

Apply quality filters (configurable, with sensible defaults):

| Filter | Default | Rationale |
|--------|---------|-----------|
| Min problem_statement length | 40 words | Too-short descriptions are ambiguous |
| No bare URLs in problem_statement | on | Forces self-contained descriptions |
| No commit SHAs in problem_statement | on | Prevents trivial lookup |
| No image-only problem_statements | on | Text-based agents can't use images |
| Min FAIL_TO_PASS count | 1 | Must have verifiable signal |
| Max patch size | 500 lines | Extremely large patches are noise |
| Min patch size | 1 line | Empty patches are useless |

### 4.6 Stage 6: Dataset Emission (Mechanical)

**Input:** Filtered TaskInstances.
**Output:** SWE-bench-compatible `.jsonl` files.

The Emitter writes one JSON object per line to:
- `{output_dir}/{repo_slug}-task-instances.jsonl` — per-repo files
- `{output_dir}/all-task-instances.jsonl` — combined dataset

Each line conforms to the `SWEbenchInstance` TypedDict schema from
`swebench.harness.constants`.

Optional: upload to HuggingFace Datasets Hub via `datasets` library.


## 5. Configuration

### 5.1 Config File

SWE-benchify is configured via a YAML file (default: `swebenchify.yaml`):

```yaml
# Repositories to benchmark
repos:
  - django/django
  - sympy/sympy
  - pallets/flask
  - owner/private-repo

# GitHub authentication
github:
  token: $GITHUB_TOKEN
  tokens:                         # per-repo overrides
    owner/private-repo: $PRIVATE_REPO_TOKEN

# Pipeline settings
pipeline:
  max_concurrent_repos: 4
  max_concurrent_validations: 8
  max_prs_per_repo: null          # null = all
  pr_date_range:
    after: "2020-01-01"
    before: "2025-01-01"

# Agent settings (apply to all Claude Code sessions)
agent:
  max_attempts: 3                 # retries per agent task
  env_discovery:
    max_turns: 80
    budget_usd: 5.0
  validation:
    max_turns: 60
    budget_usd: 3.0

# Quality filters (override defaults)
filters:
  min_problem_statement_words: 40
  max_patch_lines: 500
  no_urls_in_problem: true
  no_shas_in_problem: true

# Output
output:
  dir: ./output
  upload_to_hf: false
  hf_repo: null
```

Note: No `llm` config section. Claude Code handles model selection,
API keys, and provider configuration through its own settings
(`ANTHROPIC_API_KEY` env var, `~/.claude/settings.json`, etc.).

### 5.2 CLI Interface

```bash
# Full pipeline
swebenchify run --config swebenchify.yaml

# Single repo, quick test
swebenchify run --repo django/django --max-prs 10

# Resume interrupted run
swebenchify run --config swebenchify.yaml --resume

# Individual stages
swebenchify collect --config swebenchify.yaml
swebenchify discover --config swebenchify.yaml
swebenchify validate --input candidates.jsonl
swebenchify emit --input validated.jsonl --output dataset.jsonl

# Debug agent sessions
swebenchify logs --repo django/django --stage env-discovery
swebenchify logs --instance django__django-15498 --stage validation
```


## 6. Workspace Management

Each repo gets an isolated workspace under `{workdir}/workspaces/`:

```
workspaces/
  django__django/
    repo.git/                    # bare clone (shared across commits)
    envs/
      v4.2/
        env_spec.json            # cached EnvironmentSpec
        version.json             # cached RepoVersion
        agent_session.log        # agent session transcript
      v4.1/
        ...
    instances/
      django__django-15498/
        repo/                    # worktree at base_commit
        test.patch               # test patch file
        gold.patch               # gold patch file
        validation_result.json   # agent output
        agent_session.log        # agent session transcript
    output/
      django__django-task-instances.jsonl
```

**Lifecycle:**
1. `repo.git/` is created once per repo (bare clone).
2. `envs/{version}/` is created per unique version. Persists for caching.
3. `instances/{id}/` is created per validation run. Cleaned up after
   emission unless `--keep-workspaces` is set.
4. Git worktrees (via `git worktree add`) provide cheap per-instance
   checkouts from the shared bare clone.


## 7. Observability

### 7.1 Structured Logging

All log entries include:
- `timestamp` (ISO 8601)
- `level` (debug, info, warn, error)
- `stage` (collect, extract, env-discovery, validate, filter, emit)
- `repo` (when applicable)
- `instance_id` (when applicable)

### 7.2 Progress Reporting

The CLI displays a live summary:
```
django/django:  PRs: 1247  Candidates: 312  Validated: 89/312  Emitted: 67
sympy/sympy:    PRs:  934  Candidates: 201  Validated: 12/201  Emitted: --
flask/flask:    PRs:  456  Candidates:  87  Env Discovery...
─────────────────────────────────────────────────────────────────────────
Total:          3 repos    600 candidates    101 validated    67 emitted
Agent cost:     $14.32 (23 sessions)
```

### 7.3 Cost Tracking

Every `ResultMessage` from the Agent SDK includes `total_cost_usd`. The
harness aggregates:
- Cost per agent session
- Cost per stage (env-discovery vs. validation)
- Cost per repo
- Total pipeline cost


## 8. Error Handling and Resumption

### 8.1 Resumable Pipeline

Each stage writes intermediate results to disk. `--resume` picks up from
the last completed step:

| Stage | Checkpoint | Skip condition |
|-------|-----------|---------------|
| PR Collection | `{repo}-prs.jsonl` | File exists and is recent |
| Patch Extraction | `{repo}-candidates.jsonl` | File exists |
| Env Discovery | `envs/{version}/env_spec.json` | File exists and valid |
| Validation | `instances/{id}/validation_result.json` | File exists |
| Filtering + Emission | `{repo}-task-instances.jsonl` | File exists |

### 8.2 Failure Modes

| Failure | Behavior |
|---------|----------|
| GitHub rate limit | Exponential backoff (60s, 120s, 240s, ...) |
| GitHub auth error | Skip repo, log error, continue with others |
| Agent returns `error_max_turns` | Retry with higher `max_turns` (1.5x), up to `max_attempts` |
| Agent returns `error_max_budget_usd` | Log warning, skip instance |
| Agent returns `error_during_execution` | Retry up to `max_attempts` |
| Agent writes invalid output JSON | Retry with a prompt addendum noting the issue |
| Validation: no FAIL_TO_PASS tests | Mark instance invalid (not an error — just not usable) |
| Disk full | Abort with clear error message |


## 9. Security Considerations

### 9.1 Private Repository Handling

- Repository contents MUST NOT be logged in plaintext beyond structured
  diffs (patch, test_patch) and agent session transcripts.
- GitHub tokens MUST be resolved from environment variables, never stored
  in config files directly.
- Claude Code sessions send repository code to Anthropic's API. Users
  MUST be informed of this. For air-gapped environments, Claude Code
  supports Bedrock and Vertex deployments.

### 9.2 Agent Sandboxing

- Claude Code sessions run with `permission_mode="bypassPermissions"` so
  they can install packages and run tests without interactive prompts.
- The harness SHOULD run agent sessions inside Docker containers to
  contain side effects (agent can `apt-get install`, `pip install`, etc.).
- The workspace directory is the only host path mounted into the container.
- Network access is allowed (for dependency installation) but can be
  restricted via Docker network policies.

### 9.3 Output Sanitization

- Problem statements and hints are extracted from GitHub issues verbatim.
  They may contain sensitive information from private repos.
- Users should review output before publishing datasets.


## 10. Testing Strategy

### 10.1 Unit Tests

- Patch splitting logic (test vs. non-test file classification)
- Issue number extraction from PR text
- Config parsing and validation
- Quality filter logic
- JSONL serialization matches SWE-bench schema

### 10.2 Integration Tests

- End-to-end run on a small test-fixture repo with known PRs and expected
  output
- Agent can discover environment for a Python project (pytest)
- Agent can discover environment for a TypeScript project (jest/vitest)
- Validation correctly computes FAIL_TO_PASS / PASS_TO_PASS on a known
  instance

### 10.3 Conformance Test

- Run SWE-benchify on 2-3 of SWE-bench's repos (e.g., `astropy/astropy`,
  `pallets/flask`). Compare output instances against SWE-bench's published
  dataset. Expect >=80% overlap on instance_ids (differences expected due
  to filtering heuristics and GitHub API changes over time).


## 11. Implementation Checklist

### Phase 1: Core Pipeline (Mechanical)
- [ ] Project scaffolding (pyproject.toml, package structure)
- [ ] CLI entry point with config parsing
- [ ] GitHub PR collector with rate limiting and resumption
- [ ] Patch extractor (split test vs. gold)
- [ ] Problem statement + hints extractor
- [ ] Quality filters (configurable)
- [ ] JSONL emitter (SWE-bench-compatible schema)

### Phase 2: Harness + Environment Discovery Agent
- [ ] Workspace manager (bare clone, worktrees, cleanup)
- [ ] Agent SDK integration (`run_agent_task` wrapper)
- [ ] Environment Discovery prompt and output parsing
- [ ] Caching layer (by repo+version)
- [ ] Cost tracking and aggregation
- [ ] Retry logic with prompt amendment on failure
- [ ] Progress reporting (live CLI output)

### Phase 3: Validation Agent
- [ ] Validation workspace setup (patches, env spec)
- [ ] Validation agent prompt and output parsing
- [ ] FAIL_TO_PASS / PASS_TO_PASS extraction
- [ ] Parallel validation with asyncio semaphore
- [ ] Result persistence for resumption

### Phase 4: End-to-End Integration
- [ ] Docker container setup for agent sessions
- [ ] End-to-end integration tests
- [ ] Conformance test against SWE-bench
- [ ] Resumption (`--resume`) across all stages
- [ ] HuggingFace upload support
- [ ] Documentation and usage guide


## 12. Open Questions

1. **Docker strategy.** Should the harness build one Docker image per repo
   (with dependencies baked in), or use a generic image and let the agent
   install dependencies each time? The former is faster for validation
   (many instances per repo); the latter is simpler to implement first.

2. **Test subset selection.** For repos with very large test suites (>30
   min), should the agent select a relevant subset of tests per instance,
   or always run the full suite?

3. **Existing SWE-bench data.** When processing repos already in SWE-bench,
   should we reuse their `MAP_VERSION_TO_INSTALL` as a hint to the agent,
   or always discover from scratch?

4. **Multi-language repos.** How to handle repos with mixed languages
   (e.g., Python backend + TypeScript frontend)? Should the agent produce
   multiple EnvironmentSpecs?

5. **Version granularity.** SWE-bench uses major.minor versions for
   caching. Should we support patch-level (major.minor.patch) for repos
   with fast release cycles?

6. **Agent model selection.** Should env discovery (harder, exploratory)
   use a different model than validation (more procedural)? E.g., Opus
   for discovery, Sonnet for validation?
