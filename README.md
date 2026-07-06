# SWE-benchify

[![CI](https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify/actions/workflows/ci.yml/badge.svg)](https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify/actions/workflows/ci.yml)

A harness that dispatches [Claude Code](https://claude.ai/claude-code) agents to transform GitHub repositories into [SWE-bench](https://github.com/princeton-nlp/SWE-bench)-compatible benchmarks.

Supports **Python**, **Go**, **Java** (Maven), and **Rust** (Cargo) repositories out of the box.

Given a list of GitHub repos, SWE-benchify:

1. Collects merged pull requests that reference issues
2. Extracts gold patches, test patches, and problem statements
3. Dispatches a Claude Code agent to discover the build/test environment
4. Dispatches a Claude Code agent to validate each instance (run tests before and after the fix)
5. Applies quality filters
6. Emits a SWE-bench-compatible JSONL dataset
7. Optionally emits [Harbor](https://github.com/harbor-framework/harbor)-format task directories for standardized agent evaluation

## Quickstart

```bash
pip install -e ".[dev]"
```

### Configuration

Create a config file under `configs/`. Language is detected automatically from the repository.

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

**Java repo:**

```yaml
repos:
  - apache/commons-lang

github:
  token: $GITHUB_TOKEN

pipeline:
  pr_after: "2022-01-01T00:00:00Z"
  pr_before: "2024-01-01T00:00:00Z"

output:
  dir: ./output
```

**Rust repo:**

```yaml
repos:
  - cloudflare/pingora

github:
  token: $GITHUB_TOKEN

pipeline:
  pr_after: "2024-01-01T00:00:00Z"
  pr_before: "2025-06-01T00:00:00Z"

output:
  dir: ./output
```

### Environment variables

| Variable | Required for | Description |
|----------|-------------|-------------|
| `GITHUB_TOKEN` | All stages | GitHub personal access token. Used to fetch PRs and issue metadata via the GitHub API. Public repos need no special scopes; private repos need `repo` scope. |
| `ANTHROPIC_API_KEY` | Stages 3-4 | Anthropic API key. Used by the [Claude Code Agent SDK](https://pypi.org/project/claude-code-sdk/) to dispatch agents for environment discovery (stage 3) and instance validation (stage 4). Not needed for collection-only runs (`swebenchify collect`). |

### Run the full pipeline

```bash
export GITHUB_TOKEN=ghp_...
export ANTHROPIC_API_KEY=sk-ant-...

swebenchify run -c configs/swebenchify.yaml

# With Harbor output (emits task directories alongside JSONL)
swebenchify run -c configs/swebenchify.yaml --harbor-output
```

### Run individual stages

```bash
# Collect PRs only
swebenchify collect -c configs/swebenchify.yaml

# Validate candidates (requires prior collection + extraction)
swebenchify validate -c configs/swebenchify.yaml --input output/pallets__flask-candidates.jsonl

# Apply filters and emit dataset
swebenchify emit -c configs/swebenchify.yaml --input output/validated.jsonl

# Emit with Harbor output
swebenchify emit -c configs/swebenchify.yaml --input output/validated.jsonl --harbor-output

# Convert existing JSONL to Harbor format (standalone)
swebenchify harbor -i output/all-task-instances.jsonl -o ./my-benchmark
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

## Synthetic Instance Generation

In addition to mining real PRs, SWE-benchify can **synthesize** realistic bug instances from any GitHub repo. The synthesizer introduces plausible bugs via LLM-guided mutation, generates issue descriptions from real test output, and produces instances in the same SWE-bench format.

### Quick start

```bash
# Clone and point at a repo
git clone https://github.com/pallets/flask.git /tmp/flask

# Generate 5 synthetic bugs
swebenchify synthesize \
  --repo /tmp/flask \
  --language python \
  --max-mutations 5
```

Output: `output/local__flask-synthetic-candidates.jsonl`

### CLI reference

```
swebenchify synthesize --repo <REPO> --language <LANG> [OPTIONS]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--repo` | yes | | Local path or `owner/repo` slug |
| `--language` | yes | | `python`, `go`, `rust`, or `java` |
| `--max-mutations` | no | `10` | Maximum bugs to generate |
| `--base-commit` | no | `HEAD` | Target commit SHA (auto-detected for local repos) |
| `--model` | no | `sonnet` | Claude model: `sonnet`, `haiku`, or `opus` |
| `--output-dir` | no | `output` | Directory for output JSONL |

### How it works

1. **Find mutation targets** — scans the repo for functions with edge-case signals (error handling, type checks, None guards) and existing test coverage
2. **Introduce bugs** — uses Claude to inject realistic, multi-line mutations (type confusion, wrong method calls, incomplete refactoring, stale references)
3. **Generate issue text** — captures real test output from the buggy code and frames it as a developer-filed issue, with references to real PR/issue numbers mined from git history
4. **Emit candidates** — writes SWE-bench-compatible JSONL with `patch`, `test_patch`, `problem_statement`, and `base_commit`

The synthesizer enforces an information firewall: issue descriptions contain only test output and behavioral symptoms, never implementation details from the patch. This makes synthetic instances difficult to distinguish from real ones — in evaluation, an Opus judge classified synthetic instances as real with >90% confidence across Python, Go, Java, and Rust repos.

### Example output

Each line in the output JSONL is a `CandidateInstance`:

```json
{
  "repo": "pallets/flask",
  "instance_id": "pallets__flask-93001",
  "base_commit": "a1b2c3d...",
  "patch": "diff --git a/src/flask/cli.py b/src/flask/cli.py\n@@ -191,7 +191,12 @@...",
  "test_patch": "diff --git a/tests/test_async.py b/tests/test_async.py\n...",
  "problem_statement": "tests/test_cli.py::test_locate_app_raises[cliapp.factory-no_app]\n\n...",
  "created_at": "2026-06-30T12:00:00Z",
  "provenance": "synthetic"
}
```

For sample instances that successfully fooled an Opus judge across multiple languages, see [PR #90](https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify/pull/90).

### Validation

Synthetic candidates can be validated with the same Docker-based F2P/P2P pipeline used for real instances. This confirms that the test patch fails before the fix and passes after:

```bash
# Validate with the full pipeline
swebenchify validate --input output/local__flask-synthetic-candidates.jsonl
```

### Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Required. Used by Claude to generate mutations and issue text. |

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
  ┌───────┐ ┌──────────┐
  │St 1-2 │ │ St 3: Env │── agent explores repo, writes env_spec.json
  │Collect│ │ Discovery │
  │Extract│ ├──────────┤
  └───────┘ │ St 4: Val │── agent runs tests, writes validation_result.json
            │ idation   │
  ┌───────┐ └──────────┘
  │St 5-6 │
  │Filter │
  │Emit   │
  └───────┘
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

harbor:
  emit: false                                    # emit Harbor task dirs alongside JSONL
  registry_url: ""                               # container registry URL for task TOML
  org_name: swebenchify                          # organization name in task naming
```

## Standalone Pipeline

A unified script runs the full pipeline (collect, extract, filter, validate,
emit) for any supported language:

```bash
# Python
python scripts/discover_and_validate.py --language python \
    --repo containers/podman-compose --max-prs 300

# Java (Maven)
python scripts/discover_and_validate.py --language java \
    --repo apache/commons-lang --max-prs 500

# Rust (Cargo)
python scripts/discover_and_validate.py --language rust \
    --repo cloudflare/pingora --max-prs 200
```

The script auto-detects language version and build settings from project files
(`pyproject.toml`, `pom.xml`, `Cargo.toml`, `rust-toolchain.toml`). Override
any detected value with CLI flags:

```bash
python scripts/discover_and_validate.py --language python \
    --repo pallets/flask \
    --lang-version 3.11 \
    --install-cmd "pip install -e '.[async,dotenv]'" \
    --test-cmd "pytest tests/" \
    --pre-install "pip install -r requirements/tests.txt"
```

### Language-specific options

**Python** supports `--base-image` for custom Docker base images (e.g.
repos needing PostgreSQL or Redis) and `--run-preamble` to inject shell
commands before the test phase (e.g. starting services).

**Java** supports `--jira-projects` to match Jira issue keys when collecting
PRs (e.g. `--jira-projects WFLY,WFCORE`).

**Rust** supports `--build-cmd`, `--features`, and `--system-deps`. Inline
`#[cfg(test)]` blocks are automatically moved from the gold patch to the test
patch.

### GitHub Actions workflows

Each language has a workflow that invokes the unified script:

```bash
gh workflow run python-pipeline.yml -f repo="containers/podman-compose"
gh workflow run java-pipeline.yml -f repo="apache/commons-lang"
gh workflow run rust-pipeline.yml -f repo="cloudflare/pingora"
```

Language-specific overrides are available as workflow inputs.

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

### Java images

Java validation images use `maven:3-eclipse-temurin-{java_version}` as the
base image (defaulting to Java 17). The image pre-resolves Maven dependencies
so validation runs start quickly.

### Rust images

Rust validation images use `rust:{version}-slim` as the base image. Like Go,
each spec produces a deterministic image tag based on the `env_spec_hash`.
The `RustSpecRegistry` maps spec hashes to stable version strings of the
form `{rust_version}-{hash[:8]}` (e.g. `1.84-ab3f1200`).

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

## Harbor Integration

SWE-benchify can emit benchmarks in [Harbor](https://github.com/harbor-framework/harbor) task format, enabling evaluation with any Harbor-compatible agent (Claude Code, Codex CLI, OpenHands, Aider, and others). Harbor provides containerized isolation, parallel execution at scale, and a standardized reward interface.

### Usage

There are three ways to produce Harbor output:

```bash
# 1. Standalone — convert existing JSONL to Harbor format
swebenchify harbor -i output/go-v1/all-task-instances.jsonl -o ./my-benchmark

# 2. Pipeline flag — emit Harbor alongside JSONL
swebenchify run -c configs/swebenchify-go-v1.yaml --harbor-output

# 3. Config-driven — set harbor.emit: true in YAML (see Configuration Reference)
swebenchify emit -c configs/swebenchify.yaml --input output/validated.jsonl
```

### CLI reference

```
swebenchify harbor -i <INPUT> -o <OUTPUT> [OPTIONS]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--input, -i` | yes | | Path to TaskInstance JSONL file |
| `--output, -o` | yes | | Output directory for Harbor task directories |
| `--registry-url` | no | `None` | Container registry URL for `docker_image` references in task TOML |
| `--env-specs` | no | `None` | Path to env specs JSON file (maps instance IDs to environment specs) |

The `--harbor-output` flag is also available on `swebenchify run` and `swebenchify emit`.

### Task directory structure

Each instance produces a self-contained task directory:

```
harbor-tasks/
├── registry.json                          # Index of all tasks
├── dataset.toml                           # Dataset metadata (name, languages, repos)
└── go__etcd-io__etcd-19086/
    ├── instruction.md                     # Problem statement for the agent
    ├── task.toml                          # Harbor config (timeouts, network, docker image)
    ├── environment/Dockerfile             # Language-specific build environment
    ├── solution/
    │   ├── solve.sh                       # Oracle solution (applies gold patch)
    │   └── patch.diff                     # Gold patch
    └── tests/
        ├── test.sh                        # Test runner + grading script
        ├── test.patch                     # Canonical test patch
        └── config.json                    # FAIL_TO_PASS / PASS_TO_PASS lists
```

Harbor isolates the `tests/` and `solution/` directories from the agent during the solve phase — they are uploaded only after the agent finishes.

### Anti-reward-hacking

The generated `test.sh` scripts include anti-reward-hacking logic that prevents agents from gaming benchmarks by modifying test files:

1. **Detect** — after the agent finishes, scan `git diff` and `git ls-files --others` for test file modifications using language-specific patterns (`*_test.go`, `test_*.py`, `*Test.java`, `*_test.rs`, `conftest.py`, files under `tests/`, `e2e/`, `testing/`)
2. **Revert** — surgically revert only test file changes (`git checkout` for modified files, `os.remove` for new files), preserving the agent's source code fixes
3. **Overlay** — apply the canonical `test.patch` on top of the agent's source changes
4. **Grade** — run tests and compare against the expected FAIL_TO_PASS / PASS_TO_PASS lists

Templates are provided for all four supported languages: Go, Python, Java (Maven Surefire), and Rust (cargo test).

### Running evaluations

Once you have Harbor task directories, run evaluations with the `harbor` CLI:

```bash
# Install Harbor
uv tool install harbor

# Run an agent against your benchmark
harbor run --dataset ./my-benchmark \
  --agent claude-code \
  --model anthropic/claude-sonnet-4 \
  --n-concurrent 4
```

See the [Harbor documentation](https://www.harborframework.com/) for agent configuration, remote execution (Daytona, Modal), and result analysis.

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

See [SPEC.md](docs/SPEC.md) for the full specification.
