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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swebenchify.models import GoEnvironmentSpec

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


class GoDockerfile:
    """Generates minimal Dockerfiles for Go validation images."""

    @staticmethod
    def generate(spec: "GoEnvironmentSpec") -> str:
        """Return a Dockerfile string for the given Go environment spec.

        The image is based on the official ``golang:{go_version}`` image.
        For vendored repos the vendor directory is expected to be present in
        the build context (the repo root).

        Args:
            spec: The discovered ``GoEnvironmentSpec``.

        Returns:
            A multi-line Dockerfile string.
        """
        go_version = spec.go_version or "1.21"
        source_url = "https://github.com/Red-Hat-AI-Innovation-Team/SWE-benchify"
        lines = [
            f"FROM golang:{go_version}",
            f"LABEL org.opencontainers.image.source={source_url}",
            "WORKDIR /repo",
        ]

        if spec.system_dependencies:
            pkgs = " ".join(spec.system_dependencies)
            lines += [
                "RUN apt-get update -qq && \\",
                f"    apt-get install -y --no-install-recommends {pkgs} && \\",
                "    rm -rf /var/lib/apt/lists/*",
            ]

        if spec.module_mode == "vendored":
            lines.append("# vendor directory is mounted at runtime; no COPY needed here")

        if spec.goflags:
            lines.append(f'ENV GOFLAGS="{spec.goflags}"')

        lines.append('CMD ["go", "test", "./..."]')
        return "\n".join(lines) + "\n"


class GoImageCache:
    """Per-``(repo, era, env_spec_hash)`` Docker image build and cache.

    Images are named ``swebenchify-go-{slug}-{hash_prefix}`` where
    ``slug`` is the repo's ``owner__repo`` form and ``hash_prefix`` is
    the first 12 characters of ``env_spec_hash``.

    The cache is checked via ``docker image inspect``.  A full rebuild
    can be forced with ``force_rebuild=True``.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self._cache_dir = Path(workspace_root) / "go-images"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def image_name(self, repo: str, era_commit: str, env_spec_hash: str) -> str:
        """Return a stable, unique image name for the given inputs."""
        slug = repo.replace("/", "__").lower()
        return f"swebenchify-go-{slug}-{env_spec_hash[:12]}"

    def is_cached(self, image_name: str) -> bool:
        """Return True if the image exists in the local Docker daemon."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def build(
        self,
        repo_path: str | Path,
        spec: "GoEnvironmentSpec",
        image_name: str,
    ) -> bool:
        """Build a Docker image for the given spec.

        Writes a ``Dockerfile.swebenchify`` to a temporary directory and
        runs ``docker build`` against it.

        Args:
            repo_path: Path to the repo checkout (used as build context for
                vendored repos).
            spec: The ``GoEnvironmentSpec`` to bake into the image.
            image_name: The tag to apply to the built image.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        dockerfile_content = GoDockerfile.generate(spec)

        # Empty temp dir as build context; Dockerfile piped via stdin.
        # Avoids sending the (potentially multi-GB) repo to the daemon.
        import tempfile
        with tempfile.TemporaryDirectory() as empty_ctx:
            cmd = ["docker", "build", "-f", "-", "-t", image_name, empty_ctx]
            try:
                result = subprocess.run(
                    cmd,
                    input=dockerfile_content,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    logger.info("Built Go image: %s", image_name)
                    return True
                logger.error(
                    "docker build failed for %s:\n%s", image_name, result.stderr
                )
                return False
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                logger.error("docker build error for %s: %s", image_name, exc)
                return False

    def get_or_build(
        self,
        repo: str,
        era_commit: str,
        spec: "GoEnvironmentSpec",
        repo_path: str | Path,
        force_rebuild: bool = False,
    ) -> str | None:
        """Return the image name, building it if not already cached.

        Args:
            repo: Repository full name (e.g. ``"kubernetes/kubectl"``).
            era_commit: The era base commit (used only for name derivation).
            spec: The ``GoEnvironmentSpec``.
            repo_path: Path to the repo checkout.
            force_rebuild: If ``True``, rebuild even if the image exists.

        Returns:
            The image name string on success, or ``None`` on build failure.
        """
        from swebenchify.models import compute_env_spec_hash
        spec_hash = compute_env_spec_hash(spec) if not spec.env_spec_hash else spec.env_spec_hash
        name = self.image_name(repo, era_commit, spec_hash)

        if not force_rebuild and self.is_cached(name):
            logger.debug("Go image cache hit: %s", name)
            return name

        if self.build(repo_path, spec, name):
            return name
        return None

    @staticmethod
    def harbor_image_name(
        registry_url: str,
        language: str,
        repo: str,
        env_spec_hash: str,
    ) -> str:
        """Return a Harbor-compatible registry image name.

        Follows the convention:
        ``{registry_url}/swebenchify-{lang}-{repo_slug}-{hash[:12]}``
        """
        slug = repo.replace("/", "__").lower()
        return f"{registry_url}/swebenchify-{language}-{slug}-{env_spec_hash[:12]}"

    def push_to_registry(
        self,
        local_name: str,
        registry: str,
        remote_name: str | None = None,
    ) -> str:
        """Tag and push a local image to a remote registry.

        Args:
            local_name: The local Docker image tag.
            registry: The registry URL (used when ``remote_name`` is not
                provided).
            remote_name: Explicit remote tag. When supplied, ``registry``
                is ignored and ``remote_name`` is used directly.

        Returns the registry-qualified image name on success.
        Raises ``RuntimeError`` on failure.
        """
        target = remote_name or f"{registry}/{local_name}"
        try:
            tag = subprocess.run(
                ["docker", "tag", local_name, target],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if tag.returncode != 0:
                raise RuntimeError(f"docker tag failed: {tag.stderr}")
            push = subprocess.run(
                ["docker", "push", target],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if push.returncode != 0:
                raise RuntimeError(f"docker push failed: {push.stderr}")
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"docker push timed out: {exc}") from exc
        logger.info("Pushed image: %s", target)
        return target


class RustImageCache:
    """Per-``(repo, era, env_spec_hash)`` Docker image build and cache for Rust.

    Images are named ``swebenchify-rust-{slug}-{hash_prefix}`` where
    ``slug`` is the repo's ``owner__repo`` form and ``hash_prefix`` is
    the first 12 characters of ``env_spec_hash``.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self._cache_dir = Path(workspace_root) / 'rust-images'
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def image_name(self, repo: str, era_commit: str, env_spec_hash: str) -> str:
        slug = repo.replace('/', '__').lower()
        return f'swebenchify-rust-{slug}-{env_spec_hash[:12]}'


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
