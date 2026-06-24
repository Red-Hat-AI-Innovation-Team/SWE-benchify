"""Convert SWE-benchify JSONL dataset to Harbor task directories.

Usage:
    uv run python scripts/to_harbor.py \\
        --input output/rh-v1/all-task-instances.jsonl \\
        --output output/harbor-tasks \\
        [--limit N] [--instance-id ID] [--overwrite]
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import stat
import sys
from pathlib import Path
from textwrap import dedent


def load_instances(path: str) -> list[dict]:
    instances = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances


def load_go_spec(env_spec_hash: str, data_dir: Path) -> dict | None:
    spec_file = data_dir / f"{env_spec_hash}.json"
    if spec_file.exists():
        return json.loads(spec_file.read_text())
    return None


def go_version_from_version_string(version: str) -> str:
    """Extract Go version from SWE-benchify version string like '1.26-7295ef7d'."""
    return version.split("-")[0] if "-" in version else version


def estimate_difficulty(inst: dict) -> str:
    patch_lines = inst.get("patch_lines", 0)
    files_touched = inst.get("files_touched", 0)
    if files_touched > 3 or patch_lines > 200:
        return "hard"
    if files_touched > 1 or patch_lines > 50:
        return "medium"
    return "easy"


def affected_packages_go(test_patch: str) -> list[str]:
    """Extract Go package paths affected by the test patch."""
    pkgs = set()
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        pkg_dir = str(Path(path).parent)
        if pkg_dir == ".":
            pkgs.add("./...")
        else:
            pkgs.add(f"./{pkg_dir}/...")
    return sorted(pkgs) if pkgs else ["./..."]


def test_files_from_patch(test_patch: str) -> list[str]:
    """Extract test file paths from a unified diff."""
    files = []
    for line in test_patch.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m and m.group(1) != "/dev/null":
            files.append(m.group(1))
    return files


def decode_f2p(value) -> list[str]:
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── File generators ──────────────────────────────────────────────


def gen_task_toml(inst: dict) -> str:
    instance_id = inst["instance_id"]
    repo = inst["repo"]
    lang = inst.get("repo_language", "unknown")
    difficulty = estimate_difficulty(inst)
    product = inst.get("product") or ""

    keywords = ["swe-bench", "debugging", lang]
    if product:
        keywords.append(product.lower())
    keywords_str = ", ".join(f'"{k}"' for k in keywords)

    return dedent(f"""\
        schema_version = "1.0"

        [task]
        name = "swebenchify/{instance_id}"
        description = "Fix a bug in {repo} ({lang})"
        authors = [
            {{ name = "Red Hat AI Innovation Team" }},
        ]
        keywords = [{keywords_str}]

        [metadata]
        difficulty = "{difficulty}"
        category = "debugging"
        repo_language = "{lang}"
        repo = "{repo}"
        product = "{product}"

        [verifier]
        network_mode = "public"
        timeout_sec = 3000

        [agent]
        network_mode = "public"
        timeout_sec = 3000

        [environment]
        build_timeout_sec = 1800.0
    """)


def gen_instruction_md(inst: dict) -> str:
    problem = inst.get("problem_statement", "").strip()
    repo = inst["repo"]
    base_commit = inst["base_commit"]
    hints = (inst.get("hints_text") or "").strip()

    parts = [problem, ""]
    parts.append(f"**Repository:** `{repo}`")
    parts.append(f"**Base commit:** `{base_commit}`")
    if hints:
        parts.append("")
        parts.append("## Hints")
        parts.append("")
        parts.append(hints)

    return "\n".join(parts) + "\n"


def gen_dockerfile_go(inst: dict, go_spec: dict | None) -> str:
    repo = inst["repo"]
    base_commit = inst["base_commit"]

    if go_spec:
        go_ver = go_spec.get("go_version", "1.22")
    else:
        go_ver = go_version_from_version_string(inst.get("version", "1.22"))

    lines = [
        f"FROM golang:{go_ver}",
        "",
        "RUN apt-get update -qq && \\",
        "    apt-get install -y --no-install-recommends git patch && \\",
        "    rm -rf /var/lib/apt/lists/*",
    ]

    sys_deps = (go_spec or {}).get("system_dependencies", [])
    if sys_deps:
        pkgs = " ".join(sys_deps)
        lines += [
            "",
            f"RUN apt-get update -qq && \\",
            f"    apt-get install -y --no-install-recommends {pkgs} && \\",
            "    rm -rf /var/lib/apt/lists/*",
        ]

    goflags = (go_spec or {}).get("goflags", "")
    if goflags:
        lines.append(f'ENV GOFLAGS="{goflags}"')

    lines += [
        "",
        f"RUN git clone https://github.com/{repo}.git /testbed && \\",
        f"    cd /testbed && git checkout {base_commit}",
        "",
        "WORKDIR /testbed",
        "RUN mkdir -p /logs/verifier",
    ]
    return "\n".join(lines) + "\n"


def gen_dockerfile_python(inst: dict) -> str:
    repo = inst["repo"]
    base_commit = inst["base_commit"]

    return dedent(f"""\
        FROM python:3.11-slim

        RUN apt-get update -qq && \\
            apt-get install -y --no-install-recommends git patch build-essential && \\
            rm -rf /var/lib/apt/lists/*

        RUN pip install --no-cache-dir pytest

        RUN git clone https://github.com/{repo}.git /testbed && \\
            cd /testbed && git checkout {base_commit}

        WORKDIR /testbed
        RUN mkdir -p /logs/verifier
    """)


def gen_test_sh_go(inst: dict, go_spec: dict | None) -> str:
    test_patch = inst.get("test_patch", "")
    f2p = decode_f2p(inst.get("FAIL_TO_PASS", "[]"))
    pkg_scope = " ".join(affected_packages_go(test_patch))

    f2p_json = json.dumps(f2p)

    return f"""#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo {shlex.quote(test_patch)} > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Run tests and capture output
go test -json -count=1 {pkg_scope} 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, sys

f2p = {f2p_json}
passed = set()
with open("/tmp/test_output.txt") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        test = event.get("Test")
        action = event.get("Action", "")
        if test and action == "pass":
            passed.add(test)
            # Also add the bare test name (no subtest suffix)
            passed.add(test.split("/")[0])

all_pass = all(
    t in passed or t.split("/")[0] in passed
    for t in f2p
)

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    missing = [t for t in f2p if t not in passed and t.split("/")[0] not in passed]
    print(f"NOT RESOLVED: {{len(missing)}}/{{len(f2p)}} tests still failing: {{missing}}")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${{exit_code}}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${{exit_code}}"
"""


def gen_test_sh_python(inst: dict) -> str:
    test_patch = inst.get("test_patch", "")
    f2p = decode_f2p(inst.get("FAIL_TO_PASS", "[]"))
    test_files = test_files_from_patch(test_patch)
    test_files_str = " ".join(shlex.quote(f) for f in test_files) if test_files else "."

    f2p_json = json.dumps(f2p)

    return f"""#!/bin/bash
set -uo pipefail

cd /testbed

# Apply the test patch (restores test expectations)
echo {shlex.quote(test_patch)} > /tmp/test_patch.diff
git apply /tmp/test_patch.diff 2>/dev/null || patch --fuzz=5 -p1 -i /tmp/test_patch.diff

# Try to install the project if setup exists
if [ -f setup.py ] || [ -f pyproject.toml ]; then
    pip install -e . 2>/dev/null || pip install . 2>/dev/null || true
fi

# Run tests
python -m pytest -xvs {test_files_str} 2>&1 | tee /tmp/test_output.txt || true

# Parse results: check if all FAIL_TO_PASS tests now pass
cat > /tmp/check_f2p.py << 'PYEOF'
import json, re, sys

f2p = {f2p_json}
passed = set()

with open("/tmp/test_output.txt") as f:
    for line in f:
        # pytest output: "PASSED" or "FAILED" after the test ID
        m = re.match(r"^(.+?)\\s+PASSED", line)
        if m:
            passed.add(m.group(1).strip())

# Also check for the short form "test_name PASSED"
# and pytest's "X passed" summary
all_pass = True
for t in f2p:
    # Check exact match or suffix match
    if t not in passed:
        # Try matching just the test function part
        found = any(t.endswith(p.split("::")[-1]) or p.endswith(t.split("::")[-1]) for p in passed)
        if not found:
            all_pass = False

if all_pass and f2p:
    print("RESOLVED: all FAIL_TO_PASS tests now pass")
    sys.exit(0)
else:
    print(f"NOT RESOLVED: some FAIL_TO_PASS tests still failing")
    sys.exit(1)
PYEOF

python3 /tmp/check_f2p.py
exit_code=$?

# Write reward for Harbor
mkdir -p /logs/verifier
if [ "${{exit_code}}" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi

exit "${{exit_code}}"
"""


def gen_solve_sh(inst: dict) -> str:
    patch = (inst.get("patch") or "").strip()
    return f"""#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
{patch}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
"""


# ── Main converter ───────────────────────────────────────────────


def generate_task(inst: dict, output_dir: Path, data_dir: Path, overwrite: bool = False) -> Path:
    instance_id = inst["instance_id"]
    task_dir = output_dir / instance_id

    if task_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Already exists: {task_dir}")
        shutil.rmtree(task_dir)

    env_dir = task_dir / "environment"
    tests_dir = task_dir / "tests"
    solution_dir = task_dir / "solution"

    env_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    solution_dir.mkdir(parents=True)

    lang = inst.get("repo_language", "python")
    go_spec = None
    if lang == "go":
        env_hash = inst.get("env_spec_hash")
        if env_hash:
            go_spec = load_go_spec(env_hash, data_dir)

    # task.toml
    (task_dir / "task.toml").write_text(gen_task_toml(inst))

    # instruction.md
    (task_dir / "instruction.md").write_text(gen_instruction_md(inst))

    # environment/Dockerfile
    if lang == "go":
        (env_dir / "Dockerfile").write_text(gen_dockerfile_go(inst, go_spec))
    else:
        (env_dir / "Dockerfile").write_text(gen_dockerfile_python(inst))

    # tests/test.sh
    if lang == "go":
        test_sh = gen_test_sh_go(inst, go_spec)
    else:
        test_sh = gen_test_sh_python(inst)
    test_sh_path = tests_dir / "test.sh"
    test_sh_path.write_text(test_sh)
    test_sh_path.chmod(test_sh_path.stat().st_mode | stat.S_IEXEC)

    # tests/config.json
    (tests_dir / "config.json").write_text(json.dumps(inst, indent=2))

    # solution/solve.sh
    solve_sh_path = solution_dir / "solve.sh"
    solve_sh_path.write_text(gen_solve_sh(inst))
    solve_sh_path.chmod(solve_sh_path.stat().st_mode | stat.S_IEXEC)

    return task_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert SWE-benchify JSONL to Harbor task directories"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input JSONL file (e.g. output/rh-v1/all-task-instances.jsonl)",
    )
    parser.add_argument(
        "--output", "-o",
        default="output/harbor-tasks",
        help="Output directory for Harbor tasks (default: output/harbor-tasks)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory containing go-specs/ (default: data/ relative to repo root)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max tasks to generate")
    parser.add_argument("--instance-id", type=str, default=None, help="Generate a single task")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing task dirs")
    args = parser.parse_args()

    # Resolve data directory
    if args.data_dir:
        data_dir = Path(args.data_dir) / "go-specs"
    else:
        repo_root = Path(__file__).resolve().parent.parent
        data_dir = repo_root / "data" / "go-specs"

    instances = load_instances(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.instance_id:
        instances = [i for i in instances if i["instance_id"] == args.instance_id]
        if not instances:
            print(f"Instance not found: {args.instance_id}", file=sys.stderr)
            sys.exit(1)

    if args.limit:
        instances = instances[:args.limit]

    print(f"Converting {len(instances)} instances to Harbor tasks in {output_dir} ...")

    ok = 0
    failed = 0
    for idx, inst in enumerate(instances, 1):
        iid = inst["instance_id"]
        try:
            task_dir = generate_task(inst, output_dir, data_dir, overwrite=args.overwrite)
            print(f"[{idx}/{len(instances)}] OK   {iid}")
            ok += 1
        except Exception as e:
            print(f"[{idx}/{len(instances)}] FAIL {iid}: {e}")
            failed += 1

    print(f"\nDone. Success: {ok}  Failures: {failed}")


if __name__ == "__main__":
    main()
