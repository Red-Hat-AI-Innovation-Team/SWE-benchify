"""Harbor task directory emitter for SWE-benchify.

Generates Harbor-compatible task directories from validated TaskInstance
objects, enabling cloud-scaled agent evaluation via Harbor's trial system.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import string
from pathlib import Path

from swebenchify.backends import get_backend
from swebenchify.models import (
    AnyEnvironmentSpec,
    EnvironmentSpec,
    GoEnvironmentSpec,
    RustEnvironmentSpec,
    TaskInstance,
)

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "harbor_templates"

_DEFAULT_VERIFIER_TIMEOUT: dict[str, float] = {
    "go": 300.0,
    "python": 600.0,
    "java": 900.0,
    "rust": 600.0,
}

_DEFAULT_AGENT_TIMEOUT: dict[str, float] = {
    "go": 1800.0,
    "python": 1800.0,
    "java": 1800.0,
    "rust": 1800.0,
}


def _load_template(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text()


def _detect_language(instance: TaskInstance) -> str:
    if instance.repo_language:
        return instance.repo_language
    raise ValueError(
        f"repo_language is required but not set for instance {instance.instance_id}"
    )


def _get_difficulty(instance: TaskInstance) -> str:
    return "medium"


def _first_line(text: str) -> str:
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "Fix issue"


def _build_go_test_command(test_patch: str) -> str:
    """Build go test command, handling multi-module repos.

    In multi-module repos (e.g., etcd), subdirectories have their own go.mod.
    Running `go test ./server/etcdserver/...` from the repo root fails because
    the root module doesn't contain that package. Instead we need:
    `cd server && go test -v -count=1 ./etcdserver/...`
    """
    seen: dict[str, list[str]] = {}
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        path_parts = Path(path).parts
        if len(path_parts) <= 1:
            top = "."
            pkg = "./..."
        else:
            top = path_parts[0]
            rel_pkg = str(Path(*path_parts[1:-1])) if len(path_parts) > 2 else "."
            pkg = f"./{rel_pkg}" if rel_pkg != "." else "./..."
        if top not in seen:
            seen[top] = []
        if pkg not in seen[top]:
            seen[top].append(pkg)

    if not seen:
        return "go test -v -count=1 ./..."

    cmds: list[str] = []
    for root, pkgs in seen.items():
        pkg_str = " ".join(pkgs)
        if root == ".":
            cmds.append(f"go test -v -count=1 {pkg_str}")
        else:
            cmds.append(f"(cd {shlex.quote(root)} && go test -v -count=1 {pkg_str})")

    return " ; ".join(cmds)


class HarborTaskGenerator:
    """Generates Harbor task directories from TaskInstance objects."""

    def __init__(
        self,
        instances: list[TaskInstance],
        env_specs: dict[str, AnyEnvironmentSpec] | None = None,
        registry_url: str | None = None,
    ) -> None:
        self.instances = instances
        self.env_specs = env_specs or {}
        self.registry_url = registry_url

    def generate_all(self, output_dir: Path) -> list[str]:
        generated: list[str] = []
        for instance in self.instances:
            try:
                self._generate_task(instance, output_dir)
                generated.append(instance.instance_id)
            except Exception:
                logger.exception("Failed to generate Harbor task for %s", instance.instance_id)
        return generated

    def _generate_task(self, instance: TaskInstance, output_dir: Path) -> None:
        if not re.match(r'^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$', instance.repo):
            raise ValueError(f"Invalid repo format: {instance.repo}")
        if not re.match(r'^[0-9a-f]{7,40}$', instance.base_commit):
            raise ValueError(f"Invalid base_commit format: {instance.base_commit}")

        task_dir = output_dir / instance.instance_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "environment").mkdir(exist_ok=True)
        (task_dir / "solution").mkdir(exist_ok=True)
        (task_dir / "tests").mkdir(exist_ok=True)

        language = _detect_language(instance)
        env_spec = self.env_specs.get(instance.instance_id)

        self._write_instruction(instance, task_dir)
        self._write_task_toml(instance, task_dir, language, env_spec)
        self._write_dockerfile(instance, task_dir, language, env_spec)
        self._write_solve_sh(instance, task_dir)
        self._write_test_sh(instance, task_dir, language, env_spec)
        self._write_config_json(instance, task_dir)
        self._write_test_patch(instance, task_dir)

    def _write_instruction(self, instance: TaskInstance, task_dir: Path) -> None:
        title = _first_line(instance.problem_statement)
        template = _load_template("instruction.md.template")
        content = string.Template(template).safe_substitute(
            title=title,
            repo=instance.repo,
            base_commit=instance.base_commit,
            problem_statement=instance.problem_statement,
        )
        (task_dir / "instruction.md").write_text(content)

    def _write_task_toml(
        self,
        instance: TaskInstance,
        task_dir: Path,
        language: str,
        env_spec: AnyEnvironmentSpec | None,
    ) -> None:
        if self.registry_url and instance.image_name:
            env_block = f'docker_image = "{instance.image_name}"'
        elif self.registry_url and instance.env_spec_hash:
            repo_slug = instance.repo.replace("/", "__")
            image = f"{self.registry_url}/swebenchify-{language}-{repo_slug}-{instance.env_spec_hash[:12]}"
            env_block = f'docker_image = "{image}"'
        else:
            env_block = '# Uses environment/Dockerfile'

        description = _first_line(instance.problem_statement)
        # Escape quotes for TOML string
        description = description.replace('"', '\\"')

        template = _load_template("task.toml.template")
        content = string.Template(template).safe_substitute(
            language=language,
            instance_id=instance.instance_id,
            description=description,
            repo=instance.repo,
            base_commit=instance.base_commit,
            difficulty=_get_difficulty(instance),
            version=instance.version or "unknown",
            verifier_timeout=_DEFAULT_VERIFIER_TIMEOUT.get(language, 300.0),
            agent_timeout=_DEFAULT_AGENT_TIMEOUT.get(language, 1800.0),
            environment_block=env_block,
        )
        (task_dir / "task.toml").write_text(content)

    def _write_dockerfile(
        self,
        instance: TaskInstance,
        task_dir: Path,
        language: str,
        env_spec: AnyEnvironmentSpec | None,
    ) -> None:
        base_image_line = self._get_base_image_line(language, env_spec)
        extra_setup = self._get_extra_setup(language, env_spec)

        template = _load_template("dockerfile.template")
        content = string.Template(template).safe_substitute(
            base_image_line=base_image_line,
            repo=instance.repo,
            base_commit=instance.base_commit,
            extra_setup=extra_setup,
        )
        (task_dir / "environment" / "Dockerfile").write_text(content)

    def _get_base_image_line(self, language: str, env_spec: AnyEnvironmentSpec | None) -> str:
        if isinstance(env_spec, GoEnvironmentSpec) and env_spec.go_version:
            return f"FROM golang:{env_spec.go_version}"
        if isinstance(env_spec, RustEnvironmentSpec) and env_spec.rust_version:
            return f"FROM rust:{env_spec.rust_version}-slim"
        if isinstance(env_spec, EnvironmentSpec):
            if env_spec.base_image:
                return f"FROM {env_spec.base_image}"
            version = env_spec.language_version or "3.11"
            return f"FROM python:{version}-slim"

        defaults = {
            "go": "FROM golang:latest",
            "python": "FROM python:3.11-slim",
            "java": "FROM maven:3-eclipse-temurin-17",
            "rust": "FROM rust:latest",
        }
        return defaults.get(language, "FROM ubuntu:22.04")

    def _get_extra_setup(self, language: str, env_spec: AnyEnvironmentSpec | None) -> str:
        lines: list[str] = []

        if isinstance(env_spec, GoEnvironmentSpec):
            if env_spec.system_dependencies:
                pkgs = " ".join(env_spec.system_dependencies)
                lines.append(
                    f"RUN apt-get update -qq && "
                    f"apt-get install -y --no-install-recommends {pkgs} && "
                    f"rm -rf /var/lib/apt/lists/*"
                )
            if env_spec.goflags:
                lines.append(f'ENV GOFLAGS="{env_spec.goflags}"')
            lines.append("RUN cd /testbed && go mod download")

        elif isinstance(env_spec, EnvironmentSpec):
            if env_spec.system_dependencies:
                pkgs = " ".join(env_spec.system_dependencies)
                lines.append(
                    f"RUN apt-get update -qq && "
                    f"apt-get install -y --no-install-recommends {pkgs} && "
                    f"rm -rf /var/lib/apt/lists/*"
                )
            for cmd in env_spec.pre_install:
                lines.append(f"RUN cd /testbed && {cmd}")
            if env_spec.install_cmd:
                lines.append(f"RUN cd /testbed && {env_spec.install_cmd}")

        elif isinstance(env_spec, RustEnvironmentSpec):
            lines.append(
                "RUN apt-get update -qq && "
                "apt-get install -y --no-install-recommends git ca-certificates && "
                "rm -rf /var/lib/apt/lists/*"
            )
            if env_spec.system_dependencies:
                pkgs = " ".join(env_spec.system_dependencies)
                lines.append(
                    f"RUN apt-get update -qq && "
                    f"apt-get install -y --no-install-recommends {pkgs} && "
                    f"rm -rf /var/lib/apt/lists/*"
                )

        else:
            if language == "go":
                lines.append("RUN cd /testbed && go mod download")
            elif language == "python":
                lines.append(
                    'RUN cd /testbed && pip install -e ".[dev,test,testing]" 2>/dev/null '
                    '|| pip install -e "." 2>/dev/null '
                    '|| pip install -e ".[dev]" 2>/dev/null || true'
                )
                lines.append("RUN cd /testbed && pip install pytest 2>/dev/null || true")
            elif language == "java":
                lines.append("RUN cd /testbed && mvn dependency:resolve -B 2>/dev/null || true")
            elif language == "rust":
                lines.append("RUN cd /testbed && cargo fetch 2>/dev/null || true")

        return "\n".join(lines) if lines else "# No extra setup required"

    def _write_solve_sh(self, instance: TaskInstance, task_dir: Path) -> None:
        (task_dir / "solution" / "patch.diff").write_text(instance.patch)
        template = _load_template("solve.sh.template")
        path = task_dir / "solution" / "solve.sh"
        path.write_text(template)
        os.chmod(path, 0o755)

    def _write_test_sh(
        self,
        instance: TaskInstance,
        task_dir: Path,
        language: str,
        env_spec: AnyEnvironmentSpec | None,
    ) -> None:
        test_command = self._build_test_command(instance, language, env_spec)

        if language == "go":
            template_name = "test_go.sh.template"
        elif language == "python":
            template_name = "test_python.sh.template"
        elif language == "java":
            template_name = "test_java.sh.template"
        elif language == "rust":
            template_name = "test_rust.sh.template"
        else:
            raise ValueError(f"Unsupported language: {language}")

        template = _load_template(template_name)
        content = string.Template(template).safe_substitute(test_command=test_command)
        path = task_dir / "tests" / "test.sh"
        path.write_text(content)
        os.chmod(path, 0o755)

    def _build_test_command(
        self,
        instance: TaskInstance,
        language: str,
        env_spec: AnyEnvironmentSpec | None,
    ) -> str:
        backend = get_backend(language)

        if language == "go":
            if instance.test_patch:
                return _build_go_test_command(instance.test_patch)
            return "go test -v -count=1 ./..."

        if language == "python":
            scope = ""
            if instance.test_patch and backend:
                scope = backend.test_scope(instance.test_patch)
            base_cmd = "pytest -v"
            if env_spec and isinstance(env_spec, EnvironmentSpec) and env_spec.test_cmd:
                raw = env_spec.test_cmd
                if "-v" not in raw:
                    if "pytest" in raw:
                        raw = raw.replace("pytest", "pytest -v", 1)
                    else:
                        raw += " -v"
                base_cmd = raw
            if scope:
                return f"{base_cmd} {scope}"
            return base_cmd

        if language == "java":
            scope = ""
            if instance.test_patch and backend:
                scope = backend.test_scope(instance.test_patch)
            base_cmd = "mvn test -B"
            if scope:
                return f"{base_cmd} {scope}"
            return base_cmd

        if language == "rust":
            return "cargo test 2>&1"

        return "echo 'Unsupported language'"

    def _write_config_json(self, instance: TaskInstance, task_dir: Path) -> None:
        config = {
            'instance_id': instance.instance_id,
            'repo': instance.repo,
            'FAIL_TO_PASS': instance.FAIL_TO_PASS,
            'PASS_TO_PASS': instance.PASS_TO_PASS,
            'repo_language': instance.repo_language,
        }
        (task_dir / "tests" / "config.json").write_text(
            json.dumps(config, indent=2) + "\n"
        )

    def _write_test_patch(self, instance: TaskInstance, task_dir: Path) -> None:
        (task_dir / "tests" / "test.patch").write_text(instance.test_patch or "")


def emit_harbor_dataset(
    instances: list[TaskInstance],
    output_dir: str,
    registry_url: str | None = None,
    env_specs: dict[str, AnyEnvironmentSpec] | None = None,
) -> None:
    """Write instances as Harbor task directories.

    Each instance becomes a directory:
        {output_dir}/harbor-tasks/{instance_id}/
            instruction.md
            task.toml
            environment/Dockerfile
            solution/solve.sh
            tests/test.sh
            tests/config.json
            tests/test.patch
    """
    if not instances:
        logger.info("No instances to emit as Harbor tasks")
        return

    harbor_dir = Path(output_dir) / "harbor-tasks"
    harbor_dir.mkdir(parents=True, exist_ok=True)

    generator = HarborTaskGenerator(
        instances=instances,
        env_specs=env_specs,
        registry_url=registry_url,
    )
    generated = generator.generate_all(harbor_dir)

    _write_registry(instances, harbor_dir)
    _write_dataset_toml(instances, harbor_dir)

    logger.info(
        "Emitted %d/%d Harbor tasks to %s", len(generated), len(instances), harbor_dir
    )


def _write_registry(instances: list[TaskInstance], harbor_dir: Path) -> None:
    registry: list[dict[str, str]] = []
    for inst in instances:
        registry.append({
            "instance_id": inst.instance_id,
            "task_dir": inst.instance_id,
            "repo": inst.repo,
            "language": _detect_language(inst),
        })
    (harbor_dir / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")


def _write_dataset_toml(instances: list[TaskInstance], harbor_dir: Path) -> None:
    repos = sorted({inst.repo for inst in instances})
    languages = sorted({_detect_language(inst) for inst in instances})

    lang_str = ", ".join('"' + lang + '"' for lang in languages)
    repo_str = ", ".join('"' + repo + '"' for repo in repos)

    lines = [
        '[dataset]',
        'name = "swebenchify"',
        'source = "swebenchify"',
        f'task_count = {len(instances)}',
        f'languages = [{lang_str}]',
        f'repos = [{repo_str}]',
    ]
    (harbor_dir / "dataset.toml").write_text("\n".join(lines) + "\n")
