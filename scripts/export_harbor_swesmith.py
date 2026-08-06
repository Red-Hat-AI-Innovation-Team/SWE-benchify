"""Export SWE-Smith instances as a Harbor dataset.

Converts SWE-Smith JSONL instances into Harbor task directories matching
the same template conventions as SWE-benchify's harbor_emitter.py.
Key difference: SWE-Smith images already have the bug baked in, so the
Dockerfile just uses the image directly (no repo clone or patch reverse-apply).

Usage:
    python3 scripts/export_harbor_swesmith.py --input data/swesmith-sample-50-ghcr.jsonl --name swesmith-50
    python3 scripts/export_harbor_swesmith.py --input data/swesmith-sample-200.jsonl --name swesmith-200 --limit 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "swebenchify" / "harbor_templates"


def slugify(text: str, max_len: int = 60) -> str:
    return re.sub(r"[^a-z0-9-]", "-", text.lower().replace("_", "-").replace("__", "-"))[:max_len].rstrip("-")


def detect_language(inst: dict) -> str:
    """Detect whether an instance is Python or Go from its F2P test names."""
    f2p = inst.get("FAIL_TO_PASS", "[]")
    if isinstance(f2p, str):
        f2p = json.loads(f2p)
    if not f2p:
        return "python"
    if any("::" in t for t in f2p):
        return "python"
    if any(re.match(r"^Test[A-Z]", t) for t in f2p):
        return "go"
    return "python"


def build_test_command_python(f2p: list[str]) -> str:
    if len(f2p) <= 10:
        test_names = " or ".join(t.split("::")[-1] for t in f2p)
        return f'python -m pytest -xvs -k "{test_names}"'
    return "python -m pytest -x --tb=short -v"


def build_test_command_go(f2p: list[str], patch: str) -> str:
    pkg_dirs = set()
    for line in patch.splitlines():
        m = re.match(r"diff --git a/(.+?) b/", line)
        if m:
            d = os.path.dirname(m.group(1))
            pkg_dirs.add(d or ".")
    pkg_dir = next(iter(pkg_dirs), ".")

    run_filter = "|".join(re.escape(t) for t in f2p)
    return f'CGO_ENABLED=0 go test -v -count=1 -timeout 300s -run {shlex.quote(run_filter)} ./{pkg_dir}'


def generate_task_dir(inst: dict, org: str, output_dir: str) -> str:
    """Generate a Harbor task directory for one SWE-Smith instance."""
    iid = inst["instance_id"]
    task_slug = slugify(iid)
    task_name = f"{org}/{task_slug}"
    task_dir = os.path.join(output_dir, task_slug)

    for sub in ["environment", "solution", "tests"]:
        os.makedirs(os.path.join(task_dir, sub), exist_ok=True)

    image = inst.get("image_name", "")
    patch = inst.get("patch", "")
    problem = inst.get("problem_statement", "")
    repo = inst.get("repo", "")
    f2p = inst.get("FAIL_TO_PASS", "[]")
    p2p = inst.get("PASS_TO_PASS", "[]")
    if isinstance(f2p, str):
        f2p = json.loads(f2p)
    if isinstance(p2p, str):
        p2p = json.loads(p2p)

    lang = detect_language(inst)

    # --- task.toml ---
    description = problem.strip().splitlines()[0][:120] if problem.strip() else "Fix issue"
    description = description.replace('"', '\\"')

    with open(os.path.join(task_dir, "task.toml"), "w") as f:
        f.write(f"""schema_version = "1.3"

[task]
name = "swesmith/{lang}__{task_slug}"
description = "{description}"
keywords = ["{lang}", "swe-bench", "swesmith"]

[metadata]
repo = "{repo}"
instance_id = "{iid}"
difficulty = "medium"
language = "{lang}"
source = "swesmith"

[verifier]
timeout_sec = 600.0

[agent]
timeout_sec = 3600.0
user = "root"

artifacts = ["/logs/artifacts/candidate_patch.diff", "/logs/artifacts/patch_stat.txt", "/logs/verifier/report.json"]

[environment]
docker_image = "{image}"
build_timeout_sec = 1200.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
""")

    # --- instruction.md ---
    first_line = description
    with open(os.path.join(task_dir, "instruction.md"), "w") as f:
        f.write(f"""# {first_line}

**Repository:** {repo}

## Problem Statement

{problem}

## Task

Fix the bug described above. The repository is checked out at `/testbed`.
Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
""")

    # --- environment/Dockerfile ---
    # SWE-Smith images already have the bug baked in + deps installed
    with open(os.path.join(task_dir, "environment", "Dockerfile"), "w") as f:
        f.write(f"""FROM {image}

# Ensure /logs structure exists for Harbor verifier
RUN mkdir -p /logs/verifier /logs/agent /logs/artifacts

WORKDIR /testbed
""")

    # --- tests/config.json ---
    config = {
        "instance_id": iid,
        "repo": repo,
        "FAIL_TO_PASS": f2p,
        "PASS_TO_PASS": p2p,
        "repo_language": lang,
    }
    with open(os.path.join(task_dir, "tests", "config.json"), "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    # --- tests/test.patch (empty — SWE-Smith tests are already in the image) ---
    with open(os.path.join(task_dir, "tests", "test.patch"), "w") as f:
        f.write("")

    # --- tests/test.sh ---
    if lang == "python":
        test_command = build_test_command_python(f2p)
    else:
        test_command = build_test_command_go(f2p, patch)

    template_name = f"test_{lang}.sh.template"
    template_path = TEMPLATES_DIR / template_name
    if template_path.exists():
        from string import Template
        content = Template(template_path.read_text()).safe_substitute(
            test_command=test_command,
        )
        # SWE-Smith has no test patch — skip the apply step (empty file fails git apply)
        content = content.replace(
            'git apply --3way /tests/test.patch 2>&1 || git apply /tests/test.patch 2>&1 || {\n'
            '    echo "TEST_PATCH_APPLY_FAILED"\n'
            '    echo 0 > /logs/verifier/reward.txt\n'
            '    exit 0\n'
            '}',
            '# No test patch for SWE-Smith (tests already in image)',
        )
        # For SWE-Smith Python tasks, inject conda activation before the test command
        if lang == "python":
            conda_block = """
# Activate conda env if present (SWE-Smith images use conda)
if [ -d /opt/miniconda3/envs/testbed ]; then
    source /opt/miniconda3/bin/activate testbed
fi
"""
            content = content.replace(
                "echo '>>>>> Start Test Output'",
                conda_block + "\necho '>>>>> Start Test Output'",
            )
    else:
        raise FileNotFoundError(f"Template not found: {template_path}")

    test_sh_path = os.path.join(task_dir, "tests", "test.sh")
    with open(test_sh_path, "w") as f:
        f.write(content)
    os.chmod(test_sh_path, 0o755)

    # --- solution/patch.diff ---
    with open(os.path.join(task_dir, "solution", "patch.diff"), "w") as f:
        f.write(patch)

    # --- solution/solve.sh ---
    solve_template = TEMPLATES_DIR / "solve.sh.template"
    if solve_template.exists():
        solve_content = solve_template.read_text()
    else:
        solve_content = """#!/bin/bash
set -euo pipefail
cd /testbed
git apply /solution/patch.diff
"""
    solve_path = os.path.join(task_dir, "solution", "solve.sh")
    with open(solve_path, "w") as f:
        f.write(solve_content)
    os.chmod(solve_path, 0o755)

    return task_name


def generate_dataset_toml(org: str, name: str, task_names: list[str], output_dir: str):
    with open(os.path.join(output_dir, "dataset.toml"), "w") as f:
        f.write(f"""[dataset]
name = "{org}/{name}"
source = "swesmith"
task_count = {len(task_names)}
description = "SWE-Smith benchmark instances for difficulty comparison"
keywords = ["swesmith", "synthetic-benchmark"]

[[dataset.authors]]
name = "SWE-Smith"
email = "swebenchify@redhat.com"

""")
        for task_name in task_names:
            content_hash = hashlib.sha256(task_name.encode()).hexdigest()
            f.write(f"""[[tasks]]
name = "{task_name}"
digest = "sha256:{content_hash}"

""")


def generate_registry(instances: list[dict], output_dir: str):
    registry = []
    for inst in instances:
        if not inst.get("image_name"):
            continue
        registry.append({
            "instance_id": inst["instance_id"],
            "task_dir": slugify(inst["instance_id"]),
            "repo": inst.get("repo", ""),
            "language": detect_language(inst),
        })
    with open(os.path.join(output_dir, "registry.json"), "w") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Export SWE-Smith instances as Harbor dataset")
    parser.add_argument("--input", required=True, help="SWE-Smith JSONL file")
    parser.add_argument("--org", default="red-hat-ai", help="Harbor org name")
    parser.add_argument("--name", default="swesmith", help="Dataset name")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--limit", type=int, default=0, help="Max instances to export")
    args = parser.parse_args()

    output_dir = args.output or os.path.join("data", "harbor-swesmith", args.name)
    tasks_dir = os.path.join(output_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    with open(args.input) as f:
        instances = [json.loads(line.strip()) for line in f if line.strip()]

    if args.limit:
        instances = instances[:args.limit]

    print(f"Exporting {len(instances)} SWE-Smith instances to {output_dir}", file=sys.stderr)

    lang_counts = {"python": 0, "go": 0}
    task_names = []
    for inst in instances:
        if not inst.get("image_name"):
            print(f"  Skipping {inst['instance_id']}: no image_name", file=sys.stderr)
            continue
        lang = detect_language(inst)
        lang_counts[lang] += 1
        task_name = generate_task_dir(inst, args.org, tasks_dir)
        task_names.append(task_name)

    generate_dataset_toml(args.org, args.name, task_names, output_dir)
    generate_registry(instances, output_dir)

    print(f"Done: {len(task_names)} tasks ({lang_counts['python']} Python, {lang_counts['go']} Go)", file=sys.stderr)
    print(f"  {os.path.join(output_dir, 'dataset.toml')}")
    print(f"  {os.path.join(output_dir, 'registry.json')}")
    print(f"  {tasks_dir}/ ({len(task_names)} task directories)")


if __name__ == "__main__":
    main()
