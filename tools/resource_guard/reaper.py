#!/usr/bin/env python3
"""
PLCHaT Resource Guard — orphan reaper + CPU watchdog.

Last line of defense against the CPU-explosion leak: compiled ST target binaries
(``plc_coverage_harness`` / ``plc_harness_test`` / AFL's ``afl_harness``) that
spin at ~100% CPU and get orphaned (PPID=1) when their parent Python is hard-killed
mid-run. proc_guard.py prevents most of these in-process; this watchdog catches any
that still escape and clamps total CPU as a hard ceiling.

Each tick:
  1. REAP ORPHANS — any matching process with PPID=1 is a pure leak: SIGKILL it.
  2. MONITOR/ENFORCE — estimate cores used by matching binaries; if over --max-cores
     and --enforce is set, SIGKILL the highest-CPU matching processes (orphans first)
     until back under the ceiling.
  3. HEARTBEAT — print counts + core estimate.

Note: ``ps comm`` truncates to 15 chars (plc_coverage_harness -> "plc_coverage_ha"),
so we match by prefix.

Usage:
  # background watchdog alongside a batch (reap orphans, clamp matching binaries <=10 cores)
  python -m tools.resource_guard.reaper --interval 5 --max-cores 10 --enforce \
      >/tmp/rq3_reaper.log 2>&1 &

  # one-shot cleanup (e.g. before re-running)
  python -m tools.resource_guard.reaper --once
"""

import argparse
import getpass
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List

DEFAULT_PATTERNS = ["afl_harness", "plc_coverage_harness", "plc_harness_test"]


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _snapshot(user: str) -> List[Dict]:
    """Return [{pid, ppid, pcpu, comm}] for the given user."""
    try:
        out = subprocess.run(
            ["ps", "-u", user, "-o", "pid=,ppid=,pcpu=,comm="],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return []
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            procs.append({
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "pcpu": float(parts[2]),
                "comm": parts[3].strip(),
            })
        except ValueError:
            continue
    return procs


def _matches(comm: str, patterns: List[str]) -> bool:
    # ps comm is truncated to 15 chars; match by prefix of the truncated name too.
    return any(comm.startswith(p[:15]) for p in patterns)


def _kill(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def tick(user: str, patterns: List[str], max_cores: float, enforce: bool) -> Dict:
    procs = _snapshot(user)
    matching = [p for p in procs if _matches(p["comm"], patterns)]

    # 1. Reap orphans (PPID=1) — always pure leaks.
    orphans = [p for p in matching if p["ppid"] == 1]
    reaped = sum(1 for p in orphans if _kill(p["pid"]))

    # Re-evaluate after reaping orphans.
    matching = [p for p in matching if not (p["ppid"] == 1)]
    matching_cores = sum(p["pcpu"] for p in matching) / 100.0
    user_cores = sum(p["pcpu"] for p in procs) / 100.0

    # 2. Enforce ceiling on matching binaries (orphans already gone).
    clamped = 0
    if enforce and matching_cores > max_cores:
        # Kill highest-CPU matching procs until back under the ceiling.
        for p in sorted(matching, key=lambda x: x["pcpu"], reverse=True):
            if matching_cores <= max_cores:
                break
            if _kill(p["pid"]):
                matching_cores -= p["pcpu"] / 100.0
                clamped += 1

    return {
        "matching": len(matching) + reaped,
        "orphans_reaped": reaped,
        "clamped": clamped,
        "matching_cores": round(matching_cores, 1),
        "user_cores": round(user_cores, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="PLCHaT orphan reaper + CPU watchdog")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between ticks")
    ap.add_argument("--user", default=getpass.getuser(), help="user to monitor")
    ap.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS),
                    help="comma-separated comm prefixes to treat as target binaries")
    ap.add_argument("--max-cores", type=float, default=10.0,
                    help="ceiling on cores used by matching binaries (with --enforce)")
    ap.add_argument("--enforce", action="store_true",
                    help="kill highest-CPU matching procs when over --max-cores")
    ap.add_argument("--once", action="store_true", help="run a single cleanup tick and exit")
    args = ap.parse_args()

    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
    print(f"[{_now()}] resource_guard: user={args.user} patterns={patterns} "
          f"max_cores={args.max_cores} enforce={args.enforce} "
          f"{'(once)' if args.once else f'interval={args.interval}s'}", flush=True)

    def run_tick():
        s = tick(args.user, patterns, args.max_cores, args.enforce)
        if s["orphans_reaped"] or s["clamped"] or s["matching_cores"] > args.max_cores:
            print(f"[{_now()}] reaped_orphans={s['orphans_reaped']} clamped={s['clamped']} "
                  f"matching={s['matching']} matching_cores={s['matching_cores']} "
                  f"user_cores={s['user_cores']}", flush=True)
        return s

    if args.once:
        run_tick()
        return 0

    try:
        while True:
            run_tick()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"[{_now()}] resource_guard stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
