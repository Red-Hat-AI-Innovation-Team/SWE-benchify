"""Optional Docker sandboxing for agent sessions.

Provides utilities to run agent sessions inside Docker containers for
isolation. Configure via ``agent.sandbox: docker`` in swebenchify.yaml.
The default is ``local`` (no container, current behaviour).

NOTE: Full integration with the Claude Code SDK requires either running
the entire SWE-benchify process inside Docker, or having the claude CLI
installed inside the Docker image. This module provides the configuration
and utility scaffolding; actual subprocess wrapping is a future step.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """Configuration for Docker-based sandboxing.

    Attributes:
        enabled: Whether Docker sandboxing is active.
        docker_image: The Docker image to use for sandboxed sessions.
    """

    enabled: bool = False
    docker_image: str = "python:3.11-slim"


def prepare_docker_image(config: SandboxConfig, workspace_path: Path) -> str | None:
    """Ensure the Docker image is available locally.

    Pulls the image if it is not already present. Returns the image name
    on success, or ``None`` if sandboxing is disabled or Docker is not
    available.

    Args:
        config: Sandbox configuration.
        workspace_path: Path to the workspace directory (unused currently,
            reserved for future image customisation).

    Returns:
        The Docker image name, or ``None`` on failure or when disabled.
    """
    if not config.enabled:
        return None

    try:
        # Check if image exists locally
        result = subprocess.run(
            ["docker", "image", "inspect", config.docker_image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.info("Pulling Docker image: %s", config.docker_image)
            subprocess.run(
                ["docker", "pull", config.docker_image],
                check=True,
                capture_output=True,
                text=True,
            )
        return config.docker_image
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("Docker not available or image pull failed: %s", e)
        return None


def get_docker_run_prefix(
    config: SandboxConfig,
    workspace_path: Path,
    env_vars: dict[str, str] | None = None,
) -> list[str]:
    """Build the ``docker run`` command prefix for sandboxed execution.

    When sandboxing is disabled, returns an empty list so callers can
    unconditionally prepend the result to their command without branching.

    Args:
        config: Sandbox configuration.
        workspace_path: Host path to mount as ``/workspace`` inside the
            container.
        env_vars: Additional environment variables to pass through.
            Keys present in ``os.environ`` are forwarded; values in the
            dict serve as defaults when the env var is unset.

    Returns:
        A command prefix list (e.g.
        ``["docker", "run", "--rm", "-v", "...", "image"]``), or an
        empty list when sandboxing is disabled.
    """
    if not config.enabled:
        return []

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace_path.resolve()}:/workspace",
        "-w",
        "/workspace",
        "--network",
        "host",
    ]

    # Pass through necessary env vars
    default_env: dict[str, str] = {"ANTHROPIC_API_KEY": ""}
    if env_vars:
        default_env.update(env_vars)

    for key, default in default_env.items():
        val = os.environ.get(key, default)
        if val:
            cmd.extend(["-e", f"{key}={val}"])

    cmd.append(config.docker_image)
    return cmd


def is_docker_available() -> bool:
    """Check whether Docker is available on the system.

    Returns ``True`` if ``docker info`` exits successfully within 10
    seconds, ``False`` otherwise.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
