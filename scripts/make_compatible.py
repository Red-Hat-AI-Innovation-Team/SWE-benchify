"""Rebuild task instances from on-disk validation results with SWE-bench compatibility.

Reads validation_result.json files, snaps versions to SWE-bench supported values,
sets environment_setup_commit, and filters to only compatible instances.
Then validates each instance can produce a SWE-bench TestSpec.
"""

import json
import logging
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("make_compatible")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from swebenchify.models import TaskInstance
from swebenchify.extractor import load_candidates
from swebenchify.versioning import detect_version
from swebenchify.compat import snap_version, get_environment_setup_commit, is_version_supported

OUTPUT_DIR = Path("output")
WORKSPACE_ROOT = Path("output/workspaces")


def build_all():
    all_instances = []

    for repo_slug in ["pallets__flask", "psf__requests"]:
        repo_name = repo_slug.replace("__", "/")
        candidates_file = OUTPUT_DIR / f"{repo_slug}-candidates.jsonl"
        if not candidates_file.exists():
            continue

        candidates = {c.instance_id: c for c in load_candidates(str(candidates_file))}
        bare_clone = WORKSPACE_ROOT / repo_slug / "repo.git"
        instances_dir = WORKSPACE_ROOT / repo_slug / "instances"
        if not instances_dir.exists():
            continue

        compatible = 0
        incompatible = 0
        total_valid = 0

        for inst_dir in sorted(instances_dir.iterdir()):
            result_file = inst_dir / "repo" / "validation_result.json"
            if not result_file.exists():
                continue
            try:
                vr = json.loads(result_file.read_text())
            except json.JSONDecodeError:
                continue
            if vr.get("status") != "valid":
                continue
            total_valid += 1

            instance_id = inst_dir.name
            candidate = candidates.get(instance_id)
            if not candidate:
                continue

            # Detect and snap version
            raw_version = detect_version(str(bare_clone), candidate.base_commit) or "unknown"
            version = snap_version(repo_name, raw_version)
            if not version:
                incompatible += 1
                continue

            # Get environment_setup_commit
            env_commit = get_environment_setup_commit(repo_name, version, repo_path=str(bare_clone))

            inst = TaskInstance(
                repo=repo_name,
                instance_id=instance_id,
                base_commit=candidate.base_commit,
                patch=candidate.patch or "",
                test_patch=candidate.test_patch or "",
                problem_statement=candidate.problem_statement or "",
                hints_text=candidate.hints_text or "",
                created_at=candidate.created_at,
                version=version,
                FAIL_TO_PASS=json.dumps(vr.get("FAIL_TO_PASS", [])),
                PASS_TO_PASS=json.dumps(vr.get("PASS_TO_PASS", [])),
                environment_setup_commit=env_commit,
            )
            all_instances.append(inst)
            compatible += 1

        logger.info(f"{repo_name}: {total_valid} valid, {compatible} compatible, {incompatible} incompatible")

    return all_instances


def validate_with_swebench(instances):
    """Try to create a TestSpec for each instance using SWE-bench's harness."""
    try:
        from swebench.harness.test_spec.test_spec import make_test_spec
    except ImportError:
        logger.warning("swebench not installed, skipping TestSpec validation")
        return instances

    valid = []
    for inst in instances:
        d = asdict(inst)
        try:
            spec = make_test_spec(d)
            valid.append(inst)
        except Exception as e:
            logger.warning(f"  TestSpec failed for {inst.instance_id}: {e}")

    return valid


def main():
    logger.info("Building SWE-bench compatible instances...")
    instances = build_all()
    logger.info(f"Built {len(instances)} compatible instances")

    logger.info("\nValidating with SWE-bench TestSpec...")
    valid = validate_with_swebench(instances)
    logger.info(f"{len(valid)}/{len(instances)} produce valid TestSpecs")

    # Save
    out_file = OUTPUT_DIR / "swebenchify-dataset.jsonl"
    with open(out_file, "w") as f:
        for inst in valid:
            f.write(json.dumps(asdict(inst)) + "\n")
    logger.info(f"\nSaved to {out_file}")

    # Summary
    by_repo = defaultdict(int)
    for inst in valid:
        by_repo[inst.repo] += 1
    for repo, count in sorted(by_repo.items()):
        logger.info(f"  {repo}: {count} instances")

    # Compare with SWE-bench fixture
    for repo_name, fixture_file in [("pallets/flask", "tests/fixtures/swebench_flask.jsonl"),
                                     ("psf/requests", "tests/fixtures/swebench_requests.jsonl")]:
        if not Path(fixture_file).exists():
            continue
        fixture_ids = set()
        with open(fixture_file) as f:
            for line in f:
                fixture_ids.add(json.loads(line)["instance_id"])
        our_ids = {i.instance_id for i in valid if i.repo == repo_name}
        overlap = fixture_ids & our_ids
        logger.info(f"\n  {repo_name} overlap with SWE-bench: {len(overlap)}/{len(fixture_ids)} ({100*len(overlap)/len(fixture_ids):.0f}%)")
        if fixture_ids - our_ids:
            logger.info(f"    Missing: {sorted(fixture_ids - our_ids)}")


if __name__ == "__main__":
    main()
