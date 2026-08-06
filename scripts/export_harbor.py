"""Export SWE-benchify instances as a Harbor dataset.

Converts our JSONL instances into Harbor task directories with:
- task.toml (metadata, environment config)
- instruction.md (problem statement)
- environment/Dockerfile (references our GHCR image)
- tests/test.sh (runs Go tests, checks FAIL_TO_PASS)
- solution/oracle.patch (gold patch)

Usage:
    python3 scripts/export_harbor.py --input data/swebenchify-haiku-hard.jsonl --org red-hat-ai --name haiku-hard
    python3 scripts/export_harbor.py --input data/swebenchify-847.jsonl --org red-hat-ai --name swebenchify-847
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys


def slugify(text: str, max_len: int = 60) -> str:
    return re.sub(r"[^a-z0-9-]", "-", text.lower().replace("_", "-").replace("__", "-"))[:max_len].rstrip("-")


def generate_task_dir(inst: dict, org: str, output_dir: str):
    """Generate a Harbor task directory for one instance."""
    iid = inst["instance_id"]
    task_slug = slugify(iid)
    task_name = f"{org}/{task_slug}"
    task_dir = os.path.join(output_dir, task_slug)
    os.makedirs(task_dir, exist_ok=True)

    repo = inst["repo"]
    image_name = inst.get("image_name", "")
    patch = inst.get("patch", "")
    problem = inst.get("problem_statement", "")
    f2p = inst.get("FAIL_TO_PASS", "[]")
    p2p = inst.get("PASS_TO_PASS", "[]")
    if isinstance(f2p, str):
        f2p = json.loads(f2p)
    if isinstance(p2p, str):
        p2p = json.loads(p2p)

    bug_spec = inst.get("_pipeline", {}).get("bug_spec", {})
    bug_file = bug_spec.get("file", "")
    bug_category = bug_spec.get("bug_category", "")

    # task.toml
    with open(os.path.join(task_dir, "task.toml"), "w") as f:
        f.write(f"""version = "1.0"

[task]
name = "{task_name}"
authors = [{{name = "SWE-benchify", email = "swebenchify@redhat.com"}}]
keywords = ["swebenchify", "go", "{repo.replace('/', '-')}"]

[environment]
base_image = "{image_name}"
build_timeout_sec = 600.0
cpus = 2
memory = "8G"
storage = "20G"
network_mode = "public"

[verifier]
timeout_sec = 600.0

[agent]
timeout_sec = 3600.0
network_mode = "public"

[metadata]
family = "{task_slug}"
repo = "{repo}"
tags = ["swebenchify", "go", "{bug_category.lower().replace(' ', '-') if bug_category else 'unknown'}"]
visibility = "public"

[metadata.narrative]
description = \"\"\"{problem[:500].replace(chr(34), '')}\"\"\"

[metadata.oracle_scope]
sloc = {len(patch.splitlines())}
files = {len(set(x.split()[-1] for x in patch.splitlines() if x.startswith('diff --git')))}

[metadata.origin]
repo = "{repo}"
base_commit = "{inst.get('merge_commit') or inst.get('base_commit', '')}"
""")

    # instruction.md
    with open(os.path.join(task_dir, "instruction.md"), "w") as f:
        f.write(f"""## Task

{problem}

## General instructions

- The code repo is at /testbed.
- The repository is a Go project. Run tests with `go test`.
- Do NOT modify any test files (files ending in `_test.go`).
- Focus on making the minimal change needed to fix the described issue.
""")

    # environment/Dockerfile
    env_dir = os.path.join(task_dir, "environment")
    os.makedirs(env_dir, exist_ok=True)
    base_commit = inst.get("merge_commit") or inst.get("base_commit", "")
    with open(os.path.join(env_dir, "Dockerfile"), "w") as f:
        f.write(f"""FROM {image_name}

RUN apt-get update -qq && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/* || true

# Clone repo at base commit
RUN (git clone https://github.com/{repo}.git /testbed && \\
    cd /testbed && (git checkout {base_commit} || \\
    (git fetch origin {base_commit} && \\
     git checkout {base_commit}))) || \\
    (rm -rf /testbed && mkdir -p /testbed && cd /testbed && git init && \\
     curl -sL https://github.com/{repo}/archive/{base_commit}.tar.gz | \\
     tar xz --strip-components=1 && git add -A && git commit -q -m base)

# Introduce the bug (reverse-apply gold patch)
COPY oracle.patch /tmp/oracle.patch
RUN cd /testbed && git apply --reverse /tmp/oracle.patch || \\
    git apply --reverse --3way /tmp/oracle.patch || \\
    echo "WARNING: could not introduce bug"
RUN cd /testbed && git add -A && \\
    git -c user.name=eval -c user.email=eval@test commit -m "buggy state" --allow-empty

# Ensure /logs structure exists for Harbor verifier
RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts

WORKDIR /testbed
""")
    # Copy oracle.patch into environment dir for the Dockerfile COPY
    with open(os.path.join(env_dir, "oracle.patch"), "w") as f:
        f.write(patch)

    # tests/config.json
    tests_dir = os.path.join(task_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)

    config = {
        "instance_id": iid,
        "repo": repo,
        "FAIL_TO_PASS": f2p,
        "PASS_TO_PASS": p2p,
        "repo_language": "go",
    }
    with open(os.path.join(tests_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    # tests/test.patch
    test_patch = inst.get("test_patch", "")
    with open(os.path.join(tests_dir, "test.patch"), "w") as f:
        f.write(test_patch)

    # tests/test.sh -- use Harbor Go template
    pkg_dir = os.path.dirname(bug_file) or "."
    test_cmd = f"CGO_ENABLED=0 go test -v -count=1 -timeout 300s ./{pkg_dir}"

    templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "src", "swebenchify", "harbor_templates")
    template_path = os.path.join(templates_dir, "test_go.sh.template")
    from string import Template
    content = Template(open(template_path).read()).safe_substitute(test_command=test_cmd)

    test_sh_path = os.path.join(tests_dir, "test.sh")
    with open(test_sh_path, "w") as f:
        f.write(content)
    os.chmod(os.path.join(tests_dir, "test.sh"), 0o755)

    # solution/oracle.patch
    sol_dir = os.path.join(task_dir, "solution")
    os.makedirs(sol_dir, exist_ok=True)
    with open(os.path.join(sol_dir, "oracle.patch"), "w") as f:
        f.write(patch)

    return task_name


def generate_dataset_toml(org: str, name: str, task_names: list[str], output_dir: str):
    """Generate dataset.toml manifest."""
    with open(os.path.join(output_dir, "dataset.toml"), "w") as f:
        f.write(f"""[dataset]
name = "{org}/{name}"
description = "SWE-benchify synthetic Go benchmark instances"
keywords = ["swebenchify", "go", "synthetic-benchmark"]

[[dataset.authors]]
name = "SWE-benchify"
email = "swebenchify@redhat.com"

""")
        for task_name in task_names:
            content_hash = hashlib.sha256(task_name.encode()).hexdigest()
            f.write(f"""[[tasks]]
name = "{task_name}"
digest = "sha256:{content_hash}"

""")


def main():
    parser = argparse.ArgumentParser(description="Export to Harbor dataset")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--org", default="red-hat-ai", help="Harbor org name")
    parser.add_argument("--name", default="swebenchify", help="Dataset name")
    parser.add_argument("--output", default=None, help="Output directory")
    args = parser.parse_args()

    output_dir = args.output or os.path.join("data", "harbor", args.name)
    tasks_dir = os.path.join(output_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    with open(args.input) as f:
        instances = [json.loads(line.strip()) for line in f if line.strip()]

    print(f"Exporting {len(instances)} instances to {output_dir}", file=sys.stderr)

    task_names = []
    for inst in instances:
        task_name = generate_task_dir(inst, args.org, tasks_dir)
        task_names.append(task_name)

    generate_dataset_toml(args.org, args.name, task_names, output_dir)

    print(f"Done: {len(task_names)} tasks in {output_dir}", file=sys.stderr)
    print(f"  dataset.toml: {os.path.join(output_dir, 'dataset.toml')}")
    print(f"  tasks/: {len(task_names)} task directories")


if __name__ == "__main__":
    main()
