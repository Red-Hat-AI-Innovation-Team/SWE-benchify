#!/usr/bin/env python3
"""Build and push Python Docker images to a container registry.

Reads an instances JSONL, finds Python instances that need Docker images,
looks up their EnvironmentSpec from the specs directory, builds the
images (one per unique repo+base_commit+spec), and pushes to a registry.

Usage — local build + push::

    python scripts/build_and_push_python_images.py \
        --instances output/ansible/ansible__ansible-task-instances.jsonl \
        --registry ghcr.io/Red-Hat-AI-Innovation-Team \
        --specs-dir data/python-specs \
        --update-jsonl

Usage — dry-run::

    python scripts/build_and_push_python_images.py \
        --instances output/ansible/ansible__ansible-task-instances.jsonl \
        --specs-dir data/python-specs \
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from swebenchify.models import EnvironmentSpec, compute_python_env_spec_hash


def _load_specs(specs_dir: Path) -> dict[str, EnvironmentSpec]:
    """Load all spec JSON files from a directory, indexed by computed hash."""
    index: dict[str, EnvironmentSpec] = {}
    for p in specs_dir.glob("*.json"):
        raw = json.loads(p.read_text())
        spec = EnvironmentSpec(
            language=raw.get("language", "python"),
            language_version=raw.get("language_version", "3.11"),
            package_manager=raw.get("package_manager", "pip"),
            install_cmd=raw.get("install_cmd", ""),
            test_cmd=raw.get("test_cmd", "pytest"),
            pre_install=raw.get("pre_install", []),
            pip_packages=raw.get("pip_packages", []),
            system_dependencies=raw.get("system_dependencies", []),
        )
        h = compute_python_env_spec_hash(spec)
        expected = p.stem
        if h != expected:
            print(
                f"WARNING: spec file {p.name} has hash {h[:12]}, "
                f"expected {expected[:12]} — skipping",
                file=sys.stderr,
            )
            continue
        index[h] = spec
    return index


def _image_name(repo: str, base_commit: str) -> str:
    slug = repo.replace("/", "__").lower()
    return f"swebenchify-python-{slug}-{base_commit[:12]}"


def _make_dockerfile(
    spec: EnvironmentSpec, repo: str, base_commit: str,
) -> str:
    """Generate a Dockerfile for a Python instance (no patches)."""
    version = spec.language_version or "3.11"
    source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
    lines = [
        f"FROM python:{version}-slim",
        f"LABEL org.opencontainers.image.source={source_url}",
        "RUN apt-get update -qq && "
        "apt-get install -y --no-install-recommends git",
    ]
    if spec.system_dependencies:
        pkgs = " ".join(spec.system_dependencies)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs}"
        )
    lines.append("RUN rm -rf /var/lib/apt/lists/*")
    lines.append(
        f"RUN git clone https://github.com/{repo}.git /repo && "
        f"cd /repo && git checkout {base_commit}"
    )
    for cmd in spec.pre_install:
        lines.append(f"RUN cd /repo && {cmd}")
    if spec.install_cmd:
        lines.append(f"RUN cd /repo && {spec.install_cmd}")
    if spec.pip_packages:
        pkg_str = " ".join(f"'{p}'" for p in spec.pip_packages)
        lines.append(f"RUN pip install --no-deps {pkg_str}")
    return "\n".join(lines) + "\n"


def _build_image(
    spec: EnvironmentSpec, repo: str, base_commit: str, image_name: str,
) -> bool:
    dockerfile = _make_dockerfile(spec, repo, base_commit)
    import tempfile

    with tempfile.TemporaryDirectory() as ctx:
        result = subprocess.run(
            ["docker", "build", "-f", "-", "-t", image_name, ctx],
            input=dockerfile,
            capture_output=True,
            text=True,
            timeout=600,
        )
    if result.returncode != 0:
        print(f"FAIL: docker build {image_name}:\n{result.stderr[-500:]}", file=sys.stderr)
        return False
    return True


def _make_package_public(registry: str, package_name: str) -> bool:
    """Set a GHCR package's visibility to public via the GitHub API."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("  WARNING: GITHUB_TOKEN not set, cannot set package visibility",
              file=sys.stderr)
        return False
    parts = registry.rstrip("/").split("/")
    if len(parts) < 2 or parts[0] != "ghcr.io":
        print(f"  WARNING: cannot parse org from registry {registry!r}, "
              "skipping visibility update", file=sys.stderr)
        return False
    org = parts[1]
    url = (f"https://api.github.com/orgs/{org}/packages"
           f"/container/{urllib.parse.quote(package_name, safe='')}")
    data = json.dumps({"visibility": "public"}).encode()
    req = urllib.request.Request(url, data=data, method="PATCH", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    })
    try:
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"  WARNING: failed to set visibility for {package_name}: "
              f"{exc.code} {body}", file=sys.stderr)
        return False


def _push_image(local_name: str, remote_name: str) -> bool:
    tag = subprocess.run(
        ["docker", "tag", local_name, remote_name],
        capture_output=True, text=True,
    )
    if tag.returncode != 0:
        print(f"FAIL: docker tag {remote_name}:\n{tag.stderr}", file=sys.stderr)
        return False
    push = subprocess.run(
        ["docker", "push", remote_name],
        capture_output=True, text=True, timeout=600,
    )
    if push.returncode != 0:
        print(f"FAIL: docker push {remote_name}:\n{push.stderr}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and push Python Docker images for SWE-bench instances.",
    )
    parser.add_argument(
        "--instances", type=Path, required=True, help="Path to instances JSONL"
    )
    parser.add_argument(
        "--specs-dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "python-specs",
        help="Directory containing {env_spec_hash}.json spec files",
    )
    parser.add_argument(
        "--registry", default="ghcr.io/red-hat-ai-innovation-team",
        help="Container registry prefix",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover and verify specs without building or pushing")
    parser.add_argument("--update-jsonl", action="store_true",
                        help="Update the instances JSONL with image_name after push")
    args = parser.parse_args(argv)

    if not args.specs_dir.is_dir():
        print(f"error: specs directory not found: {args.specs_dir}", file=sys.stderr)
        return 2
    specs = _load_specs(args.specs_dir)
    print(f"Loaded {len(specs)} spec(s) from {args.specs_dir}")

    lines = args.instances.read_text().splitlines()
    instances = [json.loads(line) for line in lines if line.strip()]

    # Find Python instances missing image_name, grouped by (repo, base_commit, hash)
    needed: dict[tuple[str, str, str], list[dict]] = {}
    for inst in instances:
        if inst.get("repo_language") != "python":
            continue
        if inst.get("image_name"):
            continue
        h = inst.get("env_spec_hash", "")
        if not h:
            continue
        key = (inst["repo"], inst["base_commit"], h)
        needed.setdefault(key, []).append(inst)

    if not needed:
        print("No Python instances need images — nothing to do.")
        return 0

    print(f"Found {sum(len(v) for v in needed.values())} instance(s) across "
          f"{len(needed)} unique image(s) to build")

    missing_specs = [k for k in needed if k[2] not in specs]
    if missing_specs:
        for repo, commit, h in missing_specs:
            print(f"WARNING: no spec for hash {h[:12]} (repo={repo}) — skipping",
                  file=sys.stderr)
        for k in missing_specs:
            del needed[k]

    if not needed:
        print("No buildable Python instances remain after skipping missing specs.")
        return 0

    built: dict[tuple[str, str, str], str] = {}
    for (repo, commit, h), insts in needed.items():
        spec = specs[h]
        local_name = _image_name(repo, commit)
        remote_name = f"{args.registry}/{local_name}"
        n = len(insts)
        print(f"\n{'='*60}")
        print(f"Image: {local_name}")
        print(f"  repo={repo}  python={spec.language_version}  commit={commit[:12]}")
        print(f"  covers {n} instance(s)")
        print(f"  remote: {remote_name}")

        if args.dry_run:
            print("  [dry-run] would build and push")
            built[(repo, commit, h)] = remote_name
            continue

        print("  Building…")
        if not _build_image(spec, repo, commit, local_name):
            return 1
        print("  Built OK. Pushing…")
        if not _push_image(local_name, remote_name):
            return 1
        print(f"  Pushed: {remote_name}")
        if _make_package_public(args.registry, local_name):
            print("  Visibility: public")
        built[(repo, commit, h)] = remote_name

    print(f"\n{'='*60}")
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Summary: {len(built)}/{len(needed)} image(s) "
          f"{'would be ' if args.dry_run else ''}built and pushed")

    if args.update_jsonl and not args.dry_run:
        updated = 0
        for inst in instances:
            key = (inst.get("repo", ""), inst.get("base_commit", ""),
                   inst.get("env_spec_hash", ""))
            if key in built and not inst.get("image_name"):
                inst["image_name"] = built[key]
                updated += 1
        with open(args.instances, "w") as f:
            for inst in instances:
                f.write(json.dumps(inst, separators=(",", ":")) + "\n")
        print(f"Updated {updated} instance(s) in {args.instances}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
