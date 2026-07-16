#!/usr/bin/env python3
"""Batch synthesis orchestrator for scaling across multiple repos.

Reads a YAML config with per-repo targets, clones each repo to an
isolated directory, and launches `swebenchify synthesize` as separate
processes with configurable concurrency.

Usage:
    python scripts/batch_synthesize.py --config batch.yaml --workdir /tmp/synth-sweep
    python scripts/batch_synthesize.py --config batch.yaml --workdir /tmp/synth-sweep --yield-only

Example batch.yaml:
    repos:
      - slug: grpc/grpc-go
        max_mutations: 150
      - slug: containers/podman
        max_mutations: 100
      - slug: kubernetes/kubernetes
        max_mutations: 100
    concurrency: 5
    target_multiplier: 25
    model: sonnet
"""
from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml


def _clone_repo(slug: str, workdir: Path) -> Path:
    """Clone a repo into workdir/{slug_safe}. Returns the clone path."""
    safe_name = slug.replace("/", "__")
    clone_path = workdir / safe_name
    if clone_path.exists():
        print(f"  {slug}: clone exists at {clone_path}, pulling latest...")
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=clone_path, capture_output=True, timeout=120,
        )
        return clone_path

    print(f"  {slug}: cloning...")
    subprocess.run(
        ["git", "clone", "--depth", "200", f"https://github.com/{slug}.git", str(clone_path)],
        check=True, timeout=600,
    )
    return clone_path


def _run_synthesis(
    slug: str,
    clone_path: Path,
    max_mutations: int,
    output_dir: Path,
    target_multiplier: int,
    model: str,
    yield_only: bool,
    max_files: int | None,
    max_functions: int | None,
) -> dict:
    """Run swebenchify synthesize on a single repo. Returns a result summary."""
    cmd = [
        "swebenchify",
        "synthesize",
        "--repo", str(clone_path),
        "--language", "go",
        "--max-mutations", str(max_mutations),
        "--output-dir", str(output_dir),
        "--model", model,
        "--target-multiplier", str(target_multiplier),
    ]
    if yield_only:
        cmd.append("--yield-only")
    if max_files is not None:
        cmd.extend(["--max-files", str(max_files)])
    if max_functions is not None:
        cmd.extend(["--max-functions", str(max_functions)])

    safe_name = slug.replace("/", "__")
    log_file = output_dir / f"{safe_name}.log"

    print(f"[START] {slug} (max_mutations={max_mutations}, multiplier={target_multiplier})")

    try:
        with open(log_file, "w") as lf:
            result = subprocess.run(
                cmd, stdout=lf, stderr=subprocess.STDOUT,
                timeout=7200,
            )

        out_file = output_dir / f"{safe_name}-synthetic-candidates.jsonl"
        count = 0
        if out_file.exists():
            with open(out_file) as f:
                count = sum(1 for line in f if line.strip())

        status = "ok" if result.returncode == 0 else f"exit={result.returncode}"
        print(f"[DONE]  {slug}: {count} instances ({status})")
        return {"slug": slug, "instances": count, "status": status, "log": str(log_file)}

    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {slug}: killed after 2h")
        return {"slug": slug, "instances": 0, "status": "timeout", "log": str(log_file)}
    except Exception as e:
        print(f"[ERROR] {slug}: {e}")
        return {"slug": slug, "instances": 0, "status": f"error: {e}", "log": str(log_file)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch synthesis across multiple Go repos")
    parser.add_argument("--config", required=True, help="YAML config with repo targets")
    parser.add_argument("--workdir", required=True, help="Working directory for clones and output")
    parser.add_argument("--yield-only", action="store_true", help="Use yield-only mode")
    parser.add_argument("--concurrency", type=int, default=None, help="Override config concurrency")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    workdir = Path(args.workdir)
    clone_dir = workdir / "clones"
    output_dir = workdir / "output"
    clone_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    repos = config["repos"]
    concurrency = args.concurrency or config.get("concurrency", 3)
    target_multiplier = config.get("target_multiplier", 25)
    model = config.get("model", "sonnet")
    max_files = config.get("max_files")
    max_functions = config.get("max_functions")

    print("=== Batch Synthesis ===")
    print(f"Repos: {len(repos)}, Concurrency: {concurrency}, Multiplier: {target_multiplier}")
    print(f"Yield-only: {args.yield_only}, Model: {model}")
    print()

    print("Cloning repos...")
    clone_paths = {}
    for repo in repos:
        slug = repo["slug"]
        try:
            clone_paths[slug] = _clone_repo(slug, clone_dir)
        except Exception as e:
            print(f"  {slug}: clone FAILED: {e}")

    print(f"\n{len(clone_paths)}/{len(repos)} repos cloned. Starting synthesis...\n")

    results = []
    with ProcessPoolExecutor(max_workers=concurrency) as executor:
        futures = {}
        for repo in repos:
            slug = repo["slug"]
            if slug not in clone_paths:
                continue
            fut = executor.submit(
                _run_synthesis,
                slug=slug,
                clone_path=clone_paths[slug],
                max_mutations=repo.get("max_mutations", 50),
                output_dir=output_dir,
                target_multiplier=target_multiplier,
                model=model,
                yield_only=args.yield_only,
                max_files=max_files,
                max_functions=max_functions,
            )
            futures[fut] = slug

        for fut in as_completed(futures):
            results.append(fut.result())

    summary_path = output_dir / "batch-summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    print("\n=== Summary ===")
    total = sum(r["instances"] for r in results)
    for r in sorted(results, key=lambda x: -x["instances"]):
        print(f"  {r['slug']}: {r['instances']} instances ({r['status']})")
    print(f"\nTotal: {total} instances across {len(results)} repos")
    print(f"Details: {summary_path}")


if __name__ == "__main__":
    main()
