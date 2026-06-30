"""Test full pipeline on psf/requests and compare against SWE-bench fixture."""

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_requests")

from swebenchify.models import Repository, CandidateInstance  # noqa: E402
from swebenchify.collector import collect_prs, save_prs  # noqa: E402
from swebenchify.extractor import extract_all, save_candidates  # noqa: E402
from swebenchify.dispatcher import CostTracker  # noqa: E402
from swebenchify.discovery import discover_environment  # noqa: E402
from swebenchify.validator import validate_instance  # noqa: E402
from swebenchify.workspace import WorkspaceManager  # noqa: E402

FIXTURE_PATH = "tests/fixtures/swebench_requests.jsonl"
WORKSPACE_ROOT = "output/workspaces"

token = os.environ.get("GITHUB_TOKEN")
if not token:
    print("Set GITHUB_TOKEN first")
    sys.exit(1)

repo = Repository(full_name="psf/requests", access_token=token)

# Load fixture for comparison
fixture_instances = []
with open(FIXTURE_PATH) as f:
    for line in f:
        fixture_instances.append(json.loads(line))
fixture_ids = {inst["instance_id"] for inst in fixture_instances}
dates = sorted(inst["created_at"] for inst in fixture_instances)
logger.info(f"Fixture: {len(fixture_ids)} instances, {dates[0]} to {dates[-1]}")

# Stages 1-2: Collect and extract
PR_AFTER = "2012-01-01T00:00:00Z"
PR_BEFORE = "2022-06-01T00:00:00Z"

logger.info(f"\n=== Stage 1: Collecting PRs ({PR_AFTER} to {PR_BEFORE}) ===")
os.makedirs("output", exist_ok=True)
prs = collect_prs(repo, pr_after=PR_AFTER, pr_before=PR_BEFORE)
logger.info(f"Collected {len(prs)} candidate PRs")
save_prs(prs, "output/requests-prs.jsonl")

logger.info("\n=== Stage 2: Extracting patches ===")
candidates = extract_all(prs, github_token=token)
save_candidates(candidates, "output/requests-candidates.jsonl")

viable = [c for c in candidates if c.patch and c.test_patch and c.problem_statement]
logger.info(f"Viable: {len(viable)}/{len(candidates)}")

# Compare mechanical stages
our_ids = {c.instance_id for c in viable}
overlap = fixture_ids & our_ids
logger.info("\n=== Mechanical overlap ===")
logger.info(f"SWE-bench: {len(fixture_ids)} | Ours: {len(our_ids)} | Overlap: {len(overlap)} ({100*len(overlap)/len(fixture_ids):.0f}%)")
missing = fixture_ids - our_ids
if missing:
    logger.info(f"Missing: {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}")

# Stage 3-4: Pick 3 instances that overlap with the fixture for agentic testing
test_instances = sorted(overlap)[:3]
if not test_instances:
    logger.error("No overlapping instances to test agentic stages")
    sys.exit(1)

logger.info(f"\n=== Stages 3-4: Testing {len(test_instances)} instances ===")


async def run_agentic():
    workspace_mgr = WorkspaceManager(WORKSPACE_ROOT)
    cost_tracker = CostTracker()

    # Find fixture data for our test instances
    fixture_map = {inst["instance_id"]: inst for inst in fixture_instances}

    # Stage 3: Env discovery (use first instance's commit)
    first_fixture = fixture_map[test_instances[0]]
    commit = first_fixture["base_commit"]
    version = first_fixture["version"]

    logger.info(f"\nStage 3: Env discovery for psf/requests v{version} @ {commit[:12]}")
    env_spec, repo_version = await discover_environment(
        repo=repo, commit=commit, version=version,
        workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
        max_attempts=2, max_turns=50, budget_usd=5.0,
    )

    if not env_spec:
        logger.error("Env discovery failed!")
        logger.info(cost_tracker.summary())
        return

    logger.info(f"  Language: {env_spec.language} {env_spec.language_version}")
    logger.info(f"  Install: {env_spec.install_cmd}")
    logger.info(f"  Test: {env_spec.test_cmd}")

    # Stage 4: Validate each test instance
    for instance_id in test_instances:
        fixture = fixture_map[instance_id]
        logger.info(f"\nStage 4: Validating {instance_id}")

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

        result = await validate_instance(
            candidate=candidate, env_spec=env_spec, repo=repo,
            workspace_mgr=workspace_mgr, cost_tracker=cost_tracker,
            max_attempts=2, max_turns=50, budget_usd=3.0,
        )

        expected_f2p = json.loads(fixture["FAIL_TO_PASS"])
        f2p_match = set(result.FAIL_TO_PASS) == set(expected_f2p)

        logger.info(f"  Status: {result.status}")
        logger.info(f"  FAIL_TO_PASS: {result.FAIL_TO_PASS}")
        logger.info(f"  Expected F2P: {expected_f2p}")
        logger.info(f"  F2P match: {'YES' if f2p_match else 'NO'}")
        if result.error_message:
            logger.info(f"  Error: {result.error_message}")

    logger.info("\n=== Cost Summary ===")
    logger.info(cost_tracker.summary())


asyncio.run(run_agentic())
