"""
AFL++ Orchestrator

Core execution orchestration for AFL++ fuzzing campaigns.

Handles:
- AFL++ process management and monitoring
- Seed evolution strategies
- Trace deduplication and IR export
- Stagnation detection and adaptive depth increase

Migrated from: baselines/afl/generator.py (AFLStageOrchestrator)
Refactored: Removed debug prints, fixed bare except, clarified return semantics
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Any

from .config import AFLConfig, AFL_ENV_VARS
from .seed_normalizer import SeedNormalizer

# Configure logging
logger = logging.getLogger(__name__)


class AFLOrchestrator:
    """
AFL++ execution orchestrator.

Function:
- AFL++ process management
- Seed evolution strategy
- stall detection
- Trace deduplication
- IR export

Migrated from: baselines/afl/generator.py:AFLStageOrchestrator
    """

    def __init__(
        self,
        config: AFLConfig,
        schema_dict: Dict[str, Any],
        st_path: Path,
        binary_path: Path,
        initial_seeds: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Initialize the AFL orchestrator.

        Args:
            config: AFL configuration
            schema_dict: Input schema dictionary
            st_path: Path to ST source file
            binary_path: Path to AFL-instrumented binary
        """
        self.config = config
        self.schema_dict = schema_dict
        self.st_path = st_path
        self.binary_path = binary_path
        # High-quality seeds injected by the LLM (historical/triggered/distilled cases).
        # Each is a dict with a 'sparse_timeline' {cycle: {var: value}}.
        self.initial_seeds = initial_seeds or []

        self.normalizer = SeedNormalizer(schema_dict)
        self.column_count = schema_dict.get("column_count", 1)

        # State counter
        self.total_execs_accumulated = 0
        self.current_stage_execs = 0
        self.last_total_execs = 0
        self.current_n = 1  # Current evolution depth

        self.start_time = 0.0
        self.last_discovery_time = 0.0
        self.seen_queue = set()
        self.seen_crashes = set()
        self.base_dir: Optional[Path] = None
        self.total_plc_cycles = 0

        # Sampling callback (for 24h experiments)
        self.sampling_callback: Optional[Callable] = None

        # Kill verification status
        self.verified_killed = False

        # Stagnation detection counter
        self.no_progress_stages = 0

        # Process reference (keep updated)
        self.fuzzer_proc: Optional[subprocess.Popen] = None

    def run(self, stop_on_crash: bool = False):
        """
Run AFL fuzz testing.

        Args:
stop_on_crash: RQ2 specific, exit early only when a valid Crash is found
        """
        self.prepare_run()
        self.verified_killed = False

        self.config.afl_in_dir.mkdir(parents=True, exist_ok=True)

        # Inject high-quality seeds (historical/trigger/distillation cases) provided by LLM -> AFL mutates and evolves from them, breaking through coverage plateau.
        n_injected = self._write_injected_seeds()

        # Initialize the first seed (fallback when no injected seed, ensure afl_in_dir is not empty)
        seed_path = self.config.afl_in_dir / "seed_n1.txt"
        if n_injected == 0 and not seed_path.exists():
            with open(seed_path, 'w') as f:
                f.write(" ".join(["0"] * (self.column_count - 1) + ["100"]) + "\n")

        if self.config.afl_out_dir.exists():
            shutil.rmtree(self.config.afl_out_dir)

        env = os.environ.copy()
        env.update(AFL_ENV_VARS)
        env["AFL_CRASH_EXITCODE"] = "77"

        # Start initial AFL process
        self.fuzzer_proc = self._start_fuzzer(env)

        try:
            self._run_main_loop(stop_on_crash)
        finally:
            self._cleanup_fuzzer()
            self._final_report()

    def _start_fuzzer(self, env: Dict[str, str], resume: bool = False) -> subprocess.Popen:
        """Start the AFL fuzzer process.

        Args:
env: environment variable
resume: whether to resume from the previous corpus

        Returns:
New fuzzer process reference
        """
        hard_timeout = str(self.config.max_runtime_sec + 10)

        if resume:
            afl_cmd = [
                "timeout", "-k", "5", hard_timeout,
                "afl-fuzz",
                "-i", "-",  # Resume from previous corpus
                "-o", str(self.config.afl_out_dir),
                "-t", "100+", "-d", "--",
                str(self.binary_path), "--silent"
            ]
        else:
            afl_cmd = [
                "timeout", "-k", "5", hard_timeout,
                "afl-fuzz",
                "-i", str(self.config.afl_in_dir),
                "-o", str(self.config.afl_out_dir),
                "-t", "100+", "-d", "--",
                str(self.binary_path), "--silent"
            ]

        # start_new_session=True puts timeout + afl-fuzz + the fork-server target
        # (afl_harness) into a dedicated process group so cleanup can kill the WHOLE
        # group. Without this, killing only fuzzer_proc orphans afl_harness (PPID=1),
        # which accumulates across evolution restarts and leaks (load explosion).
        return subprocess.Popen(
            afl_cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            start_new_session=True
        )

    def prepare_run(self):
        """Prepare the runtime environment."""
        self.start_time = time.time()
        self.last_discovery_time = time.time()
        self.no_progress_stages = 0

        initial_threshold = 3 if self.config.max_cycles >= 10 else self.config.plateau_seconds
        logger.info(f"[AFL_ORCH] Preparing run: max_runtime={self.config.max_runtime_sec}s")
        logger.info(f"[AFL_ORCH] Adaptive stagnation: N<10 use {initial_threshold}s, N>=10 use {self.config.plateau_seconds}s")

    def _run_main_loop(self, stop_on_crash: bool):
        """Main execution loop."""
        next_sample_time = time.time() + self.config.sampling_interval_sec
        logger.info(f"[AFL_ORCH] Starting main loop: stop_on_crash={stop_on_crash}")

        while (time.time() - self.start_time) < self.config.max_runtime_sec:
            new_p, new_c = self._poll_directories()

            # Record newly discovered files
            if new_p:
                logger.info(f"[AFL_ORCH] Discovered {len(new_p)} new queue files: {new_p[:3]}...")
            if new_c:
                logger.info(f"[AFL_ORCH] Discovered {len(new_c)} new crash files: {new_c[:3]}...")

            # RQ2 Optimization: Legitimate Kill Verification
            if stop_on_crash and new_c:
                if self._verify_crash():
                    logger.info("[AFL_ORCH] Valid crash verified, stopping...")
                    break

            # Update statistics
            self._update_statistics()

            # Check for stagnation
            should_continue = self._check_stagnation(new_p, new_c)
            if not should_continue:
                logger.info("[AFL_ORCH] Stagnation detected, stopping...")
                break

            # State output
            self._print_status()

            # Sampling callback
            if self.sampling_callback and (time.time() >= next_sample_time):
                next_sample_time = self._trigger_sampling(next_sample_time)

            time.sleep(1)

    def _verify_crash(self) -> bool:
        """Verify whether the newly discovered crash is valid.

        Returns:
            True if verified crash found
        """
        if not self.base_dir:
            return False

        crash_dir = self.base_dir / "crashes"
        for crash_file in sorted(
            crash_dir.glob("id:*"),
            key=os.path.getmtime,
            reverse=True
        ):
            if crash_file.name in self.seen_crashes:
                continue

            try:
                raw_data = crash_file.read_bytes()
                clean_data = self.normalizer.normalize(raw_data)
                if not clean_data:
                    continue

                v_proc = subprocess.run(
                    [str(self.binary_path), "--silent"],
                    input=clean_data.encode('utf-8'),
                    capture_output=True,
                    timeout=10  # Add timeout to prevent hanging
                )

                if v_proc.returncode != 0:
                    elapsed = int(time.time() - self.start_time)
                    print(f"\n[√] Valid Mutant Kill Verified at {elapsed}s.")
                    self.verified_killed = True
                    return True
            except (OSError, subprocess.TimeoutExpired) as e:
                # Ignore crash files that cannot be read or timed out
                continue

        return self.verified_killed

    def _update_statistics(self):
        """Update execution statistics."""
        curr_s = self._parse_fuzzer_stats()
        stage_execs = int(curr_s.get("execs_done", 0))
        if stage_execs > self.current_stage_execs:
            self.current_stage_execs = stage_execs

    def _get_adaptive_plateau_threshold(self) -> int:
        """
Get the adaptive stagnation threshold.

- N < 10: Use a short threshold to quickly escape inefficient shallow exploration.
- N >= 10: Use configuration threshold to allow sufficient depth exploration

        Returns:
Current applicable stagnation threshold (seconds)
        """
        if self.current_n < 10:
            return 3  # Shallow fast evolution
        return self.config.plateau_seconds  # Thorough deep exploration

    def _check_stagnation(
        self,
        new_p: List[str],
        new_c: List[str],
    ) -> bool:
        """
Check for stagnation and trigger evolution.

        Returns:
            False if should stop (coverage saturated), True if should continue
        """
        if new_p or new_c:
            self.last_discovery_time = time.time()

        elapsed = time.time() - self.start_time
        stagnant = time.time() - self.last_discovery_time
        plateau_threshold = self._get_adaptive_plateau_threshold()

        if stagnant > plateau_threshold:
            if not new_p and not new_c:
                self.no_progress_stages += 1
            else:
                self.no_progress_stages = 0

            if self.no_progress_stages >= self.config.max_no_progress_stages:
                print(f"\n[!] Coverage Saturated. No progress for {self.no_progress_stages} stages. Stopping...")
                return False  # Should stop

            # Terminate and evolve seeds
            logger.info(f"[AFL_ORCH] Stagnation detected: {stagnant:.1f}s > threshold={plateau_threshold}s, N={self.current_n}")
            self._terminate_and_evolve()

        return True  # Continue execution

    def _kill_group(self, proc, sig) -> None:
        """Signal the WHOLE process group (timeout + afl-fuzz + afl_harness fork-server
        children), not just the launched proc. Prevents orphaned afl_harness leaks."""
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(sig)
            except Exception:
                pass

    def _reap_target_binaries(self) -> None:
        """Belt-and-suspenders: kill any leftover process whose cmdline references THIS
        run's instrumented binary (unique temp path) — reaps fork-server children that
        escaped the group kill. Scoped by binary_path so it never touches other runs."""
        try:
            bp = str(self.binary_path)
            out = subprocess.run(["pgrep", "-f", bp], capture_output=True,
                                 text=True, timeout=5)
            for pid in out.stdout.split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (ProcessLookupError, ValueError, OSError):
                    pass
        except Exception:
            pass

    def _terminate_and_evolve(self) -> None:
        """Terminate current AFL and evolve seeds."""
        if self.fuzzer_proc is None:
            return

        # graceful stop (SIGINT lets afl-fuzz flush state), then hard-kill the GROUP so
        # the fork-server target (afl_harness) dies too instead of orphaning.
        self._kill_group(self.fuzzer_proc, signal.SIGINT)
        try:
            self.fuzzer_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_group(self.fuzzer_proc, signal.SIGKILL)
        self._reap_target_binaries()

        final_stats = self._parse_fuzzer_stats()
        self.total_execs_accumulated += int(
            final_stats.get("execs_done", self.current_stage_execs)
        )
        self.current_stage_execs = 0

        self.evolve_seeds()

        # Restart AFL and update instance variables
        self._restart_fuzzer()
        self.last_discovery_time = time.time()

    def _restart_fuzzer(self) -> None:
        """Restart the AFL fuzzer process and update instance variables."""
        env = os.environ.copy()
        env.update(AFL_ENV_VARS)

        # Create new process and update instance variable
        self.fuzzer_proc = self._start_fuzzer(env, resume=True)

    def _poll_directories(self) -> Tuple[List[str], List[str]]:
        """Poll the AFL output directory to discover new files.

        Returns:
            Tuple of (new queue files, new crash files)
        """
        if not self.base_dir:
            for p in [self.config.afl_out_dir, self.config.afl_out_dir / "default"]:
                if (p / "queue").exists():
                    self.base_dir = p
                    break

        if not self.base_dir:
            return [], []

        def get_new(subdir: str, seen_set: set) -> List[str]:
            p = self.base_dir / subdir
            if not p.exists():
                return []
            current = set([f for f in os.listdir(p) if f.startswith("id:")])
            new = current - seen_set
            seen_set.update(new)
            return list(new)

        return get_new("queue", self.seen_queue), get_new("crashes", self.seen_crashes)

    def _parse_fuzzer_stats(self) -> Dict[str, str]:
        """Parse the fuzzer_stats file.

        Returns:
            Dictionary of stats key-value pairs
        """
        if not self.base_dir:
            return {}

        res = {}
        try:
            stats_file = self.base_dir / "fuzzer_stats"
            with open(stats_file, 'r', errors='ignore') as f:
                for line in f:
                    if " : " in line:
                        k, v = line.split(" : ", 1)
                        res[k.strip()] = v.strip()
        except (OSError, IOError):
            pass  # File does not exist or read failed, return empty dictionary

        return res

    def _print_status(self):
        """Print status information (use logger to ensure logs are captured)."""
        elapsed = time.time() - self.start_time
        global_now = self.total_execs_accumulated + self.current_stage_execs

        if elapsed > 0:
            speed_str = f"{global_now/elapsed:.2f} exec/s"
        else:
            speed_str = "(HOLD)"

        if global_now > self.last_total_execs:
            self.last_total_execs = global_now

        # Use logger instead of sys.stdout to ensure logs are captured
        status_msg = (
            f"[AFL_HEARTBEAT] Time: {int(elapsed)}s | Execs: {global_now} | "
            f"Speed: {speed_str} | Paths: {len(self.seen_queue)} | N: {self.current_n}"
        )
        logger.info(status_msg)

        # Simultaneously output to console
        print(f"\r[*] Time: {int(elapsed)}s | Execs: {global_now} | "
              f"Speed: {speed_str} | Paths: {len(self.seen_queue)} | "
              f"N: {self.current_n}      ", end='', flush=True)

    def _trigger_sampling(self, next_sample_time: float) -> float:
        """Trigger periodic sampling callback.

        Returns:
            Next sampling time
        """
        elapsed = time.time() - self.start_time
        print(f"\n[!] Reaching sampling interval ({int(elapsed)}s). Forcing IR export...")
        self.export_to_unified_ir()
        if self.sampling_callback:
            self.sampling_callback(elapsed)
        return time.time() + self.config.sampling_interval_sec

    def _cleanup_fuzzer(self):
        """Clean up the fuzzer process."""
        if self.fuzzer_proc and self.fuzzer_proc.poll() is None:
            # kill the WHOLE group (timeout + afl-fuzz + afl_harness), not just timeout.
            self._kill_group(self.fuzzer_proc, signal.SIGTERM)
            try:
                self.fuzzer_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._kill_group(self.fuzzer_proc, signal.SIGKILL)
        # final safety net: reap any escaped fork-server children for this run's binary.
        self._reap_target_binaries()

        final_stats = self._parse_fuzzer_stats()
        self.total_execs_accumulated += int(
            final_stats.get("execs_done", self.current_stage_execs)
        )

        # Last sampling
        if self.sampling_callback:
            final_elapsed = time.time() - self.start_time
            print(f"\n[!] Finalizing task. Triggering concluding sample...")
            self.sampling_callback(final_elapsed)

    def _final_report(self):
        """Print final report."""
        total_execs = self.total_execs_accumulated
        duration = time.time() - self.start_time
        print(f"\n\n{'='*45}\n         AFL++ FINAL REPORT\n{'='*45}")
        print(f"Target: {self.config.task_root.name}")
        print(f"Execs: {total_execs}")
        if duration > 0:
            print(f"Throughput: {total_execs/duration:.2f} exec/s")
        print(f"Paths: {len(self.seen_queue)}")
        print(f"Depth: N={self.current_n}")
        print(f"{'='*45}")

        # Export IR
        self.export_to_unified_ir()

    def evolve_seeds(self):
        """Seed evolution - Limit the maximum evolution depth of AFL seeds, gradually increase the temporal depth."""
        if not self.base_dir:
            logger.warning("[AFL_ORCH] Cannot evolve seeds: base_dir not set")
            return

        self.current_n = min(self.current_n + 5, self.config.max_cycles)
        q_dir = self.base_dir / "queue"

        logger.info(f"[AFL_ORCH] Evolving seeds to N={self.current_n}")

        try:
            seeds = sorted(
                [q_dir / f for f in os.listdir(q_dir) if f.startswith("id:")],
                key=os.path.getmtime,
                reverse=True
            )[:3]
        except (OSError, FileNotFoundError):
            return

        print(f"\n[STAGING] Evolution N={self.current_n}")
        logger.info(f"[AFL_ORCH] Selected {len(seeds)} seeds for evolution")

        for i, s_path in enumerate(seeds):
            try:
                logger.info(f"[AFL_ORCH] Processing seed {i+1}/{len(seeds)}: {s_path.name}")

                with open(s_path, 'r', errors='ignore') as f:
                    raw = f.read()

                logger.debug(f"[AFL_ORCH] Seed raw content (first 100 chars): {raw[:100]}...")

                clean = self.normalizer.normalize(raw, max_cycles=self.config.max_cycles)
                lines = clean.splitlines()

                while len(lines) < self.current_n:
                    lines.append(lines[-1] if lines else " ".join(["0"] * self.column_count))

                target_file = self.config.afl_in_dir / f"evolved_n{self.current_n}_s{i}.txt"
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write("\n".join(lines) + "\n")

                logger.info(f"[AFL_ORCH] Evolved seed written to: {target_file}")
                logger.info(f"[AFL_ORCH] Evolved seed content (first line): {lines[0] if lines else '(empty)'}")

            except (OSError, IOError) as e:
                logger.error(f"[AFL_ORCH] Seed evolution failed for {s_path.name}: {e}")
                print(f"[Error] Seed evolution failed for {s_path.name}: {e}")

    def export_to_unified_ir(self):
        """Behavior deduplication and IR export."""
        if not self.base_dir:
            return

        scan_config = [
            ("CRASH", self.base_dir / "crashes"),
            ("QUEUE", self.base_dir / "queue")
        ]

        final_results = []
        seen_traces = set()
        seen_semantics = set()
        cols = self.schema_dict["columns"]

        afl_showmap_bin = shutil.which("afl-showmap")

        for source_type, d_path in scan_config:
            if not d_path.exists():
                continue

            try:
                files = sorted([f for f in d_path.glob("id:*") if f.is_file()])
            except OSError:
                continue

            kept_count = 0

            for s_file in files:
                try:
                    # 1. Parse metadata
                    meta_parts = s_file.name.split(',')
                    seed_id = meta_parts[0].split(':')[1]
                    discovery_time = 0
                    for part in meta_parts:
                        if part.startswith("time:"):
                            raw_time = part.split(':')[1]
                            if '+' in raw_time:
                                raw_time = raw_time.split('+')[0]
                            discovery_time = int(raw_time)
                            break

                    # 2. Normalize
                    raw_bytes = s_file.read_bytes()
                    clean_content = self.normalizer.normalize(
                        raw_bytes.decode(errors='ignore'),
                        max_cycles=self.config.max_cycles
                    )
                    if not clean_content:
                        continue

                    # 3. Semantic deduplication
                    content_hash = hash(clean_content)
                    if source_type == "QUEUE" and content_hash in seen_semantics:
                        continue
                    seen_semantics.add(content_hash)

                    # 4. Trace deduplication
                    is_hidden_crash = False
                    if source_type == "QUEUE" and afl_showmap_bin:
                        is_hidden_crash = self._trace_dedup(
                            s_file, clean_content, seen_traces, afl_showmap_bin
                        )

                    # 5. Build result
                    kept_count += 1
                    lines = clean_content.splitlines()
                    sparse_timeline = self._build_sparse_timeline(lines, cols)

                    final_is_crash = (source_type == "CRASH") or is_hidden_crash

                    ir_entry = {
                        "exp_id": f"AFL_{source_type}_{seed_id}",
                        "meta_discovery_time_ms": discovery_time,
                        "target_st_path": str(self.st_path),
                        "schema_path": str(self.config.task_root / "input" / "input_schema_v2.json"),
                        "tester_type": "AFL_Mutation",
                        "scan_cycle_ms": 50,
                        "total_cycles": len(lines),
                        "is_crash": final_is_crash,
                        "sparse_timeline": sparse_timeline
                    }
                    final_results.append(ir_entry)

                except (OSError, IOError, ValueError) as e:
                    # Skip problematic files and continue processing other files
                    continue

            if kept_count > 0:
                print(f"    [{source_type}] Processed. Kept: {kept_count}")

        # High-quality filtering
        final_results.sort(key=lambda x: x["meta_discovery_time_ms"], reverse=True)
        final_results = final_results[:self.config.max_eval_cases]

        # Statistical physics execution cost
        for entry in final_results:
            self.total_plc_cycles += entry["total_cycles"]

        # Write to file
        output_path = self.config.output_dir / self.config.ir_filename
        with open(output_path, "w", encoding='utf-8') as f:
            json.dump(final_results, f, indent=2)
        print(f"[√] Dumped to: {output_path}")

    def _trace_dedup(
        self,
        s_file: Path,
        clean_content: str,
        seen_traces: set,
        afl_showmap_bin: str
    ) -> bool:
        """Perform trace deduplication to detect hidden crashes.

        Returns:
            True if hidden crash detected
        """
        is_hidden_crash = False
        try:
            cmd = [
                afl_showmap_bin, "-m", "none", "-q", "-e", "-o", "-",
                "--", str(self.binary_path), "--silent"
            ]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            try:
                trace_output, _ = proc.communicate(
                    input=clean_content.encode('utf-8'),
                    timeout=10
                )

                if proc.returncode != 0:
                    if proc.returncode == 2 or proc.returncode < 0 or proc.returncode > 128:
                        is_hidden_crash = True
                    else:
                        return is_hidden_crash

                if not is_hidden_crash:
                    trace_hash = hash(trace_output)
                    if trace_hash in seen_traces:
                        return False  # skip duplicates
                    seen_traces.add(trace_hash)

            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                is_hidden_crash = True

        except (OSError, subprocess.SubprocessError):
            # afl-showmap call failed, skip trace deduplication
            pass

        return is_hidden_crash

    def _build_sparse_timeline(self, lines: List[str], cols: List[str]) -> Dict[int, Dict[str, str]]:
        """# Build a sparse timeline from the full row.

        Returns:
            Sparse timeline mapping cycle index to variable updates
        """
        sparse_timeline = {}
        for idx, line in enumerate(lines):
            vals = line.split()
            updates = {}
            for col_idx, v in enumerate(vals):
                if v != "0" and v != "0.0":
                    if col_idx < len(cols):
                        updates[cols[col_idx]] = v
            if updates:
                sparse_timeline[str(idx)] = updates
        return sparse_timeline

    def _write_injected_seeds(self) -> int:
        """Write LLM-injected seeds into AFL's input dir as the inverse of
        _build_sparse_timeline: each cycle -> one line of column-ordered, space-separated
        values (schema_dict['columns'] order). Returns the number of seed files written."""
        if not self.initial_seeds:
            return 0
        cols = self.schema_dict.get("columns", [])
        if not cols:
            return 0
        written = 0
        for i, seed in enumerate(self.initial_seeds):
            try:
                tl = (seed or {}).get("sparse_timeline") or {}
                if not tl:
                    continue
                # numeric cycle order
                cyc_keys = sorted(tl.keys(), key=lambda k: int(k))
                lines = []
                for ck in cyc_keys:
                    upd = tl[ck] or {}
                    # case-insensitive var lookup
                    low = {str(k).lower(): v for k, v in upd.items()}
                    row = []
                    for col in cols:
                        v = upd.get(col, low.get(str(col).lower(), "0"))
                        sv = str(v).strip()
                        # AFL seeds are numeric tokens; coerce booleans, blanks -> 0
                        if sv == "" or sv.upper() in ("FALSE", "F", "OFF"):
                            sv = "0"
                        elif sv.upper() in ("TRUE", "T", "ON"):
                            sv = "1"
                        row.append(sv)
                    lines.append(" ".join(row))
                if not lines:
                    continue
                with open(self.config.afl_in_dir / f"seed_inj_{i}.txt", "w") as f:
                    f.write("\n".join(lines) + "\n")
                written += 1
            except (ValueError, OSError, TypeError):
                continue
        if written:
            print(f"[AFL_ORCH] Injected {written} LLM seed(s) into {self.config.afl_in_dir}")
        return written


__all__ = ["AFLOrchestrator"]
