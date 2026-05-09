# SWE-benchify

A harness that dispatches [Claude Code](https://claude.ai/claude-code) agents to transform GitHub repositories into [SWE-bench](https://github.com/princeton-nlp/SWE-bench)-compatible benchmarks.

Given a list of GitHub repos, SWE-benchify:

1. Collects merged pull requests that reference issues
2. Extracts gold patches, test patches, and problem statements
3. Dispatches a Claude Code agent to discover the build/test environment
4. Dispatches a Claude Code agent to validate each instance (run tests before and after the fix)
5. Applies quality filters
6. Emits a SWE-bench-compatible JSONL dataset

## Quickstart

```bash
pip install -e ".[dev]"
```

### Configuration

Create a `swebenchify.yaml`:

```yaml
repos:
  - pallets/flask

github:
  token: $GITHUB_TOKEN

pipeline:
  pr_after: "2021-01-01T00:00:00Z"
  pr_before: "2023-06-01T00:00:00Z"

output:
  dir: ./output
```

### Run the full pipeline

```bash
export GITHUB_TOKEN=ghp_...
export ANTHROPIC_API_KEY=sk-ant-...

swebenchify run -c swebenchify.yaml
```

### Run individual stages

```bash
# Collect PRs only
swebenchify collect -c swebenchify.yaml

# Validate candidates (requires prior collection + extraction)
swebenchify validate -c swebenchify.yaml --input output/pallets__flask-candidates.jsonl

# Apply filters and emit dataset
swebenchify emit -c swebenchify.yaml --input output/validated.jsonl
```

## Example: pallets/flask

Running SWE-benchify on `pallets/flask` with PRs from 2021-01 to 2023-06:

**Stage 1-2 (PR Collection + Patch Extraction):**
```
Collected 110 candidate PRs
Extracted 37 viable candidates (have patch + test_patch + problem_statement)
```

Compared against the published SWE-bench dataset (11 Flask instances): **100% overlap** — all 11 SWE-bench instances were found in our output.

**Stage 3 (Environment Discovery):**
The agent explored the Flask repo at commit `182ce3d` and discovered:

```json
{
  "language": "python",
  "language_version": "3.11",
  "package_manager": "pip",
  "install_cmd": "pip install -e '.[async,dotenv]' -r requirements/tests.txt",
  "test_cmd": "python -m pytest tests/ -x --tb=short -q"
}
```

Cost: $1.13 | 43 turns | 175s

**Stage 4 (Instance Validation):**
Validating `pallets__flask-5063` — the agent applied the test patch, ran tests, applied the gold patch, and ran tests again:

```
Status: valid
FAIL_TO_PASS: tests/test_cli.py::TestRoutes::test_subdomain
              tests/test_cli.py::TestRoutes::test_host
PASS_TO_PASS: 475 tests
```

**FAIL_TO_PASS matches SWE-bench exactly.** Cost: $0.86 | 21 turns | 87s

## Architecture

SWE-benchify is a **harness**, not an agent framework. It uses the [Claude Code Agent SDK](https://pypi.org/project/claude-code-sdk/) to dispatch Claude Code sessions and collects structured JSON output from each session.

```
User Config (repos, tokens)
        │
        ▼
   ┌─────────────────┐
   │  Pipeline        │
   │  Controller      │── async orchestrator with bounded concurrency
   └──┬──────┬────────┘
      │      │
  Mechanical  Agentic
  (Python)   (Claude Code)
      │      │
      ▼      ▼
  ┌──────┐ ┌──────────┐
  │St 1-2│ │ St 3: Env │── agent explores repo, writes env_spec.json
  │Collect│ │ Discovery │
  │Extract│ ├──────────┤
  └──────┘ │ St 4: Val │── agent runs tests, writes validation_result.json
           │ idation   │
  ┌──────┐ └──────────┘
  │St 5-6│
  │Filter│
  │ Emit │
  └──────┘
```

**Mechanical stages** (1, 2, 5, 6) are pure Python — GitHub API calls, diff parsing, quality filters, JSONL serialization.

**Agentic stages** (3, 4) dispatch Claude Code with a task-specific prompt and `cwd` set to a workspace directory. The agent writes structured JSON files; the harness reads them.

## Configuration Reference

```yaml
repos:
  - owner/repo
  - owner/private-repo

github:
  token: $GITHUB_TOKEN            # default token (env var)
  tokens:                          # per-repo overrides
    owner/private-repo: $PRIVATE_TOKEN

pipeline:
  max_concurrent_repos: 4          # parallel repo processing
  max_concurrent_validations: 8    # parallel validation runs
  max_prs_per_repo: null           # null = no limit
  pr_after: "2021-01-01T00:00:00Z" # ISO 8601 date cutoff
  pr_before: "2024-01-01T00:00:00Z"

agent:
  max_attempts: 3                  # retries per agent task
  sandbox: local                   # "local" or "docker"
  docker_image: python:3.11-slim   # base image for docker sandbox
  env_discovery:
    max_turns: 80
    budget_usd: 5.0
  validation:
    max_turns: 60
    budget_usd: 3.0

filters:
  min_problem_statement_words: 40
  max_patch_lines: 500
  min_patch_lines: 1
  min_fail_to_pass: 1
  no_urls_in_problem: true
  no_shas_in_problem: true
  no_image_only_problem: true

output:
  dir: ./output
  upload_to_hf: false
  hf_repo: null
```

## Output Format

Output conforms to the `SWEbenchInstance` schema from `swebench.harness.constants`:

```json
{
  "repo": "pallets/flask",
  "instance_id": "pallets__flask-5063",
  "base_commit": "182ce3dd15dfa3537391c3efaf9c3ff407d134d4",
  "patch": "diff --git a/...",
  "test_patch": "diff --git a/...",
  "problem_statement": "Issue title\nIssue body...",
  "hints_text": "Comment before fix was submitted...",
  "created_at": "2023-04-14T16:36:54Z",
  "version": "2.3",
  "FAIL_TO_PASS": "[\"tests/test_cli.py::TestRoutes::test_subdomain\", ...]",
  "PASS_TO_PASS": "[\"tests/test_basic.py::test_request_dispatching\", ...]",
  "environment_setup_commit": null
}
```

## Development

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -q

# Run mechanical stages on Flask (needs GITHUB_TOKEN)
GITHUB_TOKEN=... python scripts/test_flask.py

# Run agentic stages on Flask (needs GITHUB_TOKEN + ANTHROPIC_API_KEY)
GITHUB_TOKEN=... python scripts/test_agentic.py
```

## How It Works

See [SPEC.md](SPEC.md) for the full specification.
