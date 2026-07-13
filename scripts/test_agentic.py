"""Smoke-test agentic stages (3-4) on a known Flask instance."""

import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_agentic")

from swebenchify.discovery import discover_environment  # noqa: E402
from swebenchify.dispatcher import CostTracker  # noqa: E402
from swebenchify.models import EnvironmentSpec, Repository  # noqa: E402
from swebenchify.validator import validate_instance  # noqa: E402
from swebenchify.workspace import WorkspaceManager  # noqa: E402

# Pick pallets__flask-5063 from the SWE-bench fixture
INSTANCE_ID = "pallets__flask-5063"
FIXTURE_PATH = "tests/fixtures/swebench_flask.jsonl"
WORKSPACE_ROOT = "output/workspaces"


def load_fixture_instance(instance_id: str) -> dict:
    with open(FIXTURE_PATH) as f:
        for line in f:
            d = json.loads(line)
            if d["instance_id"] == instance_id:
                return d
    raise ValueError(f"Instance {instance_id} not found in fixture")


async def test_env_discovery():
    """Stage 3: Can the agent discover Flask's build/test environment?"""
    logger.info("=" * 60)
    logger.info("STAGE 3: Environment Discovery")
    logger.info("=" * 60)

    fixture = load_fixture_instance(INSTANCE_ID)
    repo = Repository(full_name="pallets/flask")
    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()

    commit = fixture["base_commit"]
    version = fixture["version"]

    logger.info(f"Repo: {repo.full_name}")
    logger.info(f"Commit: {commit}")
    logger.info(f"Expected version: {version}")

    env_spec, repo_version = await discover_environment(
        repo=repo,
        commit=commit,
        version=version,
        workspace_mgr=workspace_mgr,
        cost_tracker=cost_tracker,
        max_attempts=2,
        max_turns=50,
        budget_usd=3.0,
    )

    if env_spec is None:
        logger.error("FAIL: Environment discovery returned None")
        logger.info(f"Cost: {cost_tracker.summary()}")
        return None

    logger.info("SUCCESS: Environment discovered")
    logger.info(f"  Language: {env_spec.language} {env_spec.language_version}")
    logger.info(f"  Package manager: {env_spec.package_manager}")
    logger.info(f"  Install: {env_spec.install_cmd}")
    logger.info(f"  Test: {env_spec.test_cmd}")
    logger.info(f"  Pre-install: {env_spec.pre_install}")
    logger.info(f"  System deps: {env_spec.system_dependencies}")
    if repo_version:
        logger.info(f"  Detected version: {repo_version.version} (expected: {version})")
    logger.info(f"Cost: {cost_tracker.summary()}")

    return env_spec


async def test_validation(env_spec: EnvironmentSpec):
    """Stage 4: Can the agent validate an instance and extract FAIL_TO_PASS?"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("STAGE 4: Instance Validation")
    logger.info("=" * 60)

    fixture = load_fixture_instance(INSTANCE_ID)
    repo = Repository(full_name="pallets/flask")
    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()

    # Build a CandidateInstance from the fixture data
    from swebenchify.models import CandidateInstance
    candidate = CandidateInstance(
        repo=fixture["repo"],
        instance_id=fixture["instance_id"],
        pr_number=int(fixture["instance_id"].rsplit("-", 1)[1]),
        base_commit=fixture["base_commit"],
        merge_commit="",
        patch=fixture["patch"],
        test_patch=fixture["test_patch"],
        problem_statement=fixture["problem_statement"],
        hints_text=fixture["hints_text"],
        created_at=fixture["created_at"],
    )

    logger.info(f"Instance: {candidate.instance_id}")
    logger.info(f"Commit: {candidate.base_commit}")
    logger.info(f"Patch lines: {len((candidate.patch or '').splitlines())}")
    logger.info(f"Test patch lines: {len((candidate.test_patch or '').splitlines())}")

    result = await validate_instance(
        candidate=candidate,
        env_spec=env_spec,
        repo=repo,
        workspace_mgr=workspace_mgr,
        cost_tracker=cost_tracker,
        max_attempts=2,
        max_turns=50,
        budget_usd=3.0,
    )

    logger.info(f"Status: {result.status}")
    logger.info(f"FAIL_TO_PASS: {result.FAIL_TO_PASS}")
    logger.info(f"PASS_TO_PASS: {len(result.PASS_TO_PASS)} tests")
    if result.error_message:
        logger.info(f"Error: {result.error_message}")
    logger.info(f"Cost: {cost_tracker.summary()}")

    # Compare against SWE-bench ground truth
    expected_f2p = json.loads(fixture["FAIL_TO_PASS"])
    expected_p2p = json.loads(fixture["PASS_TO_PASS"])

    logger.info("")
    logger.info("--- Comparison with SWE-bench ---")
    logger.info(f"Expected FAIL_TO_PASS: {expected_f2p}")
    logger.info(f"Got FAIL_TO_PASS:      {result.FAIL_TO_PASS}")

    f2p_match = set(result.FAIL_TO_PASS) == set(expected_f2p)
    logger.info(f"FAIL_TO_PASS match: {'YES' if f2p_match else 'NO'}")

    if result.PASS_TO_PASS:
        p2p_overlap = set(result.PASS_TO_PASS) & set(expected_p2p)
        logger.info(f"PASS_TO_PASS overlap: {len(p2p_overlap)}/{len(expected_p2p)} expected tests")

    return result


async def main():
    # Stage 3
    env_spec = await test_env_discovery()
    if env_spec is None:
        logger.error("Aborting: env discovery failed")
        sys.exit(1)

    # Stage 4
    result = await test_validation(env_spec)
    if result.status != "valid":
        logger.warning(f"Validation status: {result.status} (not 'valid')")

    logger.info("")
    logger.info("=" * 60)
    logger.info("DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
