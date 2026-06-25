#!/usr/bin/env python3
"""Build and push Go Docker images to a container registry.

Reads an instances JSONL, finds Go instances that need Docker images,
looks up their GoEnvironmentSpec from the specs directory, builds the
images, and pushes to a registry (typically GHCR).

Usage — local build + push::

    python scripts/build_and_push_images.py \
        --instances /path/to/instances.jsonl \
        --registry ghcr.io/Red-Hat-AI-Innovation-Team \
        --specs-dir data/go-specs

Usage — dry-run (discover and verify, no build)::

    python scripts/build_and_push_images.py \
        --instances /path/to/instances.jsonl \
        --specs-dir data/go-specs \
        --dry-run

Usage — update instances JSONL after push::

    python scripts/build_and_push_images.py \
        --instances /path/to/instances.jsonl \
        --registry ghcr.io/Red-Hat-AI-Innovation-Team \
        --specs-dir data/go-specs \
        --update-jsonl
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

from swebenchify.models import GoEnvironmentSpec, compute_env_spec_hash
from swebenchify.sandbox import GoDockerfile


def _load_specs(specs_dir: Path) -> dict[str, GoEnvironmentSpec]:
    """Load all spec JSON files from a directory, indexed by computed hash."""
    index: dict[str, GoEnvironmentSpec] = {}
    for p in specs_dir.glob("*.json"):
        raw = json.loads(p.read_text())
        spec = GoEnvironmentSpec(
            go_version=raw.get("go_version", ""),
            build_cmd=raw.get("build_cmd", ""),
            test_cmd=raw.get("test_cmd", ""),
            module_mode=raw.get("module_mode", "modules"),
            goflags=raw.get("goflags", ""),
            system_dependencies=raw.get("system_dependencies", []),
        )
        h = compute_env_spec_hash(spec)
        expected = p.stem
        if h != expected:
            print(
                f"WARNING: spec file {p.name} has hash {h[:12]}, "
                f"expected {expected[:12]} — skipping",
                file=sys.stderr,
            )
            continue
        spec.env_spec_hash = h
        index[h] = spec
    return index


def _image_name(repo: str, env_spec_hash: str) -> str:
    slug = repo.replace("/", "__").lower()
    return f"swebenchify-go-{slug}-{env_spec_hash[:12]}"


def _build_image(spec: GoEnvironmentSpec, image_name: str) -> bool:
    dockerfile = GoDockerfile.generate(spec)
    import tempfile

    with tempfile.TemporaryDirectory() as ctx:
        result = subprocess.run(
            ["docker", "build", "-f", "-", "-t", image_name, ctx],
            input=dockerfile,
            capture_output=True,
            text=True,
            timeout=300,
        )
    if result.returncode != 0:
        print(f"FAIL: docker build {image_name}:\n{result.stderr}", file=sys.stderr)
        return False
    return True


def _make_package_public(registry: str, package_name: str) -> bool:
    """Set a GHCR package's visibility to public via the GitHub API."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("  WARNING: GITHUB_TOKEN not set, cannot set package visibility",
              file=sys.stderr)
        return False

    # Extract org from registry prefix like "ghcr.io/red-hat-ai-innovation-team"
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
        capture_output=True,
        text=True,
    )
    if tag.returncode != 0:
        print(f"FAIL: docker tag {remote_name}:\n{tag.stderr}", file=sys.stderr)
        return False
    push = subprocess.run(
        ["docker", "push", remote_name],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if push.returncode != 0:
        print(f"FAIL: docker push {remote_name}:\n{push.stderr}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and push Go Docker images for SWE-bench instances.",
    )
    parser.add_argument(
        "--instances", type=Path, required=True, help="Path to instances JSONL"
    )
    parser.add_argument(
        "--specs-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "go-specs",
        help="Directory containing {env_spec_hash}.json spec files",
    )
    parser.add_argument(
        "--registry",
        default="ghcr.io/red-hat-ai-innovation-team",
        help="Container registry prefix (default: ghcr.io/red-hat-ai-innovation-team)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and verify specs without building or pushing",
    )
    parser.add_argument(
        "--update-jsonl",
        action="store_true",
        help="Update the instances JSONL with image_name after successful push",
    )
    args = parser.parse_args(argv)

    # Load specs index
    if not args.specs_dir.is_dir():
        print(f"error: specs directory not found: {args.specs_dir}", file=sys.stderr)
        return 2
    specs = _load_specs(args.specs_dir)
    print(f"Loaded {len(specs)} spec(s) from {args.specs_dir}")

    # Parse instances JSONL
    lines = args.instances.read_text().splitlines()
    instances = [json.loads(line) for line in lines if line.strip()]

    # Find Go instances missing image_name, grouped by env_spec_hash
    needed: dict[str, list[dict]] = {}
    for inst in instances:
        if inst.get("repo_language") != "go":
            continue
        if inst.get("image_name"):
            continue
        h = inst.get("env_spec_hash", "")
        if not h:
            continue
        needed.setdefault(h, []).append(inst)

    if not needed:
        print("No Go instances need images — nothing to do.")
        return 0

    print(f"Found {sum(len(v) for v in needed.values())} instance(s) across "
          f"{len(needed)} unique image(s) to build")

    # Check spec availability
    missing_specs = [h for h in needed if h not in specs]
    if missing_specs:
        for h in missing_specs:
            sample = needed[h][0]
            print(
                f"ERROR: no spec for hash {h[:12]} "
                f"(repo={sample['repo']}, {len(needed[h])} instances)",
                file=sys.stderr,
            )
        return 1

    # Build and push
    built: dict[str, str] = {}  # env_spec_hash -> remote image name
    for h, insts in needed.items():
        spec = specs[h]
        repo = insts[0]["repo"]
        local_name = _image_name(repo, h)
        remote_name = f"{args.registry}/{local_name}"
        n = len(insts)
        print(f"\n{'='*60}")
        print(f"Image: {local_name}")
        print(f"  repo={repo}  go={spec.go_version}  mode={spec.module_mode}")
        print(f"  covers {n} instance(s)")
        print(f"  remote: {remote_name}")

        if args.dry_run:
            print("  [dry-run] would build and push")
            built[h] = remote_name
            continue

        print("  Building…")
        if not _build_image(spec, local_name):
            return 1
        print("  Built OK. Pushing…")
        if not _push_image(local_name, remote_name):
            return 1
        print(f"  Pushed: {remote_name}")
        if _make_package_public(args.registry, local_name):
            print("  Visibility: public")
        built[h] = remote_name

    # Summary
    print(f"\n{'='*60}")
    print(f"{'[dry-run] ' if args.dry_run else ''}Summary: "
          f"{len(built)}/{len(needed)} image(s) {'would be ' if args.dry_run else ''}built and pushed")

    # Update JSONL
    if args.update_jsonl and not args.dry_run:
        updated = 0
        for inst in instances:
            h = inst.get("env_spec_hash", "")
            if h in built and not inst.get("image_name"):
                inst["image_name"] = built[h]
                updated += 1
        with open(args.instances, "w") as f:
            for inst in instances:
                f.write(json.dumps(inst, separators=(",", ":")) + "\n")
        print(f"Updated {updated} instance(s) in {args.instances}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
