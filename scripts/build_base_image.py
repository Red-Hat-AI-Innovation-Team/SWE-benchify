#!/usr/bin/env python
"""Build SWE-bench-compatible base image without miniconda.

Workaround for environments where repo.anaconda.com is blocked.
Uses python:3.x-slim images instead of ubuntu + miniconda.

Usage:
    # Build base images for all needed Python versions
    python scripts/build_base_image.py

    # Build for a specific version
    python scripts/build_base_image.py --python-version 3.11
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

DOCKERFILE_TEMPLATE = """\
FROM python:{python_version}-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y \\
    wget git build-essential libffi-dev libtiff-dev \\
    jq curl locales locales-all tzdata \\
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

WORKDIR /testbed
"""


def build_base_image(python_version: str, docker_host: str | None = None) -> str:
    """Build a base image for the given Python version.

    Returns the image tag.
    """
    tag = f"sweb.base.py.x86_64:latest"

    with tempfile.TemporaryDirectory() as tmpdir:
        dockerfile = Path(tmpdir) / "Dockerfile"
        dockerfile.write_text(
            DOCKERFILE_TEMPLATE.format(python_version=python_version)
        )

        cmd = ["podman", "build", "-t", tag, "-f", str(dockerfile), tmpdir]
        env = os.environ.copy()
        if docker_host:
            env["DOCKER_HOST"] = docker_host

        print(f"Building {tag} with Python {python_version}...")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            print(f"Build failed:\n{result.stderr}")
            raise RuntimeError(f"Failed to build base image: {result.stderr[-200:]}")

        print(f"Built {tag} successfully")
        return tag


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SWE-bench base image without miniconda")
    parser.add_argument("--python-version", default="3.11",
                        help="Python version (default: 3.11)")
    parser.add_argument("--docker-host", default=os.environ.get("DOCKER_HOST", "unix:///tmp/podman.sock"))
    args = parser.parse_args()

    build_base_image(args.python_version, args.docker_host)


if __name__ == "__main__":
    main()
