"""Difficulty eval — synthesize instances, validate + eval on OpenShift, measure Haiku failure rate.

Used by the remote-factory difficulty workflow. Runs synthesis and enrichment
locally (picking up worktree code changes), then launches validation and eval
jobs on the OpenShift cluster via `oc`.

Usage:
    python3 scripts/eval_difficulty.py                    # Full eval
    python3 scripts/eval_difficulty.py --quick             # 5 instances, 1 repo
    python3 scripts/eval_difficulty.py --n-instances 20    # Custom count
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

SYNTH_MODEL = "claude-opus-4-6"
NAMESPACE = "swebenchify"
EVAL_MODEL = "claude-haiku-4-5"
IMAGE = "ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming"

EVAL_REPOS = [
    {
        "slug": "grpc/grpc-go",
        "url": "https://github.com/grpc/grpc-go.git",
        "language": "go",
    },
]

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

        cm_name = f"{component}-input-{job_slug}"
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


def wait_for_jobs(component, prefix="diff", timeout=1800):
    label = f"component={component}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = oc("get", "jobs", "-l", label, "-n", NAMESPACE, "--no-headers")
        lines = [x for x in r.stdout.strip().split("\n") if x and prefix in x]
        if not lines:
            break
        running = sum(1 for x in lines if "Running" in x)
        if running == 0:
            break
        log.info("Waiting: %d/%d %s jobs still running", running, len(lines), component)
        time.sleep(30)


def collect_annotations(component, prefix="diff"):
    r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE,
           "-o", "json", timeout=60)
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


def cleanup_jobs(component, prefix="diff"):
    r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE,
           "--no-headers", "-o", "custom-columns=NAME:.metadata.name")
    for name in r.stdout.strip().split("\n"):
        name = name.strip()
        if name and prefix in name:
            oc("delete", "job", name, "-n", NAMESPACE, "--wait=false")
            prefix_part = component.split("-")[0]
            cm_suffix = name.split(prefix_part + "-", 1)[-1] if "-" in name else name
            cm = f"{component}-input-{cm_suffix}"
            oc("delete", "configmap", cm, "-n", NAMESPACE)


# ── Main eval ────────────────────────────────────────────────────


def run_eval(n_instances=10, repos=None, round_id=None):
    repos = repos or EVAL_REPOS
    round_id = round_id or f"r{int(time.time()) % 100000}"
    prefix = f"diff-{round_id}"

    all_yields = []
    all_enriched = []
    all_valid = []

    for repo_cfg in repos:
        repo_slug = repo_cfg["slug"]
        repo_url = repo_cfg["url"]
        language = repo_cfg["language"]
        repo_path = f"/tmp/eval-difficulty-{repo_slug.replace('/', '-')}"

        # ── Step 1: Clone repo ──
        if not os.path.isdir(repo_path):
            log.info("Cloning %s", repo_slug)
            subprocess.run(["git", "clone", "--depth=1", repo_url, repo_path],
                           capture_output=True, timeout=300)

        # ── Step 2: Synthesize locally ──
        log.info("Synthesizing %d instances from %s", n_instances, repo_slug)
        repo_yields = []

        def on_candidate(candidate, metadata):
            d = candidate if isinstance(candidate, dict) else candidate.__dict__
            d["repo"] = repo_slug
            old_id = d.get("instance_id", "")
            if old_id.startswith("local__"):
                num = old_id.rsplit("-", 1)[-1] if "-" in old_id else old_id
                slug = repo_slug.replace("/", "-")
                d["instance_id"] = f"{slug}-{num}"
            repo_yields.append(d)

        try:
            result = asyncio.run(synth_mod.synthesize_repo(
                repo_path=repo_path,
                repo_slug=repo_slug,
                base_commit="HEAD",
                language=language,
                model=SYNTH_MODEL,
                max_mutations=n_instances,
                yield_only=True,
                target_multiplier=8,
                max_files=20,
                max_functions=5,
                on_candidate=on_candidate,
            ))
        except Exception as e:
            log.error("Synthesis failed: %s", e)
            continue

        # Also check the result object for candidates
        if hasattr(result, 'candidates'):
            for c in result.candidates:
                d = c if isinstance(c, dict) else (c.__dict__ if hasattr(c, '__dict__') else {})
                if d and d.get("instance_id") and d["instance_id"] not in {y.get("instance_id") for y in repo_yields}:
                    d["repo"] = repo_slug
                    repo_yields.append(d)

        all_yields.extend(repo_yields)
        log.info("Got %d yields from %s", len(repo_yields), repo_slug)

        # ── Step 3: Enrich locally ──
        log.info("Enriching %d instances", len(all_yields))
        for inst in all_yields:
            try:
                enriched = asyncio.run(synth_mod.enrich_instance(inst, repo_path, model=SYNTH_MODEL))
                if enriched:
                    all_enriched.append(enriched)
            except Exception as e:
                log.warning("Enrichment failed for %s: %s", inst.get("instance_id"), e)

        log.info("Enriched: %d/%d", len(all_enriched), len(all_yields))

    if not all_enriched:
        print(json.dumps({"score": 0.0, "details": "No enriched instances produced"}))
        return

    # ── Step 4: Validate on cluster ──
    log.info("Launching validation on cluster (%d instances)", len(all_enriched))
    val_jsonl = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for inst in all_enriched:
        val_jsonl.write(json.dumps(inst) + "\n")
    val_jsonl.close()

    launch_jobs_from_jsonl(
        val_jsonl.name, "validation",
        os.path.join(PROJECT_ROOT, "k8s/validation-job.yaml"),
        prefix=prefix,
    )
    wait_for_jobs("validation", prefix=prefix, timeout=1800)
    val_results = collect_annotations("validation", prefix=prefix)
    os.unlink(val_jsonl.name)

    valid_ids = set()
    for r in val_results:
        if r.get("status") == "valid":
            valid_ids.add(r.get("instance_id"))

    log.info("Validated: %d/%d valid", len(valid_ids), len(all_enriched))

    # ── Step 5: Prep and eval on cluster ──
    eval_instances = []
    for inst in all_enriched:
        if inst.get("instance_id") not in valid_ids:
            continue
        # Add required fields for eval
        inst["version"] = "1.0"
        inst["repo_language"] = "go"
        if isinstance(inst.get("FAIL_TO_PASS"), list):
            inst["FAIL_TO_PASS"] = json.dumps(inst["FAIL_TO_PASS"])
        if isinstance(inst.get("PASS_TO_PASS"), list):
            inst["PASS_TO_PASS"] = json.dumps(inst["PASS_TO_PASS"])
        if "hints_text" not in inst:
            inst["hints_text"] = ""
        eval_instances.append(inst)
        all_valid.append(inst)

    if not eval_instances:
        cleanup_jobs("validation", prefix=prefix)
        print(json.dumps({"score": 0.0, "details": "No valid instances to evaluate"}))
        return

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
    wait_for_jobs("eval", prefix=prefix, timeout=3600)
    eval_results = collect_annotations("eval", prefix=prefix)
    os.unlink(eval_jsonl.name)

    # ── Step 6: Compute scores ──
    n_eval = len(eval_results)
    n_resolved = sum(1 for r in eval_results if r.get("resolved"))
    haiku_failure = (n_eval - n_resolved) / n_eval if n_eval > 0 else 0.0

    # Bug category diversity
    categories = {}
    for inst in all_enriched:
        cat = inst.get("_pipeline", {}).get("bug_spec", {}).get("bug_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    n_categories = len(categories)
    diversity = min(1.0, n_categories / 5.0) if all_enriched else 0.0

    score = 0.7 * haiku_failure + 0.15 * diversity + 0.15 * 0.5  # placeholder judge evasion

    # ── Step 7: Cleanup ──
    cleanup_jobs("validation", prefix=prefix)
    cleanup_jobs("eval", prefix=prefix)

    # ── Output ──
    result = {
        "score": round(score, 4),
        "haiku_failure": round(haiku_failure, 4),
        "diversity": round(diversity, 4),
        "n_yields": len(all_yields),
        "n_enriched": len(all_enriched),
        "n_valid": len(valid_ids),
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
    parser.add_argument("--n-instances", type=int, default=10)
    parser.add_argument("--repo", type=str, default=None, help="Override repo slug")
    parser.add_argument("--role", type=str, default="generator", help="generator or discriminator")
    args = parser.parse_args()

    n = 5 if args.quick else args.n_instances
    repos = EVAL_REPOS
    if args.repo:
        repos = [r for r in EVAL_REPOS if r["slug"] == args.repo]
        if not repos:
            repos = [{"slug": args.repo, "url": f"https://github.com/{args.repo}.git", "language": "go"}]

    run_eval(n_instances=n, repos=repos)


if __name__ == "__main__":
    main()
