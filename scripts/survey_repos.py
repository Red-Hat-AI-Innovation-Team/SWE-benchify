#!/usr/bin/env python3
"""Survey Go repos for synthesis viability.

Clones each repo, counts mutation targets, and runs a test smoke check
to classify repos as Viable / Slow / Broken / Thin.

Usage:
    python scripts/survey_repos.py --config configs/swebenchify-rh-v1.yaml --workdir /tmp/survey
    python scripts/survey_repos.py --repos grpc/grpc-go containers/podman --workdir /tmp/survey
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _clone_repo(slug: str, workdir: Path) -> Path | None:
    safe_name = slug.replace("/", "__")
    clone_path = workdir / safe_name
    if clone_path.exists():
        return clone_path
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", f"https://github.com/{slug}.git", str(clone_path)],
            check=True, capture_output=True, timeout=300,
        )
        return clone_path
    except Exception as e:
        print(f"  {slug}: clone failed: {e}")
        return None


def _count_targets(clone_path: Path) -> dict:
    from swebenchify.synthesizer import find_mutation_targets
    targets = find_mutation_targets(str(clone_path), "go", max_files=100, max_functions=10)

    from swebenchify.synthesizer import _find_existing_test_file
    with_tests = 0
    for t in targets:
        if _find_existing_test_file(str(clone_path), t["file"], "go", function_name=t.get("function_name")):
            with_tests += 1

    return {"total": len(targets), "with_tests": with_tests}


def _smoke_test(clone_path: Path) -> dict:
    """Run a quick Go test to check buildability and measure test time."""
    go_files = list(clone_path.rglob("*_test.go"))
    if not go_files:
        return {"status": "no_tests", "duration_s": 0, "output": ""}

    test_pkg = "./" + str(go_files[0].parent.relative_to(clone_path))

    start = time.time()
    try:
        result = subprocess.run(
            ["go", "test", "-short", "-count=1", "-timeout", "90s", "-v", test_pkg],
            cwd=clone_path, capture_output=True, text=True, timeout=120,
        )
        duration = time.time() - start
        passed = result.returncode == 0
        output = (result.stdout + result.stderr)[-500:]
        return {
            "status": "pass" if passed else "test_fail",
            "duration_s": round(duration, 1),
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "duration_s": 120, "output": "killed after 120s"}
    except FileNotFoundError:
        return {"status": "no_go", "duration_s": 0, "output": "go binary not found"}
    except Exception as e:
        return {"status": "error", "duration_s": 0, "output": str(e)}


def _build_check(clone_path: Path) -> dict:
    """Check if the repo builds."""
    try:
        result = subprocess.run(
            ["go", "build", "./..."],
            cwd=clone_path, capture_output=True, text=True, timeout=300,
        )
        return {"builds": result.returncode == 0, "error": result.stderr[-300:] if result.returncode != 0 else ""}
    except subprocess.TimeoutExpired:
        return {"builds": False, "error": "build timeout (300s)"}
    except Exception as e:
        return {"builds": False, "error": str(e)}


def _classify(targets: dict, build: dict, test: dict) -> str:
    if not build["builds"]:
        return "Broken"
    if targets["with_tests"] < 20:
        return "Thin"
    if test["status"] == "timeout" or test["duration_s"] > 120:
        return "Slow"
    if test["status"] in ("pass", "test_fail"):
        return "Viable"
    return "Broken"


def main() -> None:
    parser = argparse.ArgumentParser(description="Survey Go repos for synthesis viability")
    parser.add_argument("--config", default=None, help="YAML config with repo list")
    parser.add_argument("--repos", nargs="*", default=None, help="Repo slugs to survey")
    parser.add_argument("--workdir", required=True, help="Working directory for clones")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test smoke check")
    parser.add_argument("--skip-build", action="store_true", help="Skip build check")
    args = parser.parse_args()

    if args.repos:
        slugs = args.repos
    elif args.config:
        with open(args.config) as f:
            config = yaml.safe_load(f)
        slugs = config.get("go_repos", [r for r in config.get("repos", [])])
    else:
        parser.error("Provide --config or --repos")
        return

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    print(f"Surveying {len(slugs)} Go repos...\n")

    results = []
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")

        clone_path = _clone_repo(slug, workdir)
        if not clone_path:
            results.append({"slug": slug, "class": "Broken", "error": "clone failed"})
            continue

        targets = _count_targets(clone_path)
        print(f"  targets: {targets['total']} total, {targets['with_tests']} with tests")

        if args.skip_build:
            build = {"builds": True, "error": ""}
        else:
            build = _build_check(clone_path)
            print(f"  build: {'OK' if build['builds'] else 'FAIL'}")

        if args.skip_tests:
            test = {"status": "skipped", "duration_s": 0, "output": ""}
        else:
            test = _smoke_test(clone_path)
            print(f"  test: {test['status']} ({test['duration_s']}s)")

        classification = _classify(targets, build, test)
        print(f"  -> {classification}")

        results.append({
            "slug": slug,
            "class": classification,
            "targets_total": targets["total"],
            "targets_with_tests": targets["with_tests"],
            "builds": build["builds"],
            "test_status": test["status"],
            "test_duration_s": test["duration_s"],
        })

    report_path = workdir / "survey-report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"{'Slug':<45} {'Class':<10} {'Targets':>8} {'w/Tests':>8}")
    print(f"{'-'*45} {'-'*10} {'-'*8} {'-'*8}")
    for r in sorted(results, key=lambda x: (-x.get("targets_with_tests", 0))):
        print(f"{r['slug']:<45} {r['class']:<10} {r.get('targets_total', '?'):>8} {r.get('targets_with_tests', '?'):>8}")

    viable = [r for r in results if r["class"] == "Viable"]
    print(f"\n{len(viable)}/{len(results)} repos viable for synthesis")
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
