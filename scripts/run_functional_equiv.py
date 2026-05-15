#!/usr/bin/env python
"""Measure functional equivalence of agent-generated specs (Phase 1.1c).

For each (repo, version) pair where we have both an agent-generated spec
and SWE-bench's ground truth spec, build Docker images with each spec,
run tests on the same commit, and compare pass/fail sets.

Usage:
    # Start podman socket first:
    # podman system service --time=3600 unix:///tmp/podman.sock &
    # export DOCKER_HOST=unix:///tmp/podman.sock

    # Run on Flask
    python scripts/run_functional_equiv.py --repo pallets/flask

    # Dry run
    python scripts/run_functional_equiv.py --repo pallets/flask --dry-run

    # Use cached specs from a previous benchmark run
    python scripts/run_functional_equiv.py --repo pallets/flask \
        --specs-dir output/workspaces
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from swebenchify.spec_bench import load_ground_truth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class FunctionalResult:
    """Result of running tests with a spec on a specific commit."""

    repo: str
    version: str
    spec_source: str  # "agent" or "swebench"
    commit: str
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    success: bool = False
    error_message: str | None = None


@dataclass
class EquivalenceResult:
    """Comparison of agent vs SWE-bench spec on the same commit."""

    repo: str
    version: str
    commit: str
    agent_result: FunctionalResult | None = None
    swebench_result: FunctionalResult | None = None
    pass_set_match: bool = False
    fail_set_match: bool = False
    jaccard_pass: float = 0.0
    jaccard_fail: float = 0.0


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def get_version_commits(repo: str) -> dict[str, str]:
    """Get a representative commit per version from SWE-bench dataset."""
    try:
        from datasets import load_dataset
        ds = load_dataset("princeton-nlp/SWE-bench", split="test")
        commits: dict[str, str] = {}
        for row in ds:
            if row["repo"] == repo and row["version"] not in commits:
                commits[row["version"]] = row["base_commit"]
        return commits
    except Exception as e:
        logger.error("Failed to load dataset: %s", e)
        return {}


def load_agent_specs(workspace_root: Path, repo: str) -> dict[str, dict]:
    """Load agent-generated specs from workspace cache."""
    slug = repo.replace("/", "__")
    envs_dir = workspace_root / slug / "envs"
    specs: dict[str, dict] = {}
    if not envs_dir.is_dir():
        return specs
    for version_dir in sorted(envs_dir.iterdir()):
        if not version_dir.is_dir():
            continue
        spec_file = version_dir / "env_spec.json"
        if spec_file.exists():
            try:
                specs[version_dir.name] = json.loads(spec_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    return specs


def agent_spec_to_swebench_format(agent_spec: dict) -> dict:
    """Convert an agent-generated spec to SWE-bench's expected format."""
    return {
        "python": agent_spec.get("language_version", agent_spec.get("python", "3.9")),
        "install": agent_spec.get("install_cmd", agent_spec.get("install", "pip install -e .")),
        "test_cmd": agent_spec.get("test_cmd", "pytest -rA"),
        "pip_packages": agent_spec.get("pip_packages", []),
        "pre_install": agent_spec.get("pre_install", []),
        "packages": agent_spec.get("packages", ""),
    }


def run_tests_with_spec(
    instance: dict,
    spec: dict,
    spec_source: str,
    timeout: int = 600,
) -> FunctionalResult:
    """Build a Docker image with the given spec and run tests.

    Uses swebench.harness machinery to build and run.
    """
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
    from swebench.harness.test_spec.test_spec import make_test_spec

    repo = instance["repo"]
    version = instance["version"]
    commit = instance["base_commit"]

    original_specs = MAP_REPO_VERSION_TO_SPECS.get(repo, {}).get(version)

    try:
        MAP_REPO_VERSION_TO_SPECS.setdefault(repo, {})[version] = spec
        test_spec = make_test_spec(instance)

        import docker
        import os

        docker_host = os.environ.get("DOCKER_HOST", "unix:///tmp/podman.sock")
        client = docker.DockerClient(base_url=docker_host)

        from swebench.harness.docker_build import (
            build_base_images,
            build_env_images,
            build_instance_images,
        )
        from swebench.harness.run_evaluation import run_instance

        logger.info("Building images for %s v%s (%s spec)...", repo, version, spec_source)

        build_base_images(client, [test_spec], force_rebuild=False)
        build_env_images(client, [test_spec], force_rebuild=False)

        instance_images = build_instance_images(client, [test_spec], force_rebuild=True)

        if not instance_images:
            return FunctionalResult(
                repo=repo, version=version, spec_source=spec_source,
                commit=commit, error_message="Failed to build instance image",
            )

        result = run_instance(test_spec, {"model_patch": ""}, client=client, timeout=timeout)

        passed = result.get("resolved_tests", {}).get("PASSED", [])
        failed = result.get("resolved_tests", {}).get("FAILED", [])

        return FunctionalResult(
            repo=repo, version=version, spec_source=spec_source,
            commit=commit, passed=passed, failed=failed, success=True,
        )

    except Exception as e:
        logger.error("Error running tests with %s spec for %s v%s: %s",
                      spec_source, repo, version, e)
        return FunctionalResult(
            repo=repo, version=version, spec_source=spec_source,
            commit=commit, error_message=str(e),
        )
    finally:
        if original_specs is not None:
            MAP_REPO_VERSION_TO_SPECS[repo][version] = original_specs


def compare_results(
    repo: str,
    version: str,
    commit: str,
    agent_result: FunctionalResult,
    swebench_result: FunctionalResult,
) -> EquivalenceResult:
    """Compare test results from agent and SWE-bench specs."""
    agent_pass = set(agent_result.passed)
    swebench_pass = set(swebench_result.passed)
    agent_fail = set(agent_result.failed)
    swebench_fail = set(swebench_result.failed)

    return EquivalenceResult(
        repo=repo,
        version=version,
        commit=commit,
        agent_result=agent_result,
        swebench_result=swebench_result,
        pass_set_match=agent_pass == swebench_pass,
        fail_set_match=agent_fail == swebench_fail,
        jaccard_pass=jaccard(agent_pass, swebench_pass),
        jaccard_fail=jaccard(agent_fail, swebench_fail),
    )


def format_results(results: list[EquivalenceResult]) -> str:
    """Format equivalence results as a human-readable report."""
    lines = [
        "=" * 70,
        "Functional Equivalence: Agent Spec vs SWE-bench Spec",
        "=" * 70,
        "",
    ]

    if not results:
        lines.append("No results to report.")
        return "\n".join(lines)

    pass_match_count = sum(1 for r in results if r.pass_set_match)
    mean_jaccard = sum(r.jaccard_pass for r in results) / len(results)

    lines.append(f"Versions tested:     {len(results)}")
    lines.append(f"Pass-set match:      {pass_match_count}/{len(results)} ({pass_match_count/len(results):.0%})")
    lines.append(f"Mean Jaccard (pass): {mean_jaccard:.3f}")
    lines.append(f"Target (>=80%):      {'PASS' if pass_match_count/len(results) >= 0.8 else 'FAIL'}")
    lines.append("")

    for r in results:
        status = "MATCH" if r.pass_set_match else f"DIFFER (J={r.jaccard_pass:.2f})"
        lines.append(f"  {r.repo} v{r.version}: {status}")
        if r.agent_result and r.swebench_result:
            lines.append(f"    agent:   {len(r.agent_result.passed)} passed, {len(r.agent_result.failed)} failed")
            lines.append(f"    swebench: {len(r.swebench_result.passed)} passed, {len(r.swebench_result.failed)} failed")
        if not r.pass_set_match and r.agent_result and r.swebench_result:
            agent_only = set(r.agent_result.passed) - set(r.swebench_result.passed)
            swebench_only = set(r.swebench_result.passed) - set(r.agent_result.passed)
            if agent_only:
                lines.append(f"    agent-only pass:   {len(agent_only)} tests")
            if swebench_only:
                lines.append(f"    swebench-only pass: {len(swebench_only)} tests")
        if r.agent_result and r.agent_result.error_message:
            lines.append(f"    agent error: {r.agent_result.error_message}")
        if r.swebench_result and r.swebench_result.error_message:
            lines.append(f"    swebench error: {r.swebench_result.error_message}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Functional equivalence test (Phase 1.1c)")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--specs-dir", type=Path, default=Path("output/workspaces"),
                        help="Directory with cached agent specs")
    parser.add_argument("--versions", help="Comma-separated versions to test")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=600, help="Docker test timeout in seconds")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ground_truth = load_ground_truth(args.repo)
    agent_specs = load_agent_specs(args.specs_dir, args.repo)
    version_commits = get_version_commits(args.repo)

    target_versions = set(ground_truth.keys()) & set(agent_specs.keys()) & set(version_commits.keys())
    if args.versions:
        target_versions &= set(args.versions.split(","))

    logger.info("Versions with both specs and commits: %s", sorted(target_versions))

    if args.dry_run:
        print(f"\n{args.repo}: would test functional equivalence for {len(target_versions)} versions")
        for v in sorted(target_versions):
            print(f"  {v}: commit={version_commits[v][:12]}...")
        return

    results: list[EquivalenceResult] = []

    for version in sorted(target_versions):
        commit = version_commits[version]
        gt_spec = ground_truth[version]
        ag_spec = agent_spec_to_swebench_format(agent_specs[version])

        instance = {
            "repo": args.repo,
            "instance_id": f"{args.repo.replace('/', '__')}-bench-{version}",
            "version": version,
            "base_commit": commit,
            "test_patch": "",
            "FAIL_TO_PASS": "[]",
            "PASS_TO_PASS": "[]",
            "problem_statement": "",
            "hints_text": "",
            "created_at": "",
            "environment_setup_commit": commit,
            "patch": "",
        }

        logger.info("Testing %s v%s with SWE-bench spec...", args.repo, version)
        swebench_result = run_tests_with_spec(instance, gt_spec, "swebench", timeout=args.timeout)

        logger.info("Testing %s v%s with agent spec...", args.repo, version)
        agent_result = run_tests_with_spec(instance, ag_spec, "agent", timeout=args.timeout)

        result = compare_results(args.repo, version, commit, agent_result, swebench_result)
        results.append(result)

    if args.json:
        output = {
            "repo": args.repo,
            "results": [
                {
                    "version": r.version,
                    "pass_set_match": r.pass_set_match,
                    "jaccard_pass": r.jaccard_pass,
                    "agent_passed": len(r.agent_result.passed) if r.agent_result else 0,
                    "swebench_passed": len(r.swebench_result.passed) if r.swebench_result else 0,
                }
                for r in results
            ],
        }
        json_str = json.dumps(output, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_str)
        else:
            print(json_str)
    else:
        print(format_results(results))


if __name__ == "__main__":
    main()
