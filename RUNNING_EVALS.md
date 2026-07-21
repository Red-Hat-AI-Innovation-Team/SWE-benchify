# Running Harbor Evaluations on a Node

Guide for running SWE-benchify evaluations using Harbor on an H100 node (RHEL 9, Podman, no Docker).

## Prerequisites

- RHEL 9 node with Podman installed
- `uv` installed
- SSH access
- GCP credentials (for Vertex AI) or Anthropic API key

## 1. Podman + Docker Compose v2 Setup

Harbor requires `docker compose` (v2, the Go binary). Podman is available but needs compatibility shims.

### Install `podman-docker` (provides `/usr/bin/docker` wrapper)

```bash
sudo dnf install -y podman-docker
```

### Install Docker Compose v2 as a CLI plugin

The real Docker Compose v2 Go binary (NOT `podman-compose`) is required. `podman-compose` has incompatible CLI flags.

```bash
mkdir -p ~/.docker/cli-plugins
COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep '"tag_name"' | sed 's/.*"v//' | sed 's/".*//')
curl -SL "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
```

### Enable Podman socket

```bash
systemctl --user enable --now podman.socket
```

### Set DOCKER_HOST

```bash
export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
echo 'export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"' >> ~/.bashrc
```

### Verify

```bash
docker compose version   # should show v2.x.x
docker info              # should show podman backend
```

### Cgroup delegation (if you hit `cpu controller not available` errors)

Rootless podman doesn't have CPU cgroup controllers by default. Fix:

```bash
sudo mkdir -p /etc/systemd/system/user@.service.d
sudo tee /etc/systemd/system/user@.service.d/delegate.conf <<EOF
[Service]
Delegate=cpu cpuset io memory pids
EOF
sudo systemctl daemon-reload
```

Log out and back in for it to take effect. Or pass `--cpus ignore --memory ignore` to Harbor to skip resource limits.

## 2. Clone and Install SWE-benchify

```bash
cd /mnt/nvme0n1/$USER
git clone <SWE-benchify-repo-url> SWE-benchify
cd SWE-benchify

uv venv -p 3.12 .venv
source .venv/bin/activate
uv pip install -e .
```

## 3. Generate Harbor Tasks

Convert instance JSONL files to Harbor task directories:

```bash
swebenchify harbor -i output/instances-go.jsonl -o ./benchmark-go
swebenchify harbor -i output/instances-python.jsonl -o ./benchmark-python
swebenchify harbor -i output/instances-java.jsonl -o ./benchmark-java
swebenchify harbor -i output/instances-rust.jsonl -o ./benchmark-rust
```

## 4. Environment Variables

### Direct Anthropic API

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Vertex AI

```bash
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project"
export CLOUD_ML_REGION="us-east5"
```

GCP credentials must be mounted into the container (see run commands below). The ADC file is typically at `~/.config/gcloud/application_default_credentials.json`.

## 5. Run Evaluations

The `my_factory.py` agent (in the repo root) runs Factory's swebench workflow inside Harbor containers.

### With Vertex AI

```bash
PYTHONPATH=. uvx harbor run -p ./benchmark-go/harbor-tasks \
  --agent "my_factory:SwebenchFactoryCeo" \
  --model anthropic/claude-opus-4-6 \
  -n 8 --job-name eval-go \
  --mounts "$HOME/.config/gcloud/application_default_credentials.json:/tmp/gcp-creds.json:ro"
```

### With Anthropic API directly

```bash
PYTHONPATH=. uvx harbor run -p ./benchmark-go/harbor-tasks \
  --agent "my_factory:SwebenchFactoryCeo" \
  --model anthropic/claude-sonnet-4 \
  -n 8 --job-name eval-go
```

### All languages

```bash
# Go (83 instances)
PYTHONPATH=. uvx harbor run -p ./benchmark-go/harbor-tasks \
  --agent "my_factory:SwebenchFactoryCeo" \
  --model anthropic/claude-opus-4-6 \
  -n 8 --job-name eval-go \
  --mounts "$HOME/.config/gcloud/application_default_credentials.json:/tmp/gcp-creds.json:ro"

# Python (12 instances)
PYTHONPATH=. uvx harbor run -p ./benchmark-python/harbor-tasks \
  --agent "my_factory:SwebenchFactoryCeo" \
  --model anthropic/claude-opus-4-6 \
  -n 4 --job-name eval-python \
  --mounts "$HOME/.config/gcloud/application_default_credentials.json:/tmp/gcp-creds.json:ro"

# Java (2 instances)
PYTHONPATH=. uvx harbor run -p ./benchmark-java/harbor-tasks \
  --agent "my_factory:SwebenchFactoryCeo" \
  --model anthropic/claude-opus-4-6 \
  -n 2 --job-name eval-java \
  --mounts "$HOME/.config/gcloud/application_default_credentials.json:/tmp/gcp-creds.json:ro"

# Rust (1 instance)
PYTHONPATH=. uvx harbor run -p ./benchmark-rust/harbor-tasks \
  --agent "my_factory:SwebenchFactoryCeo" \
  --model anthropic/claude-opus-4-6 \
  -n 1 --job-name eval-rust \
  --mounts "$HOME/.config/gcloud/application_default_credentials.json:/tmp/gcp-creds.json:ro"
```

### Useful flags

| Flag | Purpose |
|---|---|
| `-n 8` | Concurrency (parallel tasks) |
| `-l 1` | Limit to 1 task (for testing) |
| `--job-name eval-go` | Name the job for organized results |
| `--mounts "host:container:ro"` | Mount files into the container |
| `--cpus ignore --memory ignore` | Skip cgroup resource limits |
| `--debug` | Enable debug logging |

## 6. Results

Results are written to `jobs/<job-name>/`:

```bash
# View results
harbor view jobs

# Check a specific job
cat jobs/eval-go/result.json | python3 -m json.tool

# Upload/share results
harbor upload jobs/eval-go
```

### Debugging a failed trial

```bash
# Check exception
cat jobs/<job-name>/<trial-dir>/exception.txt

# Check factory log
cat jobs/<job-name>/<trial-dir>/agent/factory-ceo.txt

# Check Claude session (may need sudo for file permissions)
sudo find jobs/<job-name>/<trial-dir>/agent/sessions/ -name "*.jsonl"
```

## Model Selection Notes

Factory's swebench workflow hardcodes `--model opus` when invoking Claude Code. The `my_factory.py` agent overrides this by setting `ANTHROPIC_DEFAULT_OPUS_MODEL` to whatever `--model` you pass to Harbor. This ensures Claude Code resolves the `opus` alias to your specified model version.

If using Vertex AI, make sure the model version you specify is enabled on your Vertex project. Check with:

```bash
claude --model "claude-opus-4-6" --print "hello"
```

## Troubleshooting

| Error | Fix |
|---|---|
| `podman-compose: error: invalid choice` | Install Docker Compose v2 Go binary (not podman-compose) |
| `crun: the requested cgroup controller 'cpu' is not available` | Apply cgroup delegation fix (section 1) or use `--cpus ignore` |
| `Could not load the default credentials` | Mount GCP credentials with `--mounts` flag |
| `model X is not available on your vertex deployment` | Use an enabled model version, e.g. `claude-opus-4-6` |
| `FileNotFoundError: harbor_templates/instruction.md.template` | Use editable install: `uv pip install -e .` |
