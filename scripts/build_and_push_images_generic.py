#!/usr/bin/env python3
"""Build and push Docker images for validated SWE-bench instances (any language).

Reads an instances JSONL and the accompanying env_spec.json (emitted by every
pipeline script), builds one Docker image per unique (repo, base_commit) pair,
pushes to a container registry, and optionally writes the image name back into
the JSONL.

Usage — from a pipeline output directory::

    python scripts/build_and_push_images_generic.py \
        --instances output/FasterXML__jackson-databind/FasterXML__jackson-databind-task-instances.jsonl \
        --registry ghcr.io/red-hat-ai-innovation-team \
        --update-jsonl

Usage — dry-run::

    python scripts/build_and_push_images_generic.py \
        --instances output/FasterXML__jackson-databind/FasterXML__jackson-databind-task-instances.jsonl \
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

SOURCE_URL = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"


def _git_clone_or_archive(repo: str, base_commit: str) -> str:
    return (
        f"RUN (git clone https://github.com/{repo}.git /repo && "
        f"cd /repo && (git checkout {base_commit} || "
        f"(git fetch origin {base_commit} && git checkout {base_commit}))) "
        f"|| (rm -rf /repo && mkdir -p /repo && cd /repo && git init && "
        f"curl -sL https://github.com/{repo}/archive/{base_commit}.tar.gz | "
        f"tar xz --strip-components=1 && git add -A && git commit -q -m base)"
    )


def _make_dockerfile(spec: dict, repo: str, base_commit: str) -> str:
    lang = spec.get("language", "")
    version = spec.get("language_version", "")
    sys_deps = spec.get("system_dependencies", [])
    pre_install = spec.get("pre_install", [])
    install_cmd = spec.get("install_cmd", "")
    pip_packages = spec.get("pip_packages", [])

    if lang == "java":
        base = f"maven:3-eclipse-temurin-{version or '17'}"
    elif lang == "python":
        base = spec.get("base_image") or f"python:{version or '3.11'}-slim"
    elif lang == "go":
        base = f"golang:{version}" if version else "golang:latest"
    else:
        base = "ubuntu:24.04"

    lines = [
        f"FROM {base}",
        f"LABEL org.opencontainers.image.source={SOURCE_URL}",
    ]

    if lang == "python" and not spec.get("base_image"):
        lines.append(
            "RUN apt-get update -qq && "
            "apt-get install -y --no-install-recommends git"
        )

    if sys_deps:
        pkgs = " ".join(sys_deps)
        lines.append(
            "RUN apt-get update -qq && "
            f"apt-get install -y --no-install-recommends {pkgs} && "
            "rm -rf /var/lib/apt/lists/*"
        )
    elif lang == "python" and not spec.get("base_image"):
        lines.append("RUN rm -rf /var/lib/apt/lists/*")

    lines.append(_git_clone_or_archive(repo, base_commit))

    if lang == "go" and spec.get("goflags"):
        lines.append(f'ENV GOFLAGS="{spec["goflags"]}"')

    for cmd in pre_install:
        lines.append(f"RUN cd /repo && {cmd}")

    if install_cmd:
        lines.append(f"RUN cd /repo && {install_cmd}")

    if pip_packages:
        pkg_str = " ".join(f"'{p}'" for p in pip_packages)
        lines.append(f"RUN pip install --no-deps {pkg_str}")

    return "\n".join(lines) + "\n"


def _image_name(lang: str, repo: str, base_commit: str) -> str:
    slug = repo.replace("/", "__").lower()
    return f"swebenchify-{lang}-{slug}-{base_commit[:12]}"


def _build_image(spec: dict, repo: str, base_commit: str, image_name: str) -> bool:
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
        description="Build and push Docker images for SWE-bench instances (any language).",
    )
    parser.add_argument(
        "--instances", type=Path, required=True,
        help="Path to task-instances JSONL",
    )
    parser.add_argument(
        "--env-spec", type=Path, default=None,
        help="Path to env_spec.json (default: same directory as instances)",
    )
    parser.add_argument(
        "--registry", default="ghcr.io/red-hat-ai-innovation-team",
        help="Container registry prefix",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Discover and verify without building or pushing",
    )
    parser.add_argument(
        "--update-jsonl", action="store_true",
        help="Update the instances JSONL with image_name after push",
    )
    args = parser.parse_args(argv)

    if not args.instances.exists():
        print(f"error: instances file not found: {args.instances}", file=sys.stderr)
        return 2

    spec_path = args.env_spec or (args.instances.parent / "env_spec.json")
    if not spec_path.exists():
        print(f"error: env_spec.json not found: {spec_path}", file=sys.stderr)
        return 2

    spec = json.loads(spec_path.read_text())
    lang = spec.get("language", "unknown")
    print(f"Loaded env spec: language={lang} version={spec.get('language_version', '?')}")

    lines = args.instances.read_text().splitlines()
    instances = [json.loads(line) for line in lines if line.strip()]

    if not instances:
        print("No instances found — nothing to do.")
        return 0

    # Group by (repo, base_commit) — one image per unique pair
    needed: dict[tuple[str, str], list[dict]] = {}
    for inst in instances:
        if inst.get("image_name"):
            continue
        key = (inst["repo"], inst["base_commit"])
        needed.setdefault(key, []).append(inst)

    if not needed:
        print("All instances already have image_name — nothing to do.")
        return 0

    total = sum(len(v) for v in needed.values())
    print(f"Found {total} instance(s) across {len(needed)} unique image(s) to build")

    built: dict[tuple[str, str], str] = {}
    for (repo, commit), insts in needed.items():
        local_name = _image_name(lang, repo, commit)
        remote_name = f"{args.registry}/{local_name}"
        n = len(insts)
        print(f"\n{'='*60}")
        print(f"Image: {local_name}")
        print(f"  repo={repo}  {lang}={spec.get('language_version', '?')}  commit={commit[:12]}")
        print(f"  covers {n} instance(s)")
        print(f"  remote: {remote_name}")

        if args.dry_run:
            print("  [dry-run] would build and push")
            built[(repo, commit)] = remote_name
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
        built[(repo, commit)] = remote_name

    print(f"\n{'='*60}")
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Summary: {len(built)}/{len(needed)} image(s) "
          f"{'would be ' if args.dry_run else ''}built and pushed")

    if args.update_jsonl and not args.dry_run:
        updated = 0
        for inst in instances:
            key = (inst.get("repo", ""), inst.get("base_commit", ""))
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
