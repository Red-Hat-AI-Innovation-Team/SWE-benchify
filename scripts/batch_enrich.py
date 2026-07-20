#!/usr/bin/env python3
"""Batch enrichment orchestrator for yield-only instances.

Scans a directory for yield-only JSONL files, maps each to its repo clone,
and runs `swebenchify enrich` in parallel across repos.

Usage:
    python scripts/batch_enrich.py \
        --input-dir data/yield-sweep-22/output \
        --clone-dir data/yield-sweep-22/clones \
        --output-dir data/yield-sweep-22/enriched

    # Single repo test:
    python scripts/batch_enrich.py \
        --input-dir data/yield-sweep-22/output \
        --clone-dir data/yield-sweep-22/clones \
        --output-dir data/yield-sweep-22/enriched \
        --repo argoproj__argo-cd
"""
from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def _find_jsonl_files(input_dir: Path, clone_dir: Path, prefix: str) -> list[dict]:
    """Discover JSONL files and map them to repo clones.

    Returns a list of dicts with keys: slug, jsonl_path, clone_path, count.
    """
    entries = []
    for f in sorted(input_dir.glob("*-synthetic-candidates.jsonl")):
        stem = f.name.removesuffix("-synthetic-candidates.jsonl")
        # Strip the workdir prefix that the synthesizer encodes in the name
        # e.g. "data__yield-sweep-22__clones__argoproj__argo-cd" -> "argoproj__argo-cd"
        if prefix and stem.startswith(prefix):
            slug = stem[len(prefix):]
        else:
            slug = stem

        clone_path = clone_dir / slug
        if not clone_path.is_dir():
            continue

        count = sum(1 for line in open(f) if line.strip())
        entries.append({
            "slug": slug,
            "jsonl_path": f,
            "clone_path": clone_path,
            "count": count,
        })
    return entries


def _run_enrich(
    slug: str,
    jsonl_path: Path,
    clone_path: Path,
    output_dir: Path,
    model: str,
) -> dict:
    """Run swebenchify enrich on a single repo's instances."""
    output_file = output_dir / f"{slug}-enriched.jsonl"
    log_file = output_dir / f"{slug}.log"

    cmd = [
        "swebenchify", "enrich",
        "--input", str(jsonl_path),
        "--repo", str(clone_path),
        "--output", str(output_file),
        "--model", model,
    ]

    input_count = sum(1 for line in open(jsonl_path) if line.strip())
    print(f"[START] {slug} ({input_count} instances)")

    try:
        with open(log_file, "w") as lf:
            result = subprocess.run(
                cmd, stdout=lf, stderr=subprocess.STDOUT,
                timeout=14400,
            )

        enriched_count = 0
        if output_file.exists():
            enriched_count = sum(1 for line in open(output_file) if line.strip())

        status = "ok" if result.returncode == 0 else f"exit={result.returncode}"
        rate = f"{enriched_count / input_count * 100:.0f}%" if input_count else "n/a"
        print(f"[DONE]  {slug}: {enriched_count}/{input_count} enriched ({rate}, {status})")
        return {
            "slug": slug,
            "input": input_count,
            "enriched": enriched_count,
            "status": status,
            "log": str(log_file),
        }

    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {slug}: killed after 4h")
        return {"slug": slug, "input": input_count, "enriched": 0, "status": "timeout", "log": str(log_file)}
    except Exception as e:
        print(f"[ERROR] {slug}: {e}")
        return {"slug": slug, "input": input_count, "enriched": 0, "status": f"error: {e}", "log": str(log_file)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch enrichment of yield-only instances")
    parser.add_argument("--input-dir", required=True, help="Directory containing yield-only JSONL files")
    parser.add_argument("--clone-dir", required=True, help="Directory containing repo clones")
    parser.add_argument("--output-dir", required=True, help="Output directory for enriched JSONL files")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of parallel enrichment workers")
    parser.add_argument("--model", default="sonnet", help="Claude model for enrichment (default: sonnet)")
    parser.add_argument("--repo", default=None, help="Only enrich a single repo (slug like argoproj__argo-cd)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    clone_dir = Path(args.clone_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detect the common prefix in JSONL filenames
    # e.g. "data__yield-sweep-22__clones__" when clones are under that path
    prefix = str(clone_dir).replace("/", "__").replace(".", "") + "__"
    # Normalize: remove leading underscores from relative paths
    prefix = prefix.lstrip("_")

    entries = _find_jsonl_files(input_dir, clone_dir, prefix)

    if args.repo:
        entries = [e for e in entries if e["slug"] == args.repo]
        if not entries:
            print(f"Error: repo {args.repo} not found in {input_dir}")
            return

    total_instances = sum(e["count"] for e in entries)
    print("=== Batch Enrichment ===")
    print(f"Repos: {len(entries)}, Instances: {total_instances}, Concurrency: {args.concurrency}")
    print(f"Model: {args.model}")
    print()

    results = []
    with ProcessPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {}
        for entry in entries:
            fut = executor.submit(
                _run_enrich,
                slug=entry["slug"],
                jsonl_path=entry["jsonl_path"],
                clone_path=entry["clone_path"],
                output_dir=output_dir,
                model=args.model,
            )
            futures[fut] = entry["slug"]

        for fut in as_completed(futures):
            results.append(fut.result())

    # Merge all enriched files
    merged_path = output_dir / "enriched-all.jsonl"
    total_enriched = 0
    with open(merged_path, "w") as merged:
        for entry in entries:
            enriched_file = output_dir / f"{entry['slug']}-enriched.jsonl"
            if enriched_file.exists():
                for line in open(enriched_file):
                    if line.strip():
                        merged.write(line)
                        total_enriched += 1

    # Write summary
    summary_path = output_dir / "enrich-summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"{'Repo':<50s} {'Input':>6s} {'Enriched':>9s} {'Rate':>6s}")
    print(f"{'-'*50} {'-'*6} {'-'*9} {'-'*6}")
    for r in sorted(results, key=lambda x: -x["enriched"]):
        rate = f"{r['enriched'] / r['input'] * 100:.0f}%" if r["input"] else "n/a"
        print(f"{r['slug']:<50s} {r['input']:>6d} {r['enriched']:>9d} {rate:>6s}")

    total_input = sum(r["input"] for r in results)
    overall_rate = f"{total_enriched / total_input * 100:.0f}%" if total_input else "n/a"
    print(f"{'-'*50} {'-'*6} {'-'*9} {'-'*6}")
    print(f"{'TOTAL':<50s} {total_input:>6d} {total_enriched:>9d} {overall_rate:>6s}")
    print(f"\nMerged output: {merged_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
