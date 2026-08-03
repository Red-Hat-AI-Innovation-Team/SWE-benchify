"""Evaluate SWE-Smith instances on OpenShift with Claude models.

Launches eval jobs for sampled SWE-Smith instances using their Docker images,
then collects results for comparison with SWE-benchify.

Usage:
    python3 scripts/eval_swesmith.py --input data/swesmith-sample-200.jsonl
    python3 scripts/eval_swesmith.py --input data/swesmith-sample-200.jsonl --models haiku,sonnet,opus --limit 50
    python3 scripts/eval_swesmith.py --collect-only  # Just collect results from previous run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMESPACE = "swebenchify"
MODEL_MAP = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-6",
}

log = logging.getLogger("eval_swesmith")
log.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
log.addHandler(_handler)


def oc(*args, timeout=120):
    return subprocess.run(["oc"] + list(args), capture_output=True, text=True, timeout=timeout)


def make_slug(text, max_len=30):
    return re.sub(r"[^a-z0-9-]", "-", text.lower().replace("_", "-"))[:max_len].rstrip("-")


def launch_eval(instances, models, limit=0):
    eval_yaml = os.path.join(PROJECT_ROOT, "k8s/eval-swesmith-job.yaml")

    existing = set()
    r = oc("get", "jobs", "-l", "component=eval-swesmith", "-n", NAMESPACE,
           "--no-headers", "-o", "custom-columns=NAME:.metadata.name")
    if r.returncode == 0:
        existing = set(r.stdout.strip().splitlines())

    launched = 0
    for inst in instances:
        if limit and launched >= limit:
            break

        iid = inst["instance_id"]
        image = inst.get("image_name", "")
        if not image:
            log.warning("Skipping %s: no image_name", iid)
            continue

        job_slug = make_slug(iid)

        for model in models:
            model_id = MODEL_MAP[model]
            job_name = f"eval-swesmith-{model}-{job_slug}"

            if job_name in existing:
                continue

            cm_name = f"eval-swesmith-input-{model}-{job_slug}"
            with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
                f.write(json.dumps(inst))
                tmpf = f.name
            oc("delete", "configmap", cm_name, "-n", NAMESPACE)
            oc("create", "configmap", cm_name, f"--from-file=instance.jsonl={tmpf}", "-n", NAMESPACE)
            os.unlink(tmpf)

            env = {
                **os.environ,
                "SWESMITH_IMAGE": image,
                "INSTANCE_SLUG": job_slug,
                "NAMESPACE": NAMESPACE,
                "MODEL": model,
                "MODEL_ID": model_id,
            }
            envsubst_vars = "${SWESMITH_IMAGE} ${INSTANCE_SLUG} ${NAMESPACE} ${MODEL} ${MODEL_ID}"
            r = subprocess.run(
                f"envsubst '{envsubst_vars}' < {eval_yaml}",
                shell=True, capture_output=True, text=True, env=env,
            )
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(r.stdout)
                tmp = f.name
            subprocess.run(f"oc apply -n {NAMESPACE} -f {tmp}", shell=True, capture_output=True)
            os.unlink(tmp)

        launched += 1
        log.info("Launched %d/%d: %s (%d jobs)", launched, min(limit, len(instances)) if limit else len(instances),
                 iid[:40], launched * len(models))

        # Wait for this instance's jobs to complete before launching next
        # (avoids Docker Hub rate limiting from parallel image pulls)
        deadline = time.time() + 3600
        while time.time() < deadline:
            all_done = True
            for model in models:
                job_name = f"eval-swesmith-{model}-{job_slug}"
                r = oc("get", "job", job_name, "-n", NAMESPACE, "--no-headers")
                if r.returncode != 0:
                    continue
                if "Running" in r.stdout or ("Complete" not in r.stdout and "Failed" not in r.stdout):
                    all_done = False
                    break
            if all_done:
                break
            time.sleep(30)

    log.info("Total: %d instances × %d models = %d jobs launched (serial)", launched, len(models), launched * len(models))
    return launched


def collect_results(models):
    r = oc("get", "jobs", "-l", "component=eval-swesmith", "-n", NAMESPACE, "-o", "json", timeout=180)
    if r.returncode != 0:
        log.error("Failed to get jobs: %s", r.stderr[:200])
        return {}

    data = json.loads(r.stdout)
    results = {}
    for model in models:
        model_results = []
        for job in data.get("items", []):
            name = job["metadata"]["name"]
            if not name.startswith(f"eval-swesmith-{model}-"):
                continue
            ann = job.get("metadata", {}).get("annotations", {}).get("result", "")
            if not ann:
                continue
            try:
                d = json.loads(ann)
                if d.get("model") == model:
                    model_results.append(d)
            except json.JSONDecodeError:
                continue
        results[model] = model_results

    return results


def wait_and_collect(models, poll_interval=30, timeout=7200):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = oc("get", "jobs", "-l", "component=eval-swesmith", "-n", NAMESPACE, "--no-headers")
        if r.returncode != 0:
            log.warning("Failed to check jobs, retrying...")
            time.sleep(poll_interval)
            continue

        lines = r.stdout.strip().split("\n")
        running = sum(1 for x in lines if "Running" in x)
        complete = sum(1 for x in lines if "Complete" in x)
        failed = sum(1 for x in lines if "Failed" in x)

        results = collect_results(models)
        summary = " | ".join(
            f"{m}: {sum(1 for r in results.get(m, []) if r.get('resolved'))}/{len(results.get(m, []))}"
            for m in models
        )
        log.info("eval-swesmith: %d complete, %d running, %d failed | %s",
                 complete, running, failed, summary)

        if running == 0 and (complete + failed) > 0:
            break
        time.sleep(poll_interval)

    return collect_results(models)


def main():
    parser = argparse.ArgumentParser(description="Evaluate SWE-Smith instances")
    parser.add_argument("--input", type=str, default="data/swesmith-sample-200.jsonl")
    parser.add_argument("--models", type=str, default="haiku,sonnet,opus")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--output-dir", type=str, default="data")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",")]

    if args.collect_only:
        results = collect_results(models)
    else:
        with open(args.input) as f:
            instances = [json.loads(line.strip()) for line in f if line.strip()]
        log.info("Loaded %d SWE-Smith instances", len(instances))

        launch_eval(instances, models, args.limit)
        log.info("Waiting for eval jobs to complete...")
        results = wait_and_collect(models)

    for model, model_results in results.items():
        path = os.path.join(args.output_dir, f"eval-results-swesmith-{model}.jsonl")
        with open(path, "w") as f:
            for r in model_results:
                f.write(json.dumps(r) + "\n")
        resolved = sum(1 for r in model_results if r.get("resolved"))
        n = len(model_results)
        pct = 100 * resolved / n if n else 0
        log.info("%s: %d/%d resolved (%.1f%%)", model, resolved, n, pct)


if __name__ == "__main__":
    main()
