#!/usr/bin/env python
"""Run SWE-bench Docker-based validation on our instances (Phase 1.3b).

Calls swebench harness functions directly with podman host networking.

Usage:
    podman system service --time=3600 unix:///tmp/podman.sock &
    export DOCKER_HOST=unix:///tmp/podman.sock
    python scripts/run_docker_validation.py --repo psf/requests --max-instances 5
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def patch_network():
    """Patch Docker SDK to use host networking for builds."""
    import docker.api.build
    orig = docker.api.build.BuildApiMixin.build
    def patched(self, *a, **kw):
        kw.setdefault("network_mode", "host")
        return orig(self, *a, **kw)
    docker.api.build.BuildApiMixin.build = patched


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--max-instances", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    patch_network()

    import docker
    from datasets import load_dataset
    from swebench.harness.test_spec.test_spec import make_test_spec
    from swebench.harness.docker_build import build_env_images
    from swebench.harness.run_evaluation import run_instance

    docker_host = os.environ.get("DOCKER_HOST", "unix:///tmp/podman.sock")
    client = docker.DockerClient(base_url=docker_host)
    logger.info("Connected to Docker at %s", docker_host)

    ds = load_dataset("princeton-nlp/SWE-bench", split="test")
    instances = [dict(row) for row in ds if row["repo"] == args.repo]
    instances = instances[:args.max_instances]
    logger.info("Selected %d instances for %s", len(instances), args.repo)

    test_specs = []
    for inst in instances:
        try:
            ts = make_test_spec(inst)
            test_specs.append((inst, ts))
        except Exception as e:
            logger.warning("make_test_spec failed for %s: %s", inst["instance_id"], e)

    logger.info("Created %d TestSpecs", len(test_specs))
    if not test_specs:
        logger.error("No valid TestSpecs — nothing to run")
        return

    logger.info("Building env images...")
    try:
        build_env_images(client, [ts for _, ts in test_specs], force_rebuild=False, max_workers=1)
    except Exception as e:
        logger.error("build_env_images failed: %s", e)
        return

    results = {}
    for inst, ts in test_specs:
        iid = inst["instance_id"]
        pred = {
            "instance_id": iid,
            "model_name_or_path": "gold",
            "model_patch": inst["patch"],
        }
        logger.info("Running %s...", iid)
        try:
            result = run_instance(
                test_spec=ts,
                pred=pred,
                rm_image=True,
                force_rebuild=False,
                client=client,
                run_id="docker_val",
                timeout=args.timeout,
            )
            results[iid] = result
            logger.info("  %s: resolved=%s", iid, result.get("resolved"))
        except Exception as e:
            logger.error("  %s: error %s", iid, e)
            results[iid] = {"completed": False, "resolved": False, "error": str(e)}

    # Compare against published F2P
    swebench_f2p = {}
    for inst, _ in test_specs:
        f2p = inst["FAIL_TO_PASS"]
        if isinstance(f2p, str):
            f2p = json.loads(f2p)
        swebench_f2p[inst["instance_id"]] = f2p

    completed = sum(1 for r in results.values() if r.get("completed"))
    resolved = sum(1 for r in results.values() if r.get("resolved"))
    total = len(results)

    print(f"\n{'='*60}")
    print(f"Docker Validation Results ({args.repo})")
    print(f"{'='*60}")
    print(f"Total: {total}, Completed: {completed}, Resolved: {resolved}")
    for iid, r in sorted(results.items()):
        status = "RESOLVED" if r.get("resolved") else ("COMPLETED" if r.get("completed") else "ERROR")
        print(f"  [{status}] {iid}")

    if resolved == total and total > 0:
        print(f"\nAll {total} gold patches resolved — Docker validation working correctly")
        print("Target (>=85%): PASS")

    out = Path("results/docker_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    logger.info("Results saved to %s", out)


if __name__ == "__main__":
    main()
