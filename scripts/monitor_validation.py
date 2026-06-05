#!/usr/bin/env python3
"""Live monitor for swebenchify validation progress.

Usage:
    python scripts/monitor_validation.py [output_dir] [log_file]

Defaults:
    output_dir = ./output/rh-v1
    log_file   = ./output/rh-v1-pipeline.log

Refreshes every 5 seconds. Press Ctrl-C to exit.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

OUTPUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/rh-v1")
LOG_FILE   = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output/rh-v1-pipeline.log")
REFRESH    = 60

BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
RESET  = "\033[0m"


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


def instance_statuses(ws_dir: Path) -> dict[str, str]:
    """Map instance_id → 'done' | 'partial' | 'pending'."""
    result: dict[str, str] = {}
    inst_root = ws_dir / "instances"
    if not inst_root.exists():
        return result
    for inst in inst_root.iterdir():
        if not inst.is_dir():
            continue
        repo = inst / "repo"
        pre  = repo / "pre_fix_output.txt"
        post = repo / "post_fix_output.txt"
        meta = repo / "validation_meta.json"
        if pre.exists() and post.exists() and meta.exists():
            try:
                status = json.loads(meta.read_text()).get("status", "done")
                result[inst.name] = "error" if status == "error" else "done"
            except Exception:
                result[inst.name] = "done"
        elif pre.exists() or post.exists() or meta.exists():
            result[inst.name] = "partial"
        else:
            result[inst.name] = "pending"
    return result


def count_emitted(slug: str) -> int:
    p = OUTPUT_DIR / f"{slug}-task-instances.jsonl"
    return sum(1 for _ in p.open() if _.strip()) if p.exists() else 0


def parse_log() -> tuple[int, int, float | None]:
    """Return (n_finished, n_missing, sessions_per_min)."""
    if not LOG_FILE.exists():
        return 0, 0, None
    finished = 0
    missing  = 0
    stamps: list[float] = []
    today = datetime.now().date()
    for line in LOG_FILE.open():
        if "Agent session finished" in line:
            finished += 1
            try:
                t = datetime.strptime(line.split()[0], "%H:%M:%S").replace(
                    year=today.year, month=today.month, day=today.day
                )
                stamps.append(t.timestamp())
            except Exception:
                pass
        if "Missing output files" in line:
            missing += 1
    rate = None
    if len(stamps) >= 2:
        span = stamps[-1] - stamps[0]
        if span > 0:
            rate = (len(stamps) - 1) / span * 60
    return finished, missing, rate


def tail_log(n: int = 8) -> list[str]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text().splitlines()
    return lines[-n:]


ERASE_LINE = "\033[2K\r"   # clear entire line, return to col 0
CURSOR_UP  = "\033[{}A"    # move cursor up N lines


def _lines(text: str) -> list[str]:
    """Split rendered text into lines, expanding any embedded newlines."""
    return text.splitlines()


def build_frame() -> list[str]:
    """Return the full monitor frame as a list of plain lines (no trailing \\n)."""
    out: list[str] = []

    now = datetime.now().strftime("%H:%M:%S")
    out.append(f"{BOLD}SWE-benchify Validation Monitor{RESET}  "
               f"{DIM}{now}  output={OUTPUT_DIR}  refresh={REFRESH}s{RESET}")
    out.append("")

    col = f"{'Repo':<42} {'Viable':>7} {'Done':>6} {'Partial':>8} {'Emitted':>8}  Progress"
    out.append(BOLD + col + RESET)
    out.append("─" * 90)

    total_viable = total_done = total_partial = total_emitted = 0

    for cand_file in sorted(OUTPUT_DIR.glob("*-candidates.jsonl")):
        slug = cand_file.stem.replace("-candidates", "")
        repo = slug.replace("__", "/")
        candidates = read_jsonl(cand_file)
        viable = [c for c in candidates
                  if c.get("patch") and c.get("test_patch") and c.get("problem_statement")]
        n_viable = len(viable)
        if n_viable == 0:
            continue

        sts = instance_statuses(OUTPUT_DIR / "workspaces" / slug)
        n_done    = sum(1 for s in sts.values() if s in ("done", "error"))
        n_partial = sum(1 for s in sts.values() if s == "partial")
        n_emitted = count_emitted(slug)

        total_viable  += n_viable
        total_done    += n_done
        total_partial += n_partial
        total_emitted += n_emitted

        pct = n_done / n_viable * 100 if n_viable else 0
        filled = int(pct / 5)
        bar = GREEN + "█" * filled + DIM + "░" * (20 - filled) + RESET

        d = (CYAN   + str(n_done)    + RESET) if n_done    else DIM + "0" + RESET
        p = (YELLOW + str(n_partial) + RESET) if n_partial else DIM + "0" + RESET
        e = (GREEN  + str(n_emitted) + RESET) if n_emitted else DIM + "—" + RESET

        out.append(f"{repo:<42} {n_viable:>7}  {d:>14}  {p:>16}  {e:>14}  {bar} {pct:4.0f}%")

    out.append("─" * 90)
    pct_t = total_done / total_viable * 100 if total_viable else 0
    out.append(f"{BOLD}{'TOTAL':<42} {total_viable:>7} {total_done:>7} {total_partial:>8} "
               f"{total_emitted:>8}{RESET}   {CYAN}{pct_t:.1f}%{RESET}")
    out.append("")

    n_fin, n_miss, rate = parse_log()
    remaining = total_viable - total_done
    fail_str = (f"{RED}{n_miss/n_fin*100:.0f}%{RESET}" if n_fin else "—")
    out.append(f"Sessions finished: {n_fin}   Missing outputs: {RED}{n_miss}{RESET}   "
               f"Fail rate: {fail_str}")
    if rate and remaining > 0:
        eta = timedelta(minutes=int(remaining / rate))
        out.append(f"Rate: {CYAN}{rate:.1f}{RESET} sessions/min   "
                   f"Remaining: {remaining}   ETA: {BOLD}{eta}{RESET}")
    elif remaining == 0:
        out.append(f"{GREEN}{BOLD}✓ All instances complete!{RESET}")
    else:
        out.append(f"Rate: {DIM}computing...{RESET}   Remaining: {remaining}")

    out.append(f"\n{DIM}── Recent log ──────────────────────────────────────────────────────────{RESET}")
    for line in tail_log(8):
        if "ERROR" in line or "Missing output" in line:
            out.append(f"  {RED}{line}{RESET}")
        elif "succeeded" in line or "emitted" in line or "validated" in line:
            out.append(f"  {GREEN}{line}{RESET}")
        elif "WARNING" in line:
            out.append(f"  {YELLOW}{line}{RESET}")
        else:
            out.append(f"  {DIM}{line}{RESET}")

    return out


def main() -> None:
    prev_height = 0
    first = True
    try:
        while True:
            frame = build_frame()
            if first:
                # First render: just print normally
                sys.stdout.write("\n".join(frame) + "\n")
                first = False
            else:
                # Move cursor up to the first line of the previous frame,
                # then overwrite each line in place.
                sys.stdout.write(CURSOR_UP.format(prev_height))
                for line in frame:
                    sys.stdout.write(ERASE_LINE + line + "\n")
                # If the new frame is shorter, blank out leftover lines
                for _ in range(prev_height - len(frame)):
                    sys.stdout.write(ERASE_LINE + "\n")
                # Move back up so next refresh starts at same position
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
