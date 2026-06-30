#!/usr/bin/env python3
"""Multi-SWE-bench Go harness coverage check.

Gold-validation trick: submit the gold fix_patch as the prediction.
A correct harness marks every gold instance "resolved". Any instance
that doesn't resolve, or whose F2P set disagrees with ours, is a gap.

Three things measured per instance:
  1. Build succeeds (golang image + git clone at base_commit)
  2. Gold patch resolves (pre-fix has failures, fix run passes them)
  3. Parser comparison: MSB regex (go test -v) vs our GoJSONParser (go test -json)

Key known divergences to hunt:
  • MSB uses go test -v + regex; we use go test -json + structured parser
  • MSB collapses TestFoo/subcase → TestFoo; we keep subtests distinct
  • MSB uses bare "TestFoo"; we use "pkg/path.TestFoo"

Prerequisites: Docker (no API key required).

Usage:
    python scripts/msb_harness_check.py
    python scripts/msb_harness_check.py --candidates /tmp/etcd_candidates.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("msb-check")

DOCKER = os.environ.get("DOCKER_PATH", "docker")
GO_IMAGE = "golang:latest"  # MSB uses golang:latest; etcd requires >=1.23
TIMEOUT_BUILD = 900   # 15 min for full etcd clone
TIMEOUT_RUN = 300     # 5 min per test run


# ---------------------------------------------------------------------------
# MSB etcd regex parser (exact copy from multi_swe_bench/harness/repos/golang/etcd_io/etcd.py)
# ---------------------------------------------------------------------------

def msb_parse_log(test_log: str) -> dict[str, str]:
    """Parse go test -v output using MSB's regex.  Subtests collapsed."""
    passed: set[str] = set()
    failed: set[str] = set()
    skipped: set[str] = set()

    re_pass = re.compile(r"--- PASS: (\S+)")
    re_fail_list = [
        re.compile(r"--- FAIL: (\S+)"),
        re.compile(r"FAIL:?\s?(.+?)\s"),
    ]
    re_skip = re.compile(r"--- SKIP: (\S+)")

    def base_name(name: str) -> str:
        idx = name.rfind("/")
        return name[:idx] if idx != -1 else name

    for line in test_log.splitlines():
        line = line.strip()
        m = re_pass.match(line)
        if m:
            t = base_name(m.group(1))
            if t not in failed:
                skipped.discard(t)
                passed.add(t)
            continue
        for re_fail in re_fail_list:
            m = re_fail.match(line)
            if m:
                t = base_name(m.group(1))
                passed.discard(t)
                skipped.discard(t)
                failed.add(t)
                break
        m = re_skip.match(line)
        if m:
            t = base_name(m.group(1))
            if t not in passed and t not in failed:
                skipped.add(t)

    result: dict[str, str] = {}
    for t in passed:
        result[t] = "passed"
    for t in failed:
        result[t] = "failed"
    for t in skipped:
        result[t] = "skipped"
    return result


# ---------------------------------------------------------------------------
# Our GoJSONParser
# ---------------------------------------------------------------------------

def our_parse_log(json_output: str) -> dict[str, str]:
    from swebenchify.parsers import GoJSONParser
    return GoJSONParser().parse(json_output)["tests"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def docker_ok() -> bool:
    try:
        r = subprocess.run([DOCKER, "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_run(image: str, script: str, timeout: int = TIMEOUT_RUN) -> tuple[int, str]:
    cmd = [DOCKER, "run", "--rm", image, "sh", "-c", script]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"


def docker_build(tag: str, context_dir: str, dockerfile: str) -> tuple[int, str]:
    Path(context_dir, "Dockerfile").write_text(dockerfile)
    r = subprocess.run(
        [DOCKER, "build", "-t", tag, context_dir],
        capture_output=True, text=True, timeout=TIMEOUT_BUILD,
    )
    return r.returncode, r.stdout + r.stderr


def affected_files(test_patch: str) -> list[str]:
    """Return file paths (relative to repo root) touched by test_patch."""
    paths: list[str] = []
    for line in test_patch.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        b_path = parts[3]
        path = b_path[2:] if b_path.startswith("b/") else b_path
        if path not in paths:
            paths.append(path)
    return paths


def build_test_commands(test_patch: str) -> list[str]:
    """Return shell commands that run the affected tests, handling multi-module repos.

    For multi-module repos (e.g. etcd), the affected file may be in a
    sub-module with its own go.mod. We generate a cd + go test command
    for each distinct sub-module root found. Falls back to ./... from repo
    root if no sub-module structure is detected.
    """
    files = affected_files(test_patch)
    if not files:
        return ["go test -v -count=1 ./..."]

    # Group files by their module root: walk up from the file's directory
    # to find the nearest go.mod
    # Since we can't read the container fs here, we heuristically detect
    # sub-module boundaries from the path itself:
    # If path starts with a top-level dir that commonly owns a go.mod
    # in etcd-style repos (server/, client/, ...), split there.
    module_roots: dict[str, list[str]] = {}  # module_root -> [pkg_path, ...]
    for fpath in files:
        parts = Path(fpath).parts
        if len(parts) < 2:
            root, pkg = ".", f"./{Path(fpath).parent}"
        else:
            # Use the top-level directory as a candidate module root
            root = parts[0]
            pkg_rel = str(Path(*parts[1:]).parent)
            pkg = f"./{pkg_rel}" if pkg_rel != "." else "./..."
        if root not in module_roots:
            module_roots[root] = []
        if pkg not in module_roots[root]:
            module_roots[root].append(pkg)

    # Generate test commands, each with a cd to the module root
    cmds: list[str] = []
    for root, pkgs in module_roots.items():
        pkg_str = " ".join(pkgs)
        if root == ".":
            cmds.append(f"go test -v -count=1 {pkg_str}")
        else:
            # Run from sub-module directory; package paths are relative to it
            cmds.append(f"(cd {root} && go test -v -count=1 {pkg_str})")
    return cmds or ["go test -v -count=1 ./..."]


def split_sections(output: str) -> tuple[str, str, str]:
    """Return (verbose, json, msb_root) sections."""
    verbose_lines, json_lines, msb_lines = [], [], []
    section = None
    for line in output.splitlines():
        s = line.strip()
        if s == "=== VERBOSE ===":
            section = "verbose"
        elif s == "=== JSON ===":
            section = "json"
        elif s == "=== MSB_ROOT ===":
            section = "msb"
        elif s in ("=== DONE ===",):
            section = None
        elif section == "verbose":
            verbose_lines.append(line)
        elif section == "json":
            json_lines.append(line)
        elif section == "msb":
            msb_lines.append(line)
    return "\n".join(verbose_lines), "\n".join(json_lines), "\n".join(msb_lines)


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def find_gaps(
    msb_pre: dict, msb_fix: dict, msb_f2p: list[str],
    our_pre: dict, our_fix: dict, our_f2p: list[str],
    verbose_pre: str, json_pre: str,
    msb_root_pre: str = "",
) -> list[str]:
    gaps = []

    # Gap: subtest collapsing
    our_all = set(our_pre) | set(our_fix)
    our_subtests = {n for n in our_all if "/" in n.rsplit(".", 1)[-1]}
    if our_subtests:
        gaps.append(
            f"SUBTEST_COLLAPSE: our parser has {len(our_subtests)} subtest entries "
            f"that MSB collapses (e.g. {sorted(our_subtests)[:2]})"
        )

    # Gap: test ID prefix (pkg.TestFoo vs TestFoo)
    our_with_pkg = {n for n in our_all if "." in n}
    if our_with_pkg:
        gaps.append(
            f"ID_PREFIX: our IDs have package prefix (e.g. {sorted(our_with_pkg)[:2]}); "
            f"MSB uses bare test names"
        )

    # Gap: F2P disagreement (after normalising both to bare TestName)
    def normalise(names: list[str]) -> set[str]:
        result = set()
        for n in names:
            bare = n.rsplit(".", 1)[-1]   # strip pkg prefix
            bare = bare.split("/")[0]      # strip subtest suffix
            result.add(bare)
        return result

    msb_norm = normalise(msb_f2p)
    our_norm = normalise(our_f2p)
    only_msb = msb_norm - our_norm
    only_ours = our_norm - msb_norm
    if only_msb:
        gaps.append(f"F2P_ONLY_MSB (after normalise): {sorted(only_msb)[:3]}")
    if only_ours:
        gaps.append(f"F2P_ONLY_OURS (after normalise): {sorted(only_ours)[:3]}")

    # Gap: vendoring / module issues
    for marker in ("cannot find module", "unknown import path", "no required module"):
        if marker in verbose_pre:
            gaps.append(f"VENDOR: '{marker}' in pre-fix output")
            break

    # Gap: no test output at all
    if not verbose_pre.strip() and not json_pre.strip():
        gaps.append("NO_OUTPUT: both parsers saw empty output — check test command / package scope")

    # Gap: multi-module repo — MSB's ./... from root misses sub-module tests
    if msb_root_pre and "does not contain package" in msb_root_pre:
        gaps.append(
            "MULTI_MODULE: MSB runs 'go test ./...' from repo root but affected package "
            "is in a sub-module — MSB would miss these tests entirely. "
            "SWE-benchify must cd into the correct sub-module to test."
        )
    elif msb_root_pre and "[setup failed]" in msb_root_pre and verbose_pre and "PASS" in verbose_pre:
        gaps.append(
            "MULTI_MODULE: MSB root-module run fails ([setup failed]) but "
            "sub-module run passes — MSB harness cannot grade these instances."
        )

    return gaps


# ---------------------------------------------------------------------------
# Per-instance check
# ---------------------------------------------------------------------------

@dataclass
class InstanceResult:
    pr_number: int
    base_commit: str
    build_ok: bool = False
    pre_fix_ran: bool = False
    fix_ran: bool = False
    resolved: bool = False
    msb_f2p: list[str] = field(default_factory=list)
    our_f2p: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    pre_verbose_sample: str = ""
    error: str | None = None


def check_instance(cand: dict[str, Any], workdir: Path) -> InstanceResult:
    org = cand["org"]
    repo = cand["repo"]
    pr_num = cand["pr_number"]
    base_sha = cand["base_commit"]
    fix_patch = cand.get("patch") or ""
    test_patch = cand.get("test_patch") or ""

    result = InstanceResult(pr_number=pr_num, base_commit=base_sha)

    inst_dir = workdir / f"pr-{pr_num}"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "fix.patch").write_text(fix_patch)
    (inst_dir / "test.patch").write_text(test_patch)

    test_cmds = build_test_commands(test_patch)
    json_cmds = [c.replace("go test -v", "go test -json") for c in test_cmds]
    # MSB always runs from repo root: go test ./...
    msb_root_cmd = "go test -v -count=1 ./..."
    logger.info("[#%d] test commands: %s", pr_num, test_cmds)

    # ---- Build ----
    logger.info("[#%d] building (full clone %s/%s @ %s)...", pr_num, org, repo, base_sha[:8])
    build_tag = f"msb-check-{repo}-{pr_num}"
    # Write a warmup shell script so complex commands survive Dockerfile embedding
    warmup_script = "#!/bin/sh\nset -e\n"
    warmup_script += f"cd /work/{repo}\n"
    # Download all modules for all sub-modules found (mirrors MSB prepare.sh)
    warmup_script += "go mod download 2>/dev/null || true\n"
    for tc in test_cmds:
        # cd into sub-module if needed, then download its modules
        if tc.startswith("(cd "):
            sub = tc.split("&&")[0].strip("( ").replace("cd ", "").strip()
            warmup_script += f"(cd {sub} && go mod download 2>/dev/null || true)\n"
    warmup_script += "echo warmup_done\n"
    (inst_dir / "warmup.sh").write_text(warmup_script)

    dockerfile = textwrap.dedent(f"""\
        FROM {GO_IMAGE}
        RUN git clone https://github.com/{org}/{repo}.git /work/{repo} && \
            cd /work/{repo} && git checkout {base_sha}
        COPY fix.patch /work/fix.patch
        COPY test.patch /work/test.patch
        COPY warmup.sh /work/warmup.sh
        RUN chmod +x /work/warmup.sh && /work/warmup.sh
    """)
    rc, build_out = docker_build(build_tag, str(inst_dir), dockerfile)
    if rc != 0:
        result.error = f"docker build failed (rc={rc}): {build_out[-300:]}"
        logger.warning("[#%d] %s", pr_num, result.error[:120])
        return result
    result.build_ok = True
    logger.info("[#%d] build OK", pr_num)

    # ---- Pre-fix run ----
    logger.info("[#%d] pre-fix run...", pr_num)
    verbose_body = "\n".join(f"    {c} 2>&1 || true" for c in test_cmds)
    json_body = "\n".join(f"    {c} 2>&1 || true" for c in json_cmds)
    msb_verbose = f"    {msb_root_cmd} 2>&1 || true"

    pre_script = textwrap.dedent(f"""\
        set -e
        cd /work/{repo}
        git apply /work/test.patch 2>&1 || {{ echo PATCH_APPLY_FAILED; exit 0; }}
        echo "=== VERBOSE ==="
{verbose_body}
        echo "=== JSON ==="
{json_body}
        echo "=== MSB_ROOT ==="
{msb_verbose}
        echo "=== DONE ==="
    """)
    rc_pre, pre_out = docker_run(build_tag, pre_script)
    logger.info("[#%d] pre-fix rc=%d lines=%d", pr_num, rc_pre, pre_out.count("\n"))

    if "PATCH_APPLY_FAILED" in pre_out:
        result.error = "test.patch failed to apply"
        return result
    result.pre_fix_ran = True

    verbose_pre, json_pre, msb_root_pre = split_sections(pre_out)
    result.pre_verbose_sample = verbose_pre[:600]
    logger.info("[#%d] pre-fix verbose=%d json=%d lines",
                pr_num, verbose_pre.count("\n"), json_pre.count("\n"))

    # ---- Fix run ----
    logger.info("[#%d] fix run (gold patch)...", pr_num)
    fix_script = textwrap.dedent(f"""\
        set -e
        cd /work/{repo}
        git checkout . 2>&1
        git apply /work/test.patch /work/fix.patch 2>&1 || {{ echo PATCH_APPLY_FAILED; exit 0; }}
        echo "=== VERBOSE ==="
{verbose_body}
        echo "=== JSON ==="
{json_body}
        echo "=== MSB_ROOT ==="
{msb_verbose}
        echo "=== DONE ==="
    """)
    rc_fix, fix_out = docker_run(build_tag, fix_script)
    logger.info("[#%d] fix rc=%d lines=%d", pr_num, rc_fix, fix_out.count("\n"))

    if "PATCH_APPLY_FAILED" in fix_out:
        result.error = "gold patch failed to apply"
        return result
    result.fix_ran = True

    verbose_fix, json_fix, msb_root_fix = split_sections(fix_out)

    # ---- Parse ----
    msb_pre = msb_parse_log(verbose_pre)
    msb_fix_parsed = msb_parse_log(verbose_fix)
    our_pre = our_parse_log(json_pre)
    our_fix = our_parse_log(json_fix)

    msb_f2p = sorted(
        {t for t, s in msb_pre.items() if s == "failed"} &
        {t for t, s in msb_fix_parsed.items() if s == "passed"}
    )
    our_f2p = sorted(
        {t for t, s in our_pre.items() if s == "failed"} &
        {t for t, s in our_fix.items() if s == "passed"}
    )
    result.msb_f2p = msb_f2p
    result.our_f2p = our_f2p
    result.resolved = bool(msb_f2p)

    result.gaps = find_gaps(
        msb_pre, msb_fix_parsed, msb_f2p,
        our_pre, our_fix, our_f2p,
        verbose_pre, json_pre,
        msb_root_pre=msb_root_pre,
    )

    # Cleanup image
    subprocess.run([DOCKER, "rmi", build_tag], capture_output=True)

    logger.info("[#%d] resolved=%s msb_f2p=%d our_f2p=%d gaps=%d",
                pr_num, result.resolved, len(msb_f2p), len(our_f2p), len(result.gaps))
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="/tmp/etcd_candidates.json")
    ap.add_argument("--max-instances", type=int, default=5)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not docker_ok():
        print("ERROR: Docker not available.")
        sys.exit(1)

    candidates = json.loads(Path(args.candidates).read_text())[:args.max_instances]
    for c in candidates:
        c.setdefault("org", "etcd-io")
        c.setdefault("repo", "etcd")

    print(f"\nMSB harness coverage check — {len(candidates)} etcd instances\n")

    results: list[InstanceResult] = []
    with tempfile.TemporaryDirectory() as workdir:
        for cand in candidates:
            try:
                r = check_instance(cand, Path(workdir))
            except Exception as exc:
                r = InstanceResult(
                    pr_number=cand["pr_number"],
                    base_commit=cand["base_commit"],
                    error=str(exc),
                )
            results.append(r)

    print("\n" + "=" * 70)
    print("Results")
    print("=" * 70)

    all_gaps: list[str] = []
    for r in results:
        if r.error:
            sym = "⚠"
        elif r.resolved:
            sym = "✓"
        else:
            sym = "✗"
        print(f"\n[{sym}] #{r.pr_number} (base {r.base_commit[:8]})")
        if r.error:
            print(f"    ERROR: {r.error[:200]}")
            continue
        print(f"    build={r.build_ok}  pre_ran={r.pre_fix_ran}  fix_ran={r.fix_ran}  resolved={r.resolved}")
        if r.pre_verbose_sample and not r.pre_fix_ran:
            print(f"    pre-fix sample: {r.pre_verbose_sample[:200]}")
        print(f"    MSB F2P ({len(r.msb_f2p)}): {r.msb_f2p[:3]}{'…' if len(r.msb_f2p)>3 else ''}")
        print(f"    Our F2P ({len(r.our_f2p)}): {r.our_f2p[:3]}{'…' if len(r.our_f2p)>3 else ''}")
        if r.pre_verbose_sample:
            # Show first 3 relevant lines of verbose output for debugging
            relevant = [line for line in r.pre_verbose_sample.splitlines()
                        if any(k in line for k in ("FAIL", "PASS", "SKIP", "error", "cannot"))][:4]
            if relevant:
                print("    test sample:", relevant[0])
        for g in r.gaps:
            print(f"    GAP: {g}")
            all_gaps.append(f"#{r.pr_number}: {g}")

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    built = sum(1 for r in results if r.build_ok)
    resolved = sum(1 for r in results if r.resolved)
    errored = sum(1 for r in results if r.error)
    print(f"  Total:    {len(results)}")
    print(f"  Built:    {built}/{len(results)}")
    print(f"  Resolved: {resolved}/{len(results)}  (gold patch → MSB marks resolved)")
    print(f"  Errors:   {errored}/{len(results)}")

    gap_types = {g.split(":")[0].split(" ")[0] for g in all_gaps}
    if all_gaps:
        print(f"\nGap types found ({len(gap_types)}): {sorted(gap_types)}")
        for g in all_gaps:
            print(f"  • {g}")
    else:
        print("\n✓ No parser/format gaps — harness and producer are aligned")

    out = Path("results/msb_harness_check.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps([
        {"pr_number": r.pr_number, "base_commit": r.base_commit,
         "build_ok": r.build_ok, "resolved": r.resolved,
         "msb_f2p": r.msb_f2p, "our_f2p": r.our_f2p,
         "gaps": r.gaps, "error": r.error}
        for r in results
    ], indent=2))
    print("\nFull results: results/msb_harness_check.json")


if __name__ == "__main__":
    main()
