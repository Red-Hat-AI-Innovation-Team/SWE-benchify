#!/usr/bin/env python3
"""Live monitor for swebenchify validation progress.

Usage:
    python scripts/monitor_validation.py [output_dir] [log_file]

Defaults:
    output_dir = ./output/rh-v1
    log_file   = (auto-detected from running swebenchify process, or ./output/rh-v1-pipeline.log)

Parses pipeline log lines to track per-repo progress through stages 3-6.
Works with both the old agent-based validation and the new Docker-based
compute_f2p() path.

Refreshes every 60 seconds. Press Ctrl-C to exit.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/rh-v1")
LOG_FILE   = Path(sys.argv[2]) if len(sys.argv) > 2 else None
REFRESH    = 60

BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
RESET  = "\033[0m"


_RE_PIPELINE_LOG_LINE = re.compile(
    r"\d{2}:\d{2}:\d{2}\s+(INFO|WARNING|ERROR)\s+swebenchify\."
)


def _find_log_file() -> Path | None:
    """Try to find the pipeline log from a running process or fallback."""
    if LOG_FILE and LOG_FILE.exists():
        return LOG_FILE
    # Prefer live output from a running swebenchify process.
    # Match on actual pipeline log format to avoid picking up agent transcripts.
    try:
        task_dir = Path("/private/tmp") / f"claude-{os.getuid()}"
        if task_dir.exists():
            for output in sorted(task_dir.rglob("*.output"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    text = output.read_text(errors="replace")[:500]
                except Exception:
                    continue
                if _RE_PIPELINE_LOG_LINE.search(text):
                    return output
    except Exception:
        pass
    # Fall back to the on-disk log
    default = OUTPUT_DIR.parent / f"{OUTPUT_DIR.name}-pipeline.log"
    if default.exists():
        return default
    return None


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.open():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ---------------------------------------------------------------------------
# Log parsing — extract per-repo progress from pipeline log lines
# ---------------------------------------------------------------------------

_RE_STAGE4 = re.compile(
    r"Stage 4: Validating (\d+) instances for (.+)"
)
_RE_F2P_DONE = re.compile(
    r"compute_f2p finished: repo=(\S+) status=(\w+) f2p=(\d+) p2p=(\d+) elapsed=([\d.]+)s"
)
_RE_AGENT_DONE = re.compile(
    r"Agent session finished: status=(\w+) cost_usd=([\d.]+)"
)
_RE_VALIDATED = re.compile(
    r"(\d+)/(\d+) instances validated successfully"
)
_RE_EMITTED = re.compile(
    r"(\d+) instances emitted for (.+)"
)
_RE_STAGE3 = re.compile(
    r"Stage 3: Discovering environment for (.+)"
)
_RE_ENV_DONE = re.compile(
    r"Go env: go([\d.]+), test=(.+), mode=(\w+)"
)
_RE_PIPELINE_DONE = re.compile(
    r"Pipeline complete\."
)


class RepoProgress:
    def __init__(self, name: str, n_viable: int = 0):
        self.name = name
        self.n_viable = n_viable
        self.stage = "pending"  # pending, env-discovery, validating, done
        self.n_done = 0
        self.n_valid = 0
        self.n_invalid = 0
        self.n_error = 0
        self.n_emitted = 0
        self.total_elapsed = 0.0
        self.validated_str = ""  # "5/13 instances validated successfully"


def parse_log(log_path: Path) -> tuple[dict[str, RepoProgress], list[str], bool]:
    """Parse pipeline log and return per-repo progress, recent lines, and done flag."""
    repos: dict[str, RepoProgress] = {}
    recent: list[str] = []
    current_repo: str | None = None
    pipeline_done = False
    agent_sessions = 0
    total_cost = 0.0

    if not log_path or not log_path.exists():
        return repos, [], False

    for line in log_path.open(errors="replace"):
        line = line.rstrip()

        m = _RE_STAGE3.search(line)
        if m:
            repo = m.group(1)
            current_repo = repo.replace("/", "__")
            if current_repo not in repos:
                repos[current_repo] = RepoProgress(repo)
            repos[current_repo].stage = "env-discovery"

        m = _RE_STAGE4.search(line)
        if m:
            n, repo = int(m.group(1)), m.group(2)
            slug = repo.replace("/", "__")
            if slug not in repos:
                repos[slug] = RepoProgress(repo, n)
            repos[slug].n_viable = n
            repos[slug].stage = "validating"
            current_repo = slug

        m = _RE_F2P_DONE.search(line)
        if m:
            repo, status = m.group(1), m.group(2)
            elapsed = float(m.group(5))
            slug = repo.replace("/", "__")
            if slug not in repos:
                repos[slug] = RepoProgress(repo)
            repos[slug].n_done += 1
            repos[slug].total_elapsed += elapsed
            if status == "valid":
                repos[slug].n_valid += 1
            elif status == "invalid":
                repos[slug].n_invalid += 1
            elif status == "error":
                repos[slug].n_error += 1

        m = _RE_VALIDATED.search(line)
        if m:
            valid, total = int(m.group(1)), int(m.group(2))
            if current_repo and current_repo in repos:
                repos[current_repo].validated_str = f"{valid}/{total}"
                repos[current_repo].stage = "done"
                repos[current_repo].n_done = total

        m = _RE_EMITTED.search(line)
        if m:
            n_emitted, repo = int(m.group(1)), m.group(2)
            slug = repo.replace("/", "__")
            if slug in repos:
                repos[slug].n_emitted = n_emitted

        m = _RE_AGENT_DONE.search(line)
        if m:
            agent_sessions += 1
            total_cost += float(m.group(2))

        if _RE_PIPELINE_DONE.search(line):
            pipeline_done = True

        recent.append(line)

    return repos, recent[-10:], pipeline_done


def count_candidates(slug: str) -> int:
    p = OUTPUT_DIR / f"{slug}-candidates.jsonl"
    if not p.exists():
        return 0
    candidates = read_jsonl(p)
    return sum(1 for c in candidates
               if c.get("patch") and c.get("test_patch") and c.get("problem_statement"))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

ERASE_LINE = "\033[2K\r"
CURSOR_UP  = "\033[{}A"


def build_frame(log_path: Path | None) -> list[str]:
    out: list[str] = []

    now = datetime.now().strftime("%H:%M:%S")
    log_name = log_path.name if log_path else "not found"
    out.append(f"{BOLD}SWE-benchify Validation Monitor{RESET}  "
               f"{DIM}{now}  output={OUTPUT_DIR}  log={log_name}  refresh={REFRESH}s{RESET}")
    out.append("")

    repos, recent, pipeline_done = parse_log(log_path) if log_path else ({}, [], False)

    # Also check for repos with candidates but not yet in the log
    for cand_file in sorted(OUTPUT_DIR.glob("*-candidates.jsonl")):
        slug = cand_file.stem.replace("-candidates", "")
        if slug not in repos:
            n = count_candidates(slug)
            if n > 0:
                repos[slug] = RepoProgress(slug.replace("__", "/"), n)

    col = f"{'Repo':<45} {'Stage':<14} {'Done':>5}/{'Total':<5} {'Valid':>5} {'Inv':>5} {'Emit':>5}  Progress"
    out.append(BOLD + col + RESET)
    out.append("─" * 105)

    total_viable = total_done = total_valid = total_emitted = 0

    for slug in sorted(repos):
        rp = repos[slug]
        n_viable = rp.n_viable or count_candidates(slug)
        if n_viable == 0:
            continue

        total_viable += n_viable
        total_done += rp.n_done
        total_valid += rp.n_valid
        total_emitted += rp.n_emitted

        # Stage display
        if rp.stage == "env-discovery":
            stage_str = f"{YELLOW}env-disc{RESET}"
        elif rp.stage == "validating":
            stage_str = f"{CYAN}validating{RESET}"
        elif rp.stage == "done":
            stage_str = f"{GREEN}done{RESET}"
        else:
            stage_str = f"{DIM}pending{RESET}"

        pct = rp.n_done / n_viable * 100 if n_viable else 0
        filled = int(pct / 5)
        bar = GREEN + "█" * filled + DIM + "░" * (20 - filled) + RESET

        v = (GREEN + str(rp.n_valid) + RESET) if rp.n_valid else DIM + "0" + RESET
        inv = (YELLOW + str(rp.n_invalid) + RESET) if rp.n_invalid else DIM + "0" + RESET
        e = (GREEN + str(rp.n_emitted) + RESET) if rp.n_emitted else DIM + "—" + RESET

        avg = f" {rp.total_elapsed / rp.n_done:.0f}s/ea" if rp.n_done else ""

        out.append(
            f"{rp.name:<45} {stage_str:<23} {rp.n_done:>5}/{n_viable:<5} "
            f"{v:>14} {inv:>14} {e:>14}  {bar} {pct:4.0f}%{DIM}{avg}{RESET}"
        )

    out.append("─" * 105)
    pct_t = total_done / total_viable * 100 if total_viable else 0
    out.append(f"{BOLD}{'TOTAL':<45} {'':14} {total_done:>5}/{total_viable:<5} "
               f"{total_valid:>5} {'':>5} {total_emitted:>5}{RESET}   {CYAN}{pct_t:.1f}%{RESET}")
    out.append("")

    if pipeline_done:
        out.append(f"{GREEN}{BOLD}Pipeline complete.{RESET}")
    else:
        remaining = total_viable - total_done
        if remaining == 0 and total_viable > 0:
            out.append(f"{GREEN}{BOLD}All instances processed.{RESET}")
        else:
            out.append(f"Remaining: {remaining} instances")

    out.append(f"\n{DIM}── Recent log ──────────────────────────────────────────────────────────────────{RESET}")
    for line in recent:
        if "ERROR" in line or "error" in line.lower() and "error_message" not in line:
            out.append(f"  {RED}{line[:120]}{RESET}")
        elif "compute_f2p finished" in line or "validated" in line or "emitted" in line:
            out.append(f"  {GREEN}{line[:120]}{RESET}")
        elif "WARNING" in line:
            out.append(f"  {YELLOW}{line[:120]}{RESET}")
        elif "Stage" in line:
            out.append(f"  {CYAN}{line[:120]}{RESET}")
        else:
            out.append(f"  {DIM}{line[:120]}{RESET}")

    return out


def main() -> None:
    log_path = _find_log_file() if LOG_FILE is None else LOG_FILE
    if log_path:
        print(f"Monitoring: {log_path}", flush=True)
    else:
        print("No log file found. Start swebenchify or pass log path as arg.", flush=True)

    prev_height = 0
    first = True
    try:
        while True:
            if log_path is None or not log_path.exists():
                log_path = _find_log_file()
            frame = build_frame(log_path)
            if first:
                sys.stdout.write("\n".join(frame) + "\n")
                first = False
            else:
                sys.stdout.write(CURSOR_UP.format(prev_height))
                for line in frame:
                    sys.stdout.write(ERASE_LINE + line + "\n")
                for _ in range(prev_height - len(frame)):
                    sys.stdout.write(ERASE_LINE + "\n")
                extra = max(0, prev_height - len(frame))
                if extra:
                    sys.stdout.write(CURSOR_UP.format(extra))
            sys.stdout.flush()
            prev_height = len(frame)
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        sys.stdout.write("\nMonitor stopped.\n")


if __name__ == "__main__":
    main()
