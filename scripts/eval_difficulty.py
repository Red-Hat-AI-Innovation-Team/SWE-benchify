"""Difficulty eval — re-enrich existing instances, eval on OpenShift, measure Haiku failure rate.

Used by the remote-factory difficulty workflow. Takes existing validated
instances (data/opus-final-valid.jsonl), re-enriches a sample using the
current worktree's enrichment code (picking up prompt/logic changes),
then launches eval jobs on OpenShift via `oc`.

Usage:
    python3 scripts/eval_difficulty.py                    # 20 instances
    python3 scripts/eval_difficulty.py --quick             # 5 instances
    python3 scripts/eval_difficulty.py --n-instances 50    # Custom count
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

SYNTH_MODEL = "claude-opus-4-6"
NAMESPACE = "swebenchify"
IMAGE = "ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming"
INSTANCES_FILE = os.path.join(PROJECT_ROOT, "data/opus-final-valid.jsonl")

log = logging.getLogger("eval_difficulty")
log.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
log.addHandler(_handler)

# ── Vertex monkey-patch (same pattern as eval_synthesizer.py) ────

from anthropic import AnthropicVertex  # noqa: E402

CLIENT = AnthropicVertex()


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeResultMessage:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


async def _vertex_query(prompt, options=None):
    resp = CLIENT.messages.create(
        model=SYNTH_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text if resp.content else ""
    yield _FakeResultMessage(text)


class _FakeOptions:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


import swebenchify.synthesizer as synth_mod  # noqa: E402

synth_mod.query = _vertex_query
synth_mod.ResultMessage = _FakeResultMessage
synth_mod.ClaudeCodeOptions = _FakeOptions


# ── Cluster helpers ──────────────────────────────────────────────


def oc(*args, timeout=120):
    r = subprocess.run(["oc"] + list(args), capture_output=True, text=True, timeout=timeout)
    return r


def launch_jobs_from_jsonl(instances_jsonl, component, job_yaml, prefix="diff"):
    launched = 0
    for line in open(instances_jsonl):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        iid = d.get("instance_id", "")
        repo = d.get("repo", "")
        slug = re.sub(r"[^a-z0-9-]", "-", iid.lower().replace("_", "-"))[:63].rstrip("-")
        job_slug = f"{prefix}-{slug}"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(d) + "\n")
            tmpf = f.name

        cm_name = f"eval-input-{job_slug}"
        oc("delete", "configmap", cm_name, "-n", NAMESPACE)
        oc("create", "configmap", cm_name, f"--from-file=instance.jsonl={tmpf}", "-n", NAMESPACE)
        os.unlink(tmpf)

        env = os.environ.copy()
        env["REPO_FULL"] = repo
        env["INSTANCE_SLUG"] = job_slug
        env["IMAGE"] = IMAGE
        env["NAMESPACE"] = NAMESPACE
        env["LANGUAGE"] = "go"
        env["MODEL"] = "haiku"

        envsubst_vars = "${REPO_FULL} ${INSTANCE_SLUG} ${IMAGE} ${NAMESPACE} ${LANGUAGE} ${MODEL}"
        subprocess.run(
            f"envsubst '{envsubst_vars}' < {job_yaml} | oc apply -n {NAMESPACE} -f -",
            shell=True, capture_output=True, env=env,
        )
        launched += 1

    log.info("Launched %d %s jobs (prefix=%s)", launched, component, prefix)
    return launched


def wait_for_jobs(prefix="diff", timeout=1800):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = oc("get", "jobs", "-l", "component=eval", "-n", NAMESPACE, "--no-headers")
        lines = [x for x in r.stdout.strip().split("\n") if x and prefix in x]
        if not lines:
            break
        running = sum(1 for x in lines if "Running" in x)
        complete = sum(1 for x in lines if "Complete" in x)
        failed = sum(1 for x in lines if "Failed" in x)
        if running == 0:
            break
        log.info("Waiting: %d running, %d complete, %d failed", running, complete, failed)
        time.sleep(30)


def collect_annotations(prefix="diff"):
    r = oc("get", "jobs", "-l", "component=eval", "-n", NAMESPACE, "-o", "json", timeout=60)
    if r.returncode != 0:
        return []
    data = json.loads(r.stdout)
    results = []
    for job in data.get("items", []):
        name = job["metadata"]["name"]
        if prefix not in name:
            continue
        result_str = job.get("metadata", {}).get("annotations", {}).get("result", "")
        if result_str:
            try:
                results.append(json.loads(result_str, strict=False))
            except json.JSONDecodeError:
                pass
    return results


def cleanup_jobs(prefix="diff"):
    r = oc("get", "jobs", "-l", "component=eval", "-n", NAMESPACE,
           "--no-headers", "-o", "custom-columns=NAME:.metadata.name")
    for name in r.stdout.strip().split("\n"):
        name = name.strip()
        if name and prefix in name:
            oc("delete", "job", name, "-n", NAMESPACE, "--wait=false")
            oc("delete", "configmap", f"eval-input-{name.replace('eval-', '', 1)}", "-n", NAMESPACE)


# ── Main eval ────────────────────────────────────────────────────


def run_eval(n_instances=20, seed=None):
    round_id = f"r{int(time.time()) % 100000}"
    prefix = f"diff-{round_id}"

    # ── Step 1: Load existing validated instances ──
    if not os.path.isfile(INSTANCES_FILE):
        print(json.dumps({"score": 0.0, "details": f"Missing {INSTANCES_FILE}"}))
        return

    all_instances = []
    for line in open(INSTANCES_FILE):
        try:
            all_instances.append(json.loads(line.strip()))
        except json.JSONDecodeError:
            continue

    log.info("Loaded %d validated instances from %s", len(all_instances), INSTANCES_FILE)

    # Sample a subset
    rng = random.Random(seed)
    sample = rng.sample(all_instances, min(n_instances, len(all_instances)))
    log.info("Sampled %d instances for this round", len(sample))

    # ── Step 2: Re-enrich using current worktree code ──
    log.info("Re-enriching %d instances with current code...", len(sample))
    enriched = []
    for i, inst in enumerate(sample):
        iid = inst.get("instance_id", "?")
        repo = inst.get("repo", "")
        repo_path = f"/tmp/eval-difficulty-{repo.replace('/', '-')}"

        # Clone repo if needed
        if not os.path.isdir(repo_path):
            log.info("Cloning %s", repo)
            subprocess.run(["git", "clone", "--depth=1",
                           f"https://github.com/{repo}.git", repo_path],
                           capture_output=True, timeout=300)

        try:
            result = asyncio.run(synth_mod.enrich_instance(inst, repo_path, model=SYNTH_MODEL))
            if result:
                enriched.append(result)
                log.info("[%d/%d] Enriched %s", i + 1, len(sample), iid)
            else:
                log.warning("[%d/%d] Enrichment returned None for %s", i + 1, len(sample), iid)
        except Exception as e:
            log.warning("[%d/%d] Enrichment failed for %s: %s", i + 1, len(sample), iid, e)

    log.info("Enriched: %d/%d", len(enriched), len(sample))

    if not enriched:
        print(json.dumps({"score": 0.0, "details": "No instances enriched successfully"}))
        return

    # ── Step 3: Prep for eval ──
    eval_instances = []
    for inst in enriched:
        inst["version"] = "1.0"
        inst["repo_language"] = "go"
        if isinstance(inst.get("FAIL_TO_PASS"), list):
            inst["FAIL_TO_PASS"] = json.dumps(inst["FAIL_TO_PASS"])
        if isinstance(inst.get("PASS_TO_PASS"), list):
            inst["PASS_TO_PASS"] = json.dumps(inst["PASS_TO_PASS"])
        if "hints_text" not in inst:
            inst["hints_text"] = ""
        eval_instances.append(inst)

    # ── Step 4: Launch eval on cluster ──
    log.info("Launching eval on cluster (%d instances)", len(eval_instances))
    eval_jsonl = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for inst in eval_instances:
        eval_jsonl.write(json.dumps(inst) + "\n")
    eval_jsonl.close()

    launch_jobs_from_jsonl(
        eval_jsonl.name, "eval",
        os.path.join(PROJECT_ROOT, "k8s/eval-job.yaml"),
        prefix=prefix,
    )
    os.unlink(eval_jsonl.name)

    # ── Step 5: Wait and collect ──
    wait_for_jobs(prefix=prefix, timeout=3600)
    eval_results = collect_annotations(prefix=prefix)

    # ── Step 6: Compute scores ──
    n_eval = len(eval_results)
    n_resolved = sum(1 for r in eval_results if r.get("resolved"))
    haiku_failure = (n_eval - n_resolved) / n_eval if n_eval > 0 else 0.0

    # Bug category diversity
    categories = {}
    for inst in enriched:
        cat = inst.get("_pipeline", {}).get("bug_spec", {}).get("bug_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    n_categories = len(categories)
    diversity = min(1.0, n_categories / 5.0) if enriched else 0.0

    score = 0.7 * haiku_failure + 0.15 * diversity + 0.15 * 0.5

    # ── Step 7: Cleanup ──
    cleanup_jobs(prefix=prefix)

    # ── Output ──
    result = {
        "score": round(score, 4),
        "haiku_failure": round(haiku_failure, 4),
        "diversity": round(diversity, 4),
        "n_sampled": len(sample),
        "n_enriched": len(enriched),
        "n_eval": n_eval,
        "n_resolved": n_resolved,
        "categories": categories,
        "per_instance": [
            {
                "instance_id": r.get("instance_id"),
                "resolved": r.get("resolved"),
                "patch_lines": len(r.get("agent_patch", "").strip().splitlines()),
            }
            for r in eval_results
        ],
    }
    print(json.dumps(result))
    log.info("Score=%.4f haiku_failure=%.4f diversity=%.4f (%d/%d resolved)",
             score, haiku_failure, diversity, n_resolved, n_eval)

    # Save detailed results
    results_dir = os.path.join(PROJECT_ROOT, ".factory", "reviews")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "difficulty-eval-latest.json"), "w") as f:
        json.dump(result, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Difficulty eval for remote-factory")
    parser.add_argument("--quick", action="store_true", help="Quick mode (5 instances)")
    parser.add_argument("--n-instances", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for sampling")
    parser.add_argument("--role", type=str, default="generator", help="generator or discriminator")
    args = parser.parse_args()

    n = 5 if args.quick else args.n_instances
    run_eval(n_instances=n, seed=args.seed)


if __name__ == "__main__":
    main()
