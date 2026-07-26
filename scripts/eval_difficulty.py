"""Difficulty eval — synthesize + enrich + validate + eval on OpenShift.

Used by remote-factory via factory.md. Runs the full pipeline on the cluster
with a ConfigMap code overlay so synthesizer.py changes take effect without
rebuilding the image.

Pipeline: synthesis → enrichment → validation → eval (configurable model)
Score = 0.7 × model_failure + 0.15 × diversity + 0.15 × 0.5

Usage:
    python3 scripts/eval_difficulty.py                                # 10 instances × 6 repos, haiku
    python3 scripts/eval_difficulty.py --model sonnet                  # Use Sonnet for eval
    python3 scripts/eval_difficulty.py --model opus                    # Use Opus for eval
    python3 scripts/eval_difficulty.py --eval-only instances.jsonl     # Skip pipeline, eval only
    python3 scripts/eval_difficulty.py --eval-only instances.jsonl --model sonnet  # Re-eval with Sonnet
    python3 scripts/eval_difficulty.py --quick                         # 5 instances
    python3 scripts/eval_difficulty.py --n-instances 20                # Custom count
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
IMAGE = "ghcr.io/red-hat-ai-innovation-team/swe-benchify/swebenchify-synthesis:streaming"
SYNTHESIZER_PATH = os.path.join(PROJECT_ROOT, "src/swebenchify/synthesizer.py")
VALIDATE_SCRIPT_PATH = os.path.join(PROJECT_ROOT, "scripts/validate_and_prepare.py")

EVAL_REPOS = [
    {"slug": "containers/image", "url": "https://github.com/containers/image.git", "language": "go"},
    {"slug": "grpc/grpc-go", "url": "https://github.com/grpc/grpc-go.git", "language": "go"},
    {"slug": "openshift/router", "url": "https://github.com/openshift/router.git", "language": "go"},
    {"slug": "containers/storage", "url": "https://github.com/containers/storage.git", "language": "go"},
    {"slug": "tektoncd/pipeline", "url": "https://github.com/tektoncd/pipeline.git", "language": "go"},
    {"slug": "operator-framework/operator-registry", "url": "https://github.com/operator-framework/operator-registry.git", "language": "go"},
]

MODEL_MAP = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-6",
}

log = logging.getLogger("eval_difficulty")
log.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
log.addHandler(_handler)


# ── Cluster helpers ──────────────────────────────────────────────

def oc(*args, timeout=120):
    r = subprocess.run(["oc"] + list(args), capture_output=True, text=True, timeout=timeout)
    return r


def push_code_overlay(prefix):
    cm_name = f"synth-code-{prefix}"
    oc("delete", "configmap", cm_name, "-n", NAMESPACE)
    r = oc("create", "configmap", cm_name,
           f"--from-file=synthesizer.py={SYNTHESIZER_PATH}",
           f"--from-file=validate_and_prepare.py={VALIDATE_SCRIPT_PATH}",
           "-n", NAMESPACE)
    if r.returncode != 0:
        log.error("Failed to create code overlay: %s", r.stderr[:200])
        return None
    log.info("Pushed synthesizer.py as ConfigMap %s (%d bytes)",
             cm_name, os.path.getsize(SYNTHESIZER_PATH))
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
        "              mountPath: /app/scripts/validate_and_prepare.py\n"
        "              subPath: validate_and_prepare.py\n"
        "              readOnly: true\n"
    )
    overlay_volume = (
        f"        - name: code-overlay\n"
        f"          configMap:\n"
        f"            name: {code_cm}\n"
    )
    # Insert mount after the first volumeMounts entry
    yaml_text = yaml_text.replace(
        "          volumeMounts:\n",
        f"          volumeMounts:\n{overlay_mount}",
        1,
    )
    # Insert volume at the start of volumes list
    yaml_text = yaml_text.replace(
        "      volumes:\n",
        f"      volumes:\n{overlay_volume}",
        1,
    )
    return yaml_text


def launch_job(yaml_path, env_vars, code_cm=None, model_id=None):
    envsubst_vars = " ".join(f"${{{k}}}" for k in env_vars)
    env = {**os.environ, **env_vars}
    r = subprocess.run(
        f"envsubst '{envsubst_vars}' < {yaml_path}",
        shell=True, capture_output=True, text=True, env=env,
    )
    rendered = inject_code_overlay(r.stdout, code_cm)
    if model_id:
        rendered = rendered.replace("claude-haiku-4-5", model_id)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(rendered)
        tmp = f.name
    subprocess.run(f"oc apply -n {NAMESPACE} -f {tmp}", shell=True, capture_output=True)
    os.unlink(tmp)


def wait_for_jobs(component, prefix, timeout=1800):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE, "--no-headers")
        lines = [x for x in r.stdout.strip().split("\n") if x and prefix in x]
        if not lines:
            break
        running = sum(1 for x in lines if "Running" in x)
        complete = sum(1 for x in lines if "Complete" in x)
        failed = sum(1 for x in lines if "Failed" in x)
        if running == 0:
            break
        log.info("[%s] %d running, %d complete, %d failed", component, running, complete, failed)
        time.sleep(30)


def collect_annotations(component, prefix):
    r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE,
           "-o", "json", timeout=120)
    if r.returncode != 0:
        return []
    data = json.loads(r.stdout)
    results = []
    for job in data.get("items", []):
        name = job["metadata"]["name"]
        if prefix not in name:
            continue
        result_str = job.get("metadata", {}).get("annotations", {}).get("result", "")
        if not result_str:
            continue
        # Synthesis annotations are multi-line JSONL; enrichment/eval are single JSON
        for line in result_str.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line, strict=False))
            except json.JSONDecodeError:
                continue
    return results


def cleanup_all(prefix, code_cm=None):
    for component in ("synthesis-exp", "enrichment", "validation", "eval"):
        r = oc("get", "jobs", "-l", f"component={component}", "-n", NAMESPACE,
               "--no-headers", "-o", "custom-columns=NAME:.metadata.name")
        for name in r.stdout.strip().split("\n"):
            name = name.strip()
            if name and prefix in name:
                oc("delete", "job", name, "-n", NAMESPACE, "--wait=false")
    r = oc("get", "configmaps", "-n", NAMESPACE, "--no-headers",
           "-o", "custom-columns=NAME:.metadata.name")
    for cm in r.stdout.strip().split("\n"):
        cm = cm.strip()
        if cm and prefix in cm:
            oc("delete", "configmap", cm, "-n", NAMESPACE)
    if code_cm:
        oc("delete", "configmap", code_cm, "-n", NAMESPACE)


def make_slug(instance_id, prefix, max_len=40):
    slug = re.sub(r"[^a-z0-9-]", "-", instance_id.lower().replace("_", "-"))[:max_len].rstrip("-")
    return f"{prefix}-{slug}"


# ── Main eval ────────────────────────────────────────────────────


def _run_eval_only(eval_only_path, model, model_id, round_id):
    prefix = f"ev-{model}-{round_id}"
    eval_instances = []
    with open(eval_only_path) as f:
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
            eval_instances.append(inst)
    log.info("Eval-only: loaded %d instances from %s (model=%s)",
             len(eval_instances), eval_only_path, model)
    if not eval_instances:
        print(json.dumps({"score": 0.0, "details": "No instances in eval-only input"}))
        return

    log.info("Launching eval (%d instances, model=%s)...", len(eval_instances), model)
    eval_yaml = os.path.join(PROJECT_ROOT, "k8s/eval-job.yaml")
    for inst in eval_instances:
        job_slug = make_slug(inst["instance_id"], prefix)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(inst) + "\n")
            tmpf = f.name
        oc("delete", "configmap", f"eval-input-{job_slug}", "-n", NAMESPACE)
        oc("create", "configmap", f"eval-input-{job_slug}",
           f"--from-file=instance.jsonl={tmpf}", "-n", NAMESPACE)
        os.unlink(tmpf)
        launch_job(eval_yaml, {
            "REPO_FULL": inst["repo"],
            "INSTANCE_SLUG": job_slug,
            "IMAGE": IMAGE,
            "NAMESPACE": NAMESPACE,
            "LANGUAGE": "go",
            "MODEL": model,
        }, model_id=model_id)

    wait_for_jobs("eval", prefix, timeout=3600)
    eval_results = collect_annotations("eval", prefix)
    log.info("Eval: %d/%d returned results", len(eval_results), len(eval_instances))

    n_eval = len(eval_results)
    n_resolved = sum(1 for r in eval_results if r.get("resolved"))
    model_failure = (n_eval - n_resolved) / n_eval if n_eval > 0 else 0.0

    categories = {}
    for inst in eval_instances:
        cat = inst.get("_pipeline", {}).get("bug_spec", {}).get("bug_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    diversity = min(1.0, len(categories) / 5.0)

    score = 0.7 * model_failure + 0.15 * diversity + 0.15 * 0.5

    cleanup_all(prefix)

    result = {
        "score": round(score, 4),
        "model": model,
        "model_failure": round(model_failure, 4),
        "diversity": round(diversity, 4),
        "n_yields": 0,
        "n_enriched": 0,
        "n_valid": len(eval_instances),
        "n_eval": n_eval,
        "n_resolved": n_resolved,
        "categories": categories,
        "eval_only_source": eval_only_path,
        "per_instance": [
            {"instance_id": r.get("instance_id"), "resolved": r.get("resolved"),
             "patch_lines": len(r.get("agent_patch", "").strip().splitlines())}
            for r in eval_results
        ],
    }
    print(json.dumps(result))
    log.info("Score=%.4f model_failure=%.4f diversity=%.4f (%d/%d resolved, model=%s)",
             score, model_failure, diversity, n_resolved, n_eval, model)

    results_dir = os.path.join(PROJECT_ROOT, ".factory", "reviews")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "difficulty-eval-latest.json"), "w") as f:
        json.dump(result, f, indent=2)


def run_eval(n_instances=10, seed=None, repos=None, model="haiku", eval_only=None):
    repos = repos or EVAL_REPOS
    round_id = f"r{int(time.time()) % 100000}"
    model_id = MODEL_MAP[model]

    if eval_only:
        _run_eval_only(eval_only, model, model_id, round_id)
        return

    prefix = f"exp-{round_id}"

    # ── Step 1: Push code overlay ──
    code_cm = push_code_overlay(prefix)

    # ── Step 2: Synthesis on cluster (parallel — 1 mutation per job) ──
    synth_yaml = os.path.join(PROJECT_ROOT, "k8s/synthesis-experiment-job.yaml")
    for repo_cfg in repos:
        repo_slug = repo_cfg["slug"]
        repo_slug_k8s = repo_slug.replace("/", "-")
        log.info("Launching %d parallel synthesis jobs for %s...", n_instances, repo_slug)
        for j in range(n_instances):
            launch_job(synth_yaml, {
                "REPO_FULL": repo_slug,
                "REPO_SLUG": f"{prefix}-{repo_slug_k8s}-{j}",
                "IMAGE": IMAGE,
                "NAMESPACE": NAMESPACE,
                "MAX_MUTATIONS": "1",
            }, code_cm)

    wait_for_jobs("synthesis-exp", prefix, timeout=3600)
    synth_results = collect_annotations("synthesis-exp", prefix)

    # Fix repo/instance_id fields (synthesis outputs local/repo)
    for d in synth_results:
        old_repo = d.get("repo", "")
        if old_repo == "local/repo" or "local" in old_repo:
            d["repo"] = repos[0]["slug"]
        old_id = d.get("instance_id", "")
        if old_id.startswith("local__"):
            num = old_id.rsplit("-", 1)[-1] if "-" in old_id else old_id
            d["instance_id"] = f"{d['repo'].replace('/', '-')}-{num}"

    log.info("Synthesis: %d yields", len(synth_results))
    if not synth_results:
        cleanup_all(prefix, code_cm)
        print(json.dumps({"score": 0.0, "details": "No synthesis yields"}))
        return

    # ── Step 3: Enrichment on cluster ──
    log.info("Launching enrichment (%d instances)...", len(synth_results))
    enrich_yaml = os.path.join(PROJECT_ROOT, "k8s/enrichment-job.yaml")
    for inst in synth_results:
        job_slug = make_slug(inst["instance_id"], prefix)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(inst) + "\n")
            tmpf = f.name
        oc("delete", "configmap", f"enrich-input-{job_slug}", "-n", NAMESPACE)
        oc("create", "configmap", f"enrich-input-{job_slug}",
           f"--from-file=instances.jsonl={tmpf}", "-n", NAMESPACE)
        os.unlink(tmpf)
        launch_job(enrich_yaml, {
            "REPO_FULL": inst["repo"],
            "INSTANCE_SLUG": job_slug,
            "IMAGE": IMAGE,
            "NAMESPACE": NAMESPACE,
        }, code_cm)

    wait_for_jobs("enrichment", prefix, timeout=1800)
    enrich_results = collect_annotations("enrichment", prefix)
    log.info("Enrichment: %d/%d returned results", len(enrich_results), len(synth_results))
    if not enrich_results:
        cleanup_all(prefix, code_cm)
        print(json.dumps({"score": 0.0, "details": "No enrichment results"}))
        return

    # ── Step 4: Validation on cluster ──
    log.info("Launching validation (%d instances)...", len(enrich_results))
    val_yaml = os.path.join(PROJECT_ROOT, "k8s/validation-job.yaml")
    for inst in enrich_results:
        job_slug = make_slug(inst.get("instance_id", ""), prefix)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(inst) + "\n")
            tmpf = f.name
        oc("delete", "configmap", f"validate-input-{job_slug}", "-n", NAMESPACE)
        oc("create", "configmap", f"validate-input-{job_slug}",
           f"--from-file=instance.jsonl={tmpf}", "-n", NAMESPACE)
        os.unlink(tmpf)
        launch_job(val_yaml, {
            "REPO_FULL": inst.get("repo", ""),
            "INSTANCE_SLUG": job_slug,
            "IMAGE": IMAGE,
            "NAMESPACE": NAMESPACE,
            "LANGUAGE": "go",
        }, code_cm)

    wait_for_jobs("validation", prefix, timeout=1800)
    val_results = collect_annotations("validation", prefix)
    valid_ids = {r["instance_id"] for r in val_results if r.get("status") == "valid"}
    val_by_id = {}
    for vr in val_results:
        vid = vr.get("instance_id")
        if vid and vr.get("status") == "valid":
            val_by_id[vid] = vr
    log.info("Validation: %d/%d valid", len(valid_ids), len(enrich_results))

    # ── Step 5: Eval on cluster ──
    eval_instances = []
    for inst in enrich_results:
        iid = inst.get("instance_id")
        if iid not in valid_ids:
            continue
        vr = val_by_id.get(iid, {})
        inst["FAIL_TO_PASS"] = vr.get("FAIL_TO_PASS", [])
        inst["PASS_TO_PASS"] = vr.get("PASS_TO_PASS", [])
        inst["version"] = "1.0"
        inst["repo_language"] = "go"
        if isinstance(inst.get("FAIL_TO_PASS"), list):
            inst["FAIL_TO_PASS"] = json.dumps(inst["FAIL_TO_PASS"])
        if isinstance(inst.get("PASS_TO_PASS"), list):
            inst["PASS_TO_PASS"] = json.dumps(inst["PASS_TO_PASS"])
        if "hints_text" not in inst:
            inst["hints_text"] = ""
        eval_instances.append(inst)

    if not eval_instances:
        cleanup_all(prefix, code_cm)
        print(json.dumps({"score": 0.0, "details": f"No valid instances (0/{len(enrich_results)})"}))
        return

    results_dir = os.path.join(PROJECT_ROOT, ".factory", "reviews")
    os.makedirs(results_dir, exist_ok=True)
    instances_path = os.path.join(results_dir, f"validated-instances-{round_id}.jsonl")
    with open(instances_path, "w") as f:
        for inst in eval_instances:
            f.write(json.dumps(inst) + "\n")
    log.info("Saved %d validated instances to %s (reuse with --eval-only)",
             len(eval_instances), instances_path)

    log.info("Launching eval (%d valid instances, model=%s)...", len(eval_instances), model)
    eval_yaml = os.path.join(PROJECT_ROOT, "k8s/eval-job.yaml")
    for inst in eval_instances:
        job_slug = make_slug(inst["instance_id"], prefix)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(inst) + "\n")
            tmpf = f.name
        oc("delete", "configmap", f"eval-input-{job_slug}", "-n", NAMESPACE)
        oc("create", "configmap", f"eval-input-{job_slug}",
           f"--from-file=instance.jsonl={tmpf}", "-n", NAMESPACE)
        os.unlink(tmpf)
        launch_job(eval_yaml, {
            "REPO_FULL": inst["repo"],
            "INSTANCE_SLUG": job_slug,
            "IMAGE": IMAGE,
            "NAMESPACE": NAMESPACE,
            "LANGUAGE": "go",
            "MODEL": model,
        }, model_id=model_id)

    wait_for_jobs("eval", prefix, timeout=3600)
    eval_results = collect_annotations("eval", prefix)
    log.info("Eval: %d/%d returned results", len(eval_results), len(eval_instances))

    # ── Step 6: Compute scores ──
    n_eval = len(eval_results)
    n_resolved = sum(1 for r in eval_results if r.get("resolved"))
    model_failure = (n_eval - n_resolved) / n_eval if n_eval > 0 else 0.0

    categories = {}
    for inst in enrich_results:
        cat = inst.get("_pipeline", {}).get("bug_spec", {}).get("bug_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    diversity = min(1.0, len(categories) / 5.0) if enrich_results else 0.0

    score = 0.7 * model_failure + 0.15 * diversity + 0.15 * 0.5

    # ── Step 7: Cleanup ──
    cleanup_all(prefix, code_cm)

    result = {
        "score": round(score, 4),
        "model": model,
        "model_failure": round(model_failure, 4),
        "diversity": round(diversity, 4),
        "n_yields": len(synth_results),
        "n_enriched": len(enrich_results),
        "n_valid": len(valid_ids),
        "n_eval": n_eval,
        "n_resolved": n_resolved,
        "categories": categories,
        "per_instance": [
            {"instance_id": r.get("instance_id"), "resolved": r.get("resolved"),
             "patch_lines": len(r.get("agent_patch", "").strip().splitlines())}
            for r in eval_results
        ],
    }
    print(json.dumps(result))
    log.info("Score=%.4f model_failure=%.4f diversity=%.4f (%d/%d resolved, model=%s)",
             score, model_failure, diversity, n_resolved, n_eval, model)

    with open(os.path.join(results_dir, "difficulty-eval-latest.json"), "w") as f:
        json.dump(result, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Difficulty eval for remote-factory")
    parser.add_argument("--quick", action="store_true", help="Quick mode (5 instances)")
    parser.add_argument("--n-instances", type=int, default=10)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--repo", type=str, default=None)
    parser.add_argument("--role", type=str, default="generator")
    parser.add_argument("--model", type=str, default="haiku",
                        choices=list(MODEL_MAP.keys()),
                        help="Claude model for eval (default: haiku)")
    parser.add_argument("--eval-only", type=str, default=None, metavar="JSONL_FILE",
                        help="Skip synthesis/enrichment/validation; eval from a JSONL file of validated instances")
    args = parser.parse_args()

    n = 5 if args.quick else args.n_instances
    repos = EVAL_REPOS
    if args.repo:
        repos = [{"slug": args.repo, "url": f"https://github.com/{args.repo}.git", "language": "go"}]

    run_eval(n_instances=n, seed=args.seed, repos=repos, model=args.model, eval_only=args.eval_only)


if __name__ == "__main__":
    main()
