# SWE-benchify

[![CI](https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify/actions/workflows/ci.yml/badge.svg)](https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify/actions/workflows/ci.yml)

A harness that dispatches [Claude Code](https://claude.ai/claude-code) agents to transform GitHub repositories into [SWE-bench](https://github.com/princeton-nlp/SWE-bench)-compatible benchmarks.

Supports **Python** and **Go** repositories out of the box.

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

Create a `swebenchify.yaml`. Language is detected automatically from the repository.

**Python repo:**

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

**Go repo:**

```yaml
repos:
  - kubernetes/kubernetes

github:
  token: $GITHUB_TOKEN

pipeline:
  pr_after: "2023-01-01T00:00:00Z"
  pr_before: "2024-06-01T00:00:00Z"

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

## Examples

### pallets/flask (Python)

Running SWE-benchify on `pallets/flask` with PRs from 2021-01 to 2023-06:

**Stage 1-2 (PR Collection + Patch Extraction):**
```
Collected 110 candidate PRs
Extracted 37 viable candidates (have patch + test_patch + problem_statement)
```

Compared against the published SWE-bench dataset (11 Flask instances): **100% overlap** — all 11 SWE-bench instances were found in our output.

**Stage 3 (Environment Discovery):**
The agent explored the Flask repo at commit `182ce3d` and produced:

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

### kubernetes/kubernetes (Go)

For Go repositories, the environment discovery agent reads `go.mod` and CI
configuration rather than installing packages.

**Stage 3 (Environment Discovery):**
The agent inspects `go.mod`, `Makefile`, and `.github/workflows/` to produce a
`go_env_spec.json`:

```json
{
  "language": "go",
  "go_version": "1.22",
  "build_cmd": "make build",
  "test_cmd": "go test ./pkg/...",
  "module_mode": "vendored",
  "goflags": "-mod=vendor",
  "system_dependencies": []
}
```

The `go_version` is used to derive a stable `environment_setup_commit` by
scanning `git log` for the earliest commit whose `go.mod` declares that Go
directive — ensuring the emitted instance is reproducible.

**Stage 4 (Instance Validation):**
Go validation uses Docker with a per-spec image keyed on the `env_spec_hash`.
Test output is parsed from `go test -json` so subtests, packages, and
build failures are distinguished cleanly:

```
Status: valid
FAIL_TO_PASS: TestReconciler/pod_created
PASS_TO_PASS: 1402 tests
compiled: true
```

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
  env_discovery:
    max_turns: 80
    budget_usd: 5.0                # Python; Go discovery is read-only (budget_usd: 2.0)
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

docker:
  registry: ghcr.io/red-hat-ai-innovation-team  # GHCR org prefix
  push_images: true                              # push after build
```

## Python Pipeline

For Python repositories, a standalone pipeline script handles discovery and
validation without the full agentic flow:

```bash
python scripts/discover_and_validate_python.py \
    --repo containers/podman-compose \
    --max-prs 300 \
    --timeout 600
```

The script auto-detects environment settings from `pyproject.toml` and
`requirements.txt`, or accepts explicit overrides:

```bash
python scripts/discover_and_validate_python.py \
    --repo pallets/flask \
    --python-version 3.11 \
    --install-cmd "pip install -e '.[async,dotenv]'" \
    --test-cmd "pytest tests/" \
    --pre-install "pip install -r requirements/tests.txt"
```

### Custom base images

Repos that need infrastructure beyond `python:slim` (e.g. PostgreSQL, Redis)
can specify a custom Docker base image:

```bash
python scripts/discover_and_validate_python.py \
    --repo pulp/pulp_ansible \
    --base-image ghcr.io/pulp/pulp-ci-centos9 \
    --install-cmd "pip install -e ." \
    --test-cmd "pytest -v --pyargs pulp_ansible.tests.unit" \
    --pre-install "pip install mock pytest-django"
```

The `--run-preamble` flag injects shell commands before the test phase,
useful for starting services:

```bash
--run-preamble "/init & sleep 5; curl -sf http://localhost/pulp/api/v3/status/"
```

### GitHub Actions workflow

The `Python Pipeline` workflow (`.github/workflows/python-pipeline.yml`)
runs the pipeline in CI:

```bash
gh workflow run python-pipeline.yml \
    -f repo="containers/podman-compose" \
    -f max_prs=300
```

All environment overrides (`python_version`, `install_cmd`, `test_cmd`,
`pre_install`, `base_image`, `run_preamble`) are available as workflow inputs.

## Docker Images

### Go images

Go instances are validated inside Docker containers built from a per-repo
`GoEnvironmentSpec`. Each spec produces a deterministic image tag:

```
swebenchify-go-{owner}__{repo}-{env_spec_hash[:12]}
```

When `docker.push_images` is `true` in the config, the pipeline automatically
pushes images to the configured registry after building them locally. The
registry-qualified name (e.g. `ghcr.io/red-hat-ai-innovation-team/swebenchify-go-kubernetes__kubernetes-ff85eb477eda`)
is written to each emitted `TaskInstance.image_name`, making instances
self-contained for downstream consumers.

Specs are also persisted to `data/go-specs/{env_spec_hash}.json` during
pipeline runs so the standalone build script stays in sync.

The `Build Go Images` workflow (`.github/workflows/build-images.yml`) can
build and push images from a CI environment without running the full pipeline:

```bash
gh workflow run build-images.yml \
  -f instances_jsonl=output/instances.jsonl \
  -f registry=ghcr.io/red-hat-ai-innovation-team
```

### Python images

Python validation images are built on the fly during pipeline runs. The base
image defaults to `python:{version}-slim` but can be overridden via
`--base-image` for repos with special infrastructure requirements.

The `EnvironmentSpec` controls the Dockerfile:

```json
{
  "language": "python",
  "language_version": "3.11",
  "package_manager": "pip",
  "install_cmd": "pip install -e .",
  "test_cmd": "pytest",
  "pre_install": ["pip install -r requirements.txt"],
  "base_image": "",
  "run_preamble": ""
}
```

### Standalone build script

When images are missing from the registry, use the standalone script:

```bash
python scripts/build_and_push_images.py \
  --instances output/instances.jsonl \
  --specs-dir data/go-specs \
  --registry ghcr.io/red-hat-ai-innovation-team \
  --update-jsonl
```

**Prerequisite:** GHCR authentication. Fine-grained GitHub PATs do not support
GHCR — you need a classic PAT with `write:packages` scope:

```bash
echo "$PAT" | docker login ghcr.io -u USERNAME --password-stdin
```

## Output Format

Output conforms to the `SWEbenchInstance` schema from `swebench.harness.constants`.
Every emitted instance has a non-null `environment_setup_commit`.

**Python instance:**

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
  "environment_setup_commit": "9cc500efeec170a6d4bf0a53f1f03f0e16ea0f22"
}
```

**Go instance** (version string encodes the Go toolchain era):

```json
{
  "repo": "kubernetes/kubernetes",
  "instance_id": "kubernetes__kubernetes-115234",
  "base_commit": "a1b2c3d4...",
  "patch": "diff --git a/...",
  "test_patch": "diff --git a/...",
  "problem_statement": "Issue title\nIssue body...",
  "hints_text": "",
  "created_at": "2023-09-12T11:04:22Z",
  "version": "1.22-ab3f1200",
  "FAIL_TO_PASS": "[\"TestReconciler/pod_created\"]",
  "PASS_TO_PASS": "[\"TestReconciler/pod_updated\", ...]",
  "environment_setup_commit": "e5f6a7b8..."
}
```

## Harbor Integration

SWE-benchify datasets can be exported to the [Harbor framework](https://www.harborframework.com/) for agent evaluation.

### Convert to Harbor tasks

```bash
uv run python scripts/to_harbor.py \
    -i output/rh-v1/all-task-instances.jsonl \
    -o output/harbor-tasks
```

This generates one Harbor task directory per instance with a Dockerfile, test verifier, and oracle solution.

### Run with Harbor

```bash
# Single task with Claude Code
harbor run \
    -p output/harbor-tasks/argoproj__argo-cd-26039 \
    -a claude-code \
    -m claude-sonnet-4-6 \
    -e docker

# Full dataset
harbor run \
    -p output/harbor-tasks \
    -a claude-code \
    -m claude-sonnet-4-6 \
    -e docker \
    -n 4
```

Supports Docker and podman (via `DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock`).

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
