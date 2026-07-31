"""Streaming pipeline: synthesis → enrichment → validation → eval.

Unlike run_scaled_pipeline.sh which runs stages sequentially, this script
pipelines all stages — enrichment jobs launch as soon as synthesis results
arrive, validation launches as enrichment completes, etc. This dramatically
reduces wall-clock time since stages overlap.

Usage:
    python3 scripts/run_streaming_pipeline.py                     # Full pipeline
    python3 scripts/run_streaming_pipeline.py --jobs-per-repo 50  # Smaller run
    python3 scripts/run_streaming_pipeline.py --eval-only FILE    # Skip to eval
    python3 scripts/run_streaming_pipeline.py --models haiku,sonnet
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
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMESPACE = "swebenchify"
IMAGE = "ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming"
SYNTHESIZER_PATH = os.path.join(PROJECT_ROOT, "src/swebenchify/synthesizer.py")
CLI_PATH = os.path.join(PROJECT_ROOT, "src/swebenchify/cli.py")
VALIDATE_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "scripts/validate_and_prepare.py")

REPOS = [
    "argoproj/argo-cd", "containers/image", "containers/podman",
    "containers/storage", "coreos/go-oidc", "grpc/grpc-go",
    "kubernetes/kubernetes", "moby/moby", "open-telemetry/opentelemetry-go",
    "openshift/cluster-version-operator", "openshift/installer",
    "openshift/origin", "openshift/router",
    "operator-framework/operator-lifecycle-manager",
    "prometheus/prometheus", "rook/rook", "stolostron/hypershift",
    "tektoncd/pipeline", "thanos-io/thanos",
    "operator-framework/operator-registry", "cri-o/cri-o", "openshift/oc",
]

MODEL_MAP = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-6",
}

SLUG_TO_REPO = {r.replace("/", "-"): r for r in REPOS}

log = logging.getLogger("streaming_pipeline")
log.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
log.addHandler(_handler)


# ── Cluster helpers (shared with eval_difficulty.py) ──────────────

def oc(*args, timeout=120):
    return subprocess.run(["oc"] + list(args), capture_output=True, text=True, timeout=timeout)


def push_code_overlay(prefix):
    cm_name = f"synth-code-{prefix}"
    oc("delete", "configmap", cm_name, "-n", NAMESPACE)
    r = oc("create", "configmap", cm_name,
           f"--from-file=synthesizer.py={SYNTHESIZER_PATH}",
           f"--from-file=cli.py={CLI_PATH}",
           f"--from-file=validate_and_prepare.py={VALIDATE_SCRIPT_PATH}",
           "-n", NAMESPACE)
    if r.returncode != 0:
        log.error("Code overlay failed: %s", r.stderr[:200])
        return None
    return cm_name


def inject_code_overlay(yaml_text, code_cm):
    if not code_cm:
        return yaml_text
    overlay_mount = (
        "            - name: code-overlay\n"
        "              mountPath: /app/src/swebenchify/synthesizer.py\n"
        "              subPath: synthesizer.py\n"
        "              readOnly: true\n"
        "            - name: code-overlay\n"
        "              mountPath: /app/src/swebenchify/cli.py\n"
        "              subPath: cli.py\n"
        "              readOnly: true\n"
        "            - name: code-overlay\n"
        "              mountPath: /app/scripts/validate_and_prepare.py\n"
        "              subPath: validate_and_prepare.py\n"
        "              readOnly: true\n"
    )
    overlay_volume = (
        f"        - name: code-overlay\n"
        f"          configMap:\n"
        f"            name: {code_cm}\n"
    )
    yaml_text = yaml_text.replace("          volumeMounts:\n",
                                  f"          volumeMounts:\n{overlay_mount}", 1)
    yaml_text = yaml_text.replace("      volumes:\n",
                                  f"      volumes:\n{overlay_volume}", 1)
    return yaml_text


def launch_job(yaml_path, env_vars, code_cm=None):
    envsubst_vars = " ".join(f"${{{k}}}" for k in env_vars)
    env = {**os.environ, **env_vars}
    r = subprocess.run(f"envsubst '{envsubst_vars}' < {yaml_path}",
                       shell=True, capture_output=True, text=True, env=env)
    rendered = inject_code_overlay(r.stdout, code_cm)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(rendered)
        tmp = f.name
    subprocess.run(f"oc apply -n {NAMESPACE} -f {tmp}", shell=True, capture_output=True)
    os.unlink(tmp)


def make_slug(text, max_len=50):
    return re.sub(r"[^a-z0-9-]", "-", text.lower().replace("_", "-"))[:max_len].rstrip("-")


def get_job_results(component, prefix=None):
    """Get results from completed jobs via annotations, falling back to logs."""
    r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE, "-o", "json", timeout=120)
    if r.returncode != 0:
        return {}
    data = json.loads(r.stdout)
    results = {}
    for job in data.get("items", []):
        name = job["metadata"]["name"]
        if prefix and prefix not in name:
            continue
        conditions = job.get("status", {}).get("conditions", [])
        is_done = any(c.get("type") in ("Complete", "Failed") for c in conditions)
        if not is_done:
            continue
        ann = job.get("metadata", {}).get("annotations", {}).get("result", "")
        if not ann:
            # Fallback: read from logs
            lr = oc("logs", f"job/{name}", "-n", NAMESPACE, timeout=30)
            if lr.returncode == 0 and "=== RESULTS ===" in lr.stdout:
                log_results = lr.stdout.split("=== RESULTS ===", 1)[1]
                # Also check for RESULT: prefix (validation format)
                for line in lr.stdout.splitlines():
                    if line.startswith("RESULT: "):
                        ann = line[8:]
                        break
                if not ann:
                    json_lines = [x for x in log_results.strip().splitlines() if x.strip().startswith("{")]
                    if json_lines:
                        ann = "\n".join(json_lines)
        results[name] = ann
    return results


def count_jobs(component, prefix=None):
    r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE, "--no-headers")
    if r.returncode != 0:
        return 0, 0, 0
    lines = r.stdout.strip().split("\n")
    if prefix:
        lines = [x for x in lines if prefix in x]
    running = sum(1 for x in lines if "Running" in x)
    complete = sum(1 for x in lines if "Complete" in x)
    failed = sum(1 for x in lines if "Failed" in x)
    return complete, running, failed


def fix_repo_field(instance, job_name):
    """Fix repo and instance_id fields from synthesis output."""
    repo = instance.get("repo", "")
    if "local" not in repo and "/" in repo and "/clones/" not in repo:
        return instance

    for slug, full_repo in sorted(SLUG_TO_REPO.items(), key=lambda x: -len(x[0])):
        if slug in job_name:
            instance["repo"] = full_repo
            break
    else:
        return instance

    old_id = instance.get("instance_id", "")
    if old_id.startswith("local__"):
        num = old_id.rsplit("-", 1)[-1] if "-" in old_id else old_id
        instance["instance_id"] = f"{instance['repo'].replace('/', '-')}-{num}"
    return instance


def create_configmap(name, key, data_str):
    oc("delete", "configmap", name, "-n", NAMESPACE)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(data_str)
        tmpf = f.name
    r = oc("create", "configmap", name, f"--from-file={key}={tmpf}", "-n", NAMESPACE)
    os.unlink(tmpf)
    return r.returncode == 0


# ── Pipeline stages ──────────────────────────────────────────────


def launch_synthesis(prefix, code_cm, jobs_per_repo, batch_size=500, launch_done=None):
    """Launch synthesis jobs in batches. Sets launch_done event when finished."""
    synth_yaml = os.path.join(PROJECT_ROOT, "k8s/synthesis-experiment-job.yaml")
    launched = 0
    total = jobs_per_repo * len(REPOS)
    for repo in REPOS:
        repo_slug = repo.replace("/", "-")
        for j in range(jobs_per_repo):
            job_slug = f"{repo_slug}-{j}"
            launch_job(synth_yaml, {
                "REPO_FULL": repo,
                "REPO_SLUG": f"{prefix}-{job_slug}",
                "IMAGE": IMAGE,
                "NAMESPACE": NAMESPACE,
                "MAX_MUTATIONS": "1",
            }, code_cm)
            launched += 1

            if launched % batch_size == 0:
                log.info("Batch %d: %d/%d launched, waiting for cluster...",
                         launched // batch_size, launched, total)
                while True:
                    _, running, _ = count_jobs("synthesis-exp", prefix)
                    if running < batch_size // 2:
                        break
                    time.sleep(30)

        if launched % 500 == 0:
            log.info("  %s: %d/%d total launched", repo, launched, total)

    log.info("Synthesis: all %d jobs launched", launched)
    if launch_done:
        launch_done.set()


def poll_and_stream(prefix, code_cm, models, output_dir, poll_interval=30, launch_done=None):
    """Main streaming loop: poll for completions and launch next-stage jobs."""

    synth_processed = set()
    enrich_processed = set()
    valid_processed = set()
    eval_processed = {m: set() for m in models}

    enriched_instances = {}
    valid_instances = {}
    eval_results = {m: [] for m in models}

    eval_yaml = os.path.join(PROJECT_ROOT, "k8s/eval-job.yaml")
    enrich_yaml = os.path.join(PROJECT_ROOT, "k8s/enrichment-job.yaml")
    val_yaml = os.path.join(PROJECT_ROOT, "k8s/validation-job.yaml")

    while True:
        # ── Harvest synthesis completions → launch enrichment ──
        synth_anns = get_job_results("synthesis-exp", prefix)
        new_synth = 0
        for job_name, ann in synth_anns.items():
            if job_name in synth_processed or not ann:
                synth_processed.add(job_name)
                continue
            synth_processed.add(job_name)

            for line in ann.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    inst = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                inst = fix_repo_field(inst, job_name)
                iid = inst.get("instance_id", "")
                if not iid or not inst.get("repo"):
                    continue

                job_slug = make_slug(iid)
                if not create_configmap(f"enrich-input-{job_slug}", "instances.jsonl", json.dumps(inst) + "\n"):
                    continue
                launch_job(enrich_yaml, {
                    "REPO_FULL": inst["repo"],
                    "INSTANCE_SLUG": job_slug,
                    "IMAGE": IMAGE,
                    "NAMESPACE": NAMESPACE,
                    "SKIP_SCREENING": "1",
                }, code_cm)
                new_synth += 1

        if new_synth:
            log.info("Synthesis → Enrichment: launched %d new enrichment jobs", new_synth)

        # ── Harvest enrichment completions → launch validation ──
        enrich_anns = get_job_results("enrichment")
        new_enrich = 0
        for job_name, ann in enrich_anns.items():
            if job_name in enrich_processed or not ann:
                enrich_processed.add(job_name)
                continue
            enrich_processed.add(job_name)

            for line in ann.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    inst = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                iid = inst.get("instance_id", "")
                if not iid:
                    continue
                enriched_instances[iid] = inst

                job_slug = make_slug(iid)
                if not create_configmap(f"validate-input-{job_slug}", "instance.jsonl", json.dumps(inst)):
                    continue
                launch_job(val_yaml, {
                    "REPO_FULL": inst.get("repo", ""),
                    "INSTANCE_SLUG": job_slug,
                    "IMAGE": IMAGE,
                    "NAMESPACE": NAMESPACE,
                    "LANGUAGE": "go",
                })
                new_enrich += 1

        if new_enrich:
            log.info("Enrichment → Validation: launched %d new validation jobs", new_enrich)

        # ── Harvest validation completions → launch eval ──
        valid_anns = get_job_results("validation")
        new_valid = 0
        for job_name, ann in valid_anns.items():
            if job_name in valid_processed or not ann:
                valid_processed.add(job_name)
                continue
            valid_processed.add(job_name)

            try:
                vr = json.loads(ann, strict=False)
            except json.JSONDecodeError:
                continue

            if vr.get("status") != "valid":
                continue

            iid = vr.get("instance_id", "")
            if iid not in enriched_instances:
                continue

            inst = enriched_instances[iid].copy()
            inst["FAIL_TO_PASS"] = json.dumps(vr.get("FAIL_TO_PASS", []))
            inst["PASS_TO_PASS"] = json.dumps(vr.get("PASS_TO_PASS", []))
            inst.setdefault("version", "1.0")
            inst.setdefault("repo_language", "go")
            inst.setdefault("hints_text", "")
            valid_instances[iid] = inst
            new_valid += 1

            # Launch eval for all models
            for model in models:
                model_id = MODEL_MAP[model]
                job_slug = make_slug(iid)
                cm_name = f"eval-input-{model}-{job_slug}"
                if not create_configmap(cm_name, "instance.jsonl", json.dumps(inst)):
                    continue
                launch_job(eval_yaml, {
                    "REPO_FULL": inst.get("repo", ""),
                    "INSTANCE_SLUG": job_slug,
                    "IMAGE": IMAGE,
                    "NAMESPACE": NAMESPACE,
                    "MODEL": model,
                    "MODEL_ID": model_id,
                })

        if new_valid:
            log.info("Validation → Eval: launched eval for %d instances × %d models", new_valid, len(models))

        # ── Harvest eval completions ──
        for model in models:
            eval_anns = get_job_results("eval")
            for job_name, ann in eval_anns.items():
                if not job_name.startswith(f"eval-{model}-"):
                    continue
                if job_name in eval_processed[model] or not ann:
                    eval_processed[model].add(job_name)
                    continue
                eval_processed[model].add(job_name)

                try:
                    result = json.loads(ann, strict=False)
                    if result.get("model") == model:
                        eval_results[model].append(result)
                except json.JSONDecodeError:
                    continue

        # ── Status report ──
        try:
            s_c, s_r, s_f = count_jobs("synthesis-exp", prefix)
            e_c, e_r, e_f = count_jobs("enrichment")
            v_c, v_r, v_f = count_jobs("validation")
            ev_c, ev_r, ev_f = count_jobs("eval")
        except Exception:
            log.warning("Failed to get job counts (auth expired?), saving progress...")
            write_results(valid_instances, eval_results, output_dir, f"checkpoint-{int(time.time())}")
            time.sleep(poll_interval * 4)
            continue

        eval_summary = " | ".join(
            f"{m}: {sum(1 for r in eval_results[m] if r.get('resolved'))}/{len(eval_results[m])}"
            for m in models
        )

        log.info(
            "synth=%d/%d/%d | enrich=%d/%d/%d | valid=%d/%d/%d | eval=%d/%d/%d | results: %s",
            s_c, s_r, s_f, e_c, e_r, e_f, v_c, v_r, v_f, ev_c, ev_r, ev_f,
            eval_summary,
        )

        # Save checkpoint periodically
        total_eval = sum(len(v) for v in eval_results.values())
        if total_eval > 0 and total_eval % 20 < len(models):
            write_results(valid_instances, eval_results, output_dir, "latest")

        # ── Check if everything is done ──
        synth_launched = launch_done is None or launch_done.is_set()
        all_synth_done = synth_launched and s_r == 0 and (s_c + s_f) > 0
        all_enrich_done = e_r == 0 and all_synth_done and len(synth_processed) >= (s_c + s_f)
        all_valid_done = v_r == 0 and all_enrich_done and len(enrich_processed) >= (e_c + e_f)
        all_eval_done = ev_r == 0 and all_valid_done and len(valid_processed) >= (v_c + v_f)

        if all_eval_done:
            log.info("All stages complete!")
            break

        time.sleep(poll_interval)

    return valid_instances, eval_results


def write_results(valid_instances, eval_results, output_dir, timestamp):
    """Write final output files and print report."""
    os.makedirs(output_dir, exist_ok=True)

    eval_ready_path = os.path.join(output_dir, f"eval-ready-{timestamp}.jsonl")
    with open(eval_ready_path, "w") as f:
        for inst in valid_instances.values():
            f.write(json.dumps(inst) + "\n")
    log.info("Wrote %d eval-ready instances to %s", len(valid_instances), eval_ready_path)

    for model, results in eval_results.items():
        path = os.path.join(output_dir, f"eval-results-{model}-{timestamp}.jsonl")
        with open(path, "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
        resolved = sum(1 for r in results if r.get("resolved"))
        n = len(results)
        pct = 100 * resolved / n if n else 0
        log.info("%s: %d/%d resolved (%.1f%%)", model, resolved, n, pct)


def main():
    parser = argparse.ArgumentParser(description="Streaming synthesis pipeline")
    parser.add_argument("--jobs-per-repo", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--models", type=str, default="haiku,sonnet,opus")
    parser.add_argument("--eval-only", type=str, help="Skip to eval with a JSONL file of validated instances")
    parser.add_argument("--poll-interval", type=int, default=30)
    parser.add_argument("--output-dir", type=str, default="data")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    prefix = f"s-{int(time.time()) % 100000}"

    log.info("Streaming pipeline: %d repos × %d jobs = %d total, models=%s",
             len(REPOS), args.jobs_per_repo, len(REPOS) * args.jobs_per_repo, models)

    if args.eval_only:
        # Load validated instances and launch eval directly
        valid_instances = {}
        with open(args.eval_only) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                inst = json.loads(line)
                if isinstance(inst.get("FAIL_TO_PASS"), list):
                    inst["FAIL_TO_PASS"] = json.dumps(inst["FAIL_TO_PASS"])
                if isinstance(inst.get("PASS_TO_PASS"), list):
                    inst["PASS_TO_PASS"] = json.dumps(inst["PASS_TO_PASS"])
                inst.setdefault("hints_text", "")
                inst.setdefault("version", "1.0")
                inst.setdefault("repo_language", "go")
                valid_instances[inst["instance_id"]] = inst

        log.info("Eval-only: %d instances from %s", len(valid_instances), args.eval_only)
        eval_yaml = os.path.join(PROJECT_ROOT, "k8s/eval-job.yaml")
        for inst in valid_instances.values():
            for model in models:
                job_slug = make_slug(inst["instance_id"])
                cm_name = f"eval-input-{model}-{job_slug}"
                create_configmap(cm_name, "instance.jsonl", json.dumps(inst))
                launch_job(eval_yaml, {
                    "REPO_FULL": inst.get("repo", ""),
                    "INSTANCE_SLUG": job_slug,
                    "IMAGE": IMAGE,
                    "NAMESPACE": NAMESPACE,
                    "MODEL": model,
                    "MODEL_ID": MODEL_MAP[model],
                })

        log.info("Launched %d eval jobs, waiting...", len(valid_instances) * len(models))
        eval_results = {m: [] for m in models}
        eval_processed = {m: set() for m in models}

        while True:
            eval_anns = get_job_results("eval")
            for model in models:
                for job_name, ann in eval_anns.items():
                    if not job_name.startswith(f"eval-{model}-") or job_name in eval_processed[model] or not ann:
                        eval_processed[model].add(job_name)
                        continue
                    eval_processed[model].add(job_name)
                    try:
                        result = json.loads(ann, strict=False)
                        if result.get("model") == model:
                            eval_results[model].append(result)
                    except json.JSONDecodeError:
                        continue

            ev_c, ev_r, ev_f = count_jobs("eval")
            summary = " | ".join(f"{m}: {sum(1 for r in eval_results[m] if r.get('resolved'))}/{len(eval_results[m])}" for m in models)
            log.info("eval=%d/%d/%d | %s", ev_c, ev_r, ev_f, summary)
            if ev_r == 0 and (ev_c + ev_f) > 0:
                break
            time.sleep(args.poll_interval)

        write_results(valid_instances, eval_results, args.output_dir, timestamp)
        return

    # Full pipeline
    code_cm = push_code_overlay(prefix)
    log.info("Code overlay: %s", code_cm)

    launch_done = threading.Event()
    launch_thread = threading.Thread(
        target=launch_synthesis,
        args=(prefix, code_cm, args.jobs_per_repo, args.batch_size, launch_done),
        daemon=True,
    )
    log.info("Launching synthesis in background, streaming poll loop starting...")
    launch_thread.start()

    # Give first batch a head start before polling
    time.sleep(60)

    valid_instances, eval_results = poll_and_stream(
        prefix, code_cm, models, args.output_dir, args.poll_interval, launch_done,
    )

    write_results(valid_instances, eval_results, args.output_dir, timestamp)

    # Print final report
    subprocess.run([
        sys.executable, os.path.join(PROJECT_ROOT, "scripts/eval_report.py"),
        "--files",
        *[os.path.join(args.output_dir, f"eval-results-{m}-{timestamp}.jsonl") for m in models],
    ])


if __name__ == "__main__":
    main()
