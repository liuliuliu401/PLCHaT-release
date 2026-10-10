"""
PLCHaT Process Guard

Resource-safe execution of compiled *target* binaries (the ST harnesses
``plc_coverage_harness`` / ``plc_harness_test``). These binaries can spin in an
infinite loop and burn ~100% CPU; if their parent Python is hard-killed mid-run
(e.g. a tool/conversation timeout ``killpg``-ing the worker), they get reparented
to init (PPID=1) and keep spinning forever — the dominant CPU-leak source.

Defense in depth (mirrors tools/fuzzers/afl/orchestrator.py exactly — proven safe):
  1. start_new_session=True    -> binary + any children it forks live in their own
     process group so a timeout can ``killpg`` the WHOLE tree precisely.
  2. timeout -> killpg(SIGKILL) -> reaps the group on wall-clock overrun.
  3. finally killpg + pgrep -f <binary_path> reap -> kills any leftover whose
     cmdline references THIS run's unique binary path (scoped, never touches other
     runs), even on unexpected exceptions.

The remaining case — this Python being *hard-killed* (SIGKILL) mid-run, which
leaves no chance to run cleanup — is covered by the external watchdog
``tools/resource_guard/reaper.py`` (reaps PPID=1 orphans periodically).

NOTE: we deliberately do NOT use ``preexec_fn`` (e.g. PR_SET_PDEATHSIG). The RQ3
runner is multi-threaded, and running code after fork() in a threaded process can
deadlock Popen — which is why this matches AFL's preexec-free approach.
"""

import os
import signal
import subprocess
from typing import Dict, Optional


def _killpg(proc: subprocess.Popen, sig: int) -> None:
    """Signal the whole process group; fall back to the single PID."""
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.send_signal(sig)
        except Exception:
            pass


def _reap_binary(binary_path: Optional[str]) -> None:
    """Kill any leftover process whose cmdline references THIS run's binary path.
    binary_path is a unique temp path, so this is safe across concurrent runs."""
    if not binary_path:
        return
    try:
        out = subprocess.run(["pgrep", "-f", str(binary_path)],
                             capture_output=True, text=True, timeout=5)
        for pid in out.stdout.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (ProcessLookupError, ValueError, OSError):
                pass
    except Exception:
        pass


def run_target_binary(
    cmd,
    *,
    timeout: float,
    stdin_path: Optional[str] = None,
    input_text: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    text: bool = True,
    binary_path: Optional[str] = None,
) -> Dict:
    """Execute a compiled target binary with full resource protection.

    Returns a dict: {returncode, stdout, stderr, timed_out}. Never leaks the
    binary (group-killed + reaped) regardless of timeout or exception.
    """
    if binary_path is None and isinstance(cmd, (list, tuple)) and cmd:
        binary_path = cmd[0]

    stdin_f = None
    proc = None
    try:
        if stdin_path and os.path.exists(stdin_path):
            stdin_f = open(stdin_path, "r")
            stdin_arg = stdin_f
            comm_input = None
        elif input_text is not None:
            stdin_arg = subprocess.PIPE
            comm_input = input_text
        else:
            stdin_arg = subprocess.DEVNULL
            comm_input = None

        proc = subprocess.Popen(
            cmd,
            stdin=stdin_arg,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=text,
            start_new_session=True,
        )

        timed_out = False
        try:
            stdout, stderr = proc.communicate(input=comm_input, timeout=timeout)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _killpg(proc, signal.SIGKILL)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = ("", "")
            returncode = -signal.SIGKILL

        return {
            "returncode": returncode,
            "stdout": stdout or ("" if text else b""),
            "stderr": stderr or ("" if text else b""),
            "timed_out": timed_out,
        }
    finally:
        # Ensure the group is dead even on unexpected exceptions, then belt-and-
        # suspenders reap any escaped child for this run's binary.
        if proc is not None and proc.poll() is None:
            _killpg(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        _reap_binary(binary_path)
        if stdin_f is not None:
            try:
                stdin_f.close()
            except Exception:
                pass


__all__ = ["run_target_binary"]
