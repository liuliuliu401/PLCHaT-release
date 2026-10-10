#!/usr/bin/env python3
"""
DSE Fuzzer - CLI Entry Point for Dynamic Symbolic Execution

Usage:
    python -m tools.fuzzers.dse.run_dse --task 211_StackMin
    python -m tools.fuzzers.dse.run_dse --all --output temp/dse_results

Design:
    - Thin CLI wrapper around DSETool (BaseTool implementation)
    - Handles file I/O and batch processing
    - Delegates core logic to DSETool.execute()
"""

from pathlib import Path
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed

# Project root resolution - adjust parent count based on file depth
# tools/fuzzers/dse/run_dse.py → 4 parents (dse → fuzzers → tools → PROJECT_ROOT)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import PLCHaT components
from tools.fuzzers.dse.dse_tool import DSETool
from core.protocols.action_protocol import ToolCallRequest, ActionType


# ============================================================================
# CONFIGURATION
# ============================================================================

BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_raw"
OUTPUT_DIR = PROJECT_ROOT / "temp" / "dse_results"
LOG_DIR = PROJECT_ROOT / "temp" / "logs"

# Default configuration aligned with DSETool
DEFAULT_CONFIG = {
    "max_unwind": 10,
    "max_depth": 50,          # Aligned with DSETool default
    "max_cycles": 50,         # Aligned with DSETool default
    "scan_cycle_ms": 50,      # Aligned with DSETool default
    "timeout": 120,
    "plateau_limit": 20,      # Stagnation threshold (aligned with Random Fuzzer)
    "max_workers": 1,         # Parallel workers (1 = serial, >1 = parallel)
    "task_timeout": 300,     # Per-task timeout (seconds)
    "with_coverage": True,
    "debug": False,
}


# ============================================================================
# CLI WRAPPER
# ============================================================================

class DSECli:
    """
    CLI wrapper for DSETool.

    Handles:
    - Batch task processing
    - Result file I/O
    - Logging configuration
    - Progress reporting

    Core DSE logic is delegated to DSETool.execute().
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize CLI with configuration."""
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.logger = self._setup_logging()

        # Initialize DSETool once for all tasks
        self._tool = DSETool(
            benchmark_root=str(PROJECT_ROOT),
            debug=self.config["debug"]
        )

    def _setup_logging(self) -> logging.Logger:
        """Setup logging to file and console."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = LOG_DIR / f"dse_{timestamp}.log"

        logging.basicConfig(
            level=logging.DEBUG if self.config["debug"] else logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

        return logging.getLogger(__name__)

    def run_single_task(
        self,
        task_name: str,
        st_file: Path,
        output_dir: Path
    ) -> Dict[str, Any]:
        """
        Run DSE for a single task.

        Args:
            task_name: Benchmark task name
            st_file: Path to ST source file
            output_dir: Output directory for results

        Returns:
            Dict with execution results
        """
        self.logger.info("=" * 70)
        self.logger.info(f"DSE CLI: {task_name}")
        self.logger.info("=" * 70)

        # Build schema path
        schema_path = st_file.parent.parent / "input" / "input_schema_v2.json"

        # Create ToolCallRequest for DSETool
        request = ToolCallRequest(
            action_id=f"dse_cli_{task_name}",
            action_type=ActionType.GENERATE,
            tool_name="dse",
            parameters={
                "task_name": task_name,
                "st_code_path": str(st_file),
                "schema_path": str(schema_path) if schema_path.exists() else None,
                "max_depth": self.config["max_depth"],
                "max_cycles": self.config["max_cycles"],
                "scan_cycle_ms": self.config["scan_cycle_ms"],
                "timeout": self.config["timeout"],
                "plateau_limit": self.config["plateau_limit"],
                "with_coverage": self.config["with_coverage"],
            }
        )

        # Execute via DSETool
        response = self._tool.execute(request)

        # Save results
        output_dir.mkdir(parents=True, exist_ok=True)

        results_file = output_dir / f"{task_name}_results.json"
        with open(results_file, 'w') as f:
            json.dump({
                "task_name": task_name,
                "config": self.config,
                "response": {
                    "status": response.status,
                    "data": response.data,
                    "error_message": response.error_message,
                    "execution_time_ms": response.execution_time_ms
                }
            }, f, indent=2)

        self.logger.info(f"  ✓ Saved: {results_file}")

        # Return status
        if response.status == "success":
            stats = response.data.get("statistics", {})
            self.logger.info(f"  ✓ Generated: {response.data.get('total_generated', 0)} test cases")
            self.logger.info(f"  ✓ Branches: {stats.get('covered_branches', 'N/A')}")
            self.logger.info(f"  ✓ Line cov: {stats.get('line_cov', 'N/A')}")
            self.logger.info(f"  ✓ Branch cov: {stats.get('branch_cov', 'N/A')}")

            return {
                "status": "success",
                "test_cases": response.data.get("total_generated", 0),
                "covered_branches": stats.get("covered_branches", 0),
                "output_file": str(results_file)
            }
        else:
            self.logger.error(f"  ✗ Failed: {response.error_message}")
            return {
                "status": "error",
                "error": response.error_message
            }

    def _run_single_with_timeout(
        self,
        task_name: str,
        st_file: Path,
        output_dir: Path,
        timeout_sec: int
    ) -> Dict[str, Any]:
        """
        Run a single task with timeout protection.

        Args:
            task_name: Task name
            st_file: ST file path
            output_dir: Output directory
            timeout_sec: Timeout in seconds

        Returns:
            Result dict with status and data
        """
        import threading
        import queue

        result_queue = queue.Queue()

        def worker():
            try:
                result = self.run_single_task(task_name, st_file, output_dir)
                result_queue.put(result)
            except Exception as e:
                result_queue.put({"status": "error", "error": str(e)})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout_sec)

        if thread.is_alive():
            self.logger.warning(f"  ⚠ Task {task_name} timed out after {timeout_sec}s")
            return {"status": "error", "error": f"Timeout after {timeout_sec}s"}

        try:
            return result_queue.get_nowait()
        except queue.Empty:
            return {"status": "error", "error": "No result produced"}

    def run_all_tasks(
        self,
        output_dir: Path,
        pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run DSE for all tasks in benchmark with parallel execution support.

        Args:
            output_dir: Output directory for results
            pattern: Optional pattern to filter tasks (e.g., "21*")

        Returns:
            Dict with aggregated results
        """
        if not BENCHMARK_ROOT.exists():
            self.logger.error(f"Benchmark directory not found: {BENCHMARK_ROOT}")
            return {"status": "error", "error": "Benchmark not found"}

        # Find all ST files
        task_files = []
        for test_dir in sorted(BENCHMARK_ROOT.iterdir()):
            if not test_dir.is_dir():
                continue

            if pattern and not test_dir.name.match(pattern):
                continue

            st_dir = test_dir / "plc_st_files"
            if not st_dir.exists():
                continue

            for st_file in sorted(st_dir.glob("*.st")):
                task_files.append((test_dir.name, st_file))

        if not task_files:
            self.logger.warning("No ST files found!")
            return {"status": "error", "error": "No ST files"}

        max_workers = self.config.get("max_workers", 1)
        task_timeout = self.config.get("task_timeout", 300)

        self.logger.info(f"Found {len(task_files)} tasks to process")
        self.logger.info(f"Execution mode: {'parallel' if max_workers > 1 else 'serial'}")
        self.logger.info(f"Max workers: {max_workers}")
        self.logger.info(f"Per-task timeout: {task_timeout}s")

        # Initialize results
        results = {
            "total": len(task_files),
            "success": 0,
            "failed": 0,
            "timeout": 0,
            "start_time": datetime.now().isoformat(),
            "tasks": [],
            "config": self.config
        }

        start_time = datetime.now()

        if max_workers == 1:
            # Serial execution
            for i, (task_name, st_file) in enumerate(task_files, 1):
                self.logger.info(f"\n[{i}/{len(task_files)}] Processing {task_name}")

                task_output = output_dir / task_name
                result = self._run_single_with_timeout(
                    task_name, st_file, task_output, task_timeout
                )

                self._update_results(results, task_name, result)

        else:
            # Parallel execution
            self.logger.info(f"\nStarting parallel execution with {max_workers} workers")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_task = {}
                for task_name, st_file in task_files:
                    task_output = output_dir / task_name
                    future = executor.submit(
                        self._run_single_with_timeout,
                        task_name, st_file, task_output, task_timeout
                    )
                    future_to_task[future] = task_name

                # Process completed tasks
                completed = 0
                for future in as_completed(future_to_task):
                    completed += 1
                    task_name = future_to_task[future]
                    self.logger.info(f"\n[{completed}/{len(task_files)}] Completed {task_name}")

                    try:
                        result = future.result()
                        self._update_results(results, task_name, result)
                    except Exception as e:
                        self.logger.error(f"Task {task_name} raised exception: {e}")
                        self._update_results(results, task_name, {"status": "error", "error": str(e)})

        # Finalize
        end_time = datetime.now()
        results["end_time"] = end_time.isoformat()
        results["duration_seconds"] = (end_time - start_time).total_seconds()

        # Save detailed summary
        summary_file = output_dir / "dse_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(results, f, indent=2)

        # Generate human-readable report
        report_file = output_dir / "dse_report.txt"
        self._generate_report(results, report_file)

        self.logger.info("=" * 70)
        self.logger.info("DSE CLI Summary")
        self.logger.info("=" * 70)
        self.logger.info(f"Total: {results['total']}")
        self.logger.info(f"Success: {results['success']}")
        self.logger.info(f"Failed: {results['failed']}")
        self.logger.info(f"Timeout: {results['timeout']}")
        self.logger.info(f"Duration: {results['duration_seconds']:.1f}s")
        self.logger.info(f"Summary: {summary_file}")
        self.logger.info(f"Report: {report_file}")

        return results

    def _update_results(self, results: Dict[str, Any], task_name: str, result: Dict[str, Any]):
        """Update results dict with a single task result."""
        results["tasks"].append({
            "task_name": task_name,
            "result": result
        })

        if result["status"] == "success":
            results["success"] += 1
        elif "timeout" in result.get("error", "").lower():
            results["timeout"] += 1
            results["failed"] += 1
        else:
            results["failed"] += 1

    def _generate_report(self, results: Dict[str, Any], report_file: Path):
        """Generate human-readable report."""
        with open(report_file, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("DSE Fuzzer - Execution Report\n")
            f.write("=" * 70 + "\n\n")

            f.write(f"Start Time: {results['start_time']}\n")
            f.write(f"End Time: {results['end_time']}\n")
            f.write(f"Duration: {results['duration_seconds']:.1f}s\n\n")

            f.write(f"Total Tasks: {results['total']}\n")
            f.write(f"Success: {results['success']}\n")
            f.write(f"Failed: {results['failed']}\n")
            f.write(f"Timeout: {results['timeout']}\n\n")

            f.write("-" * 70 + "\n")
            f.write("Task Details:\n")
            f.write("-" * 70 + "\n\n")

            for task in results["tasks"]:
                task_name = task["task_name"]
                result = task["result"]

                if result["status"] == "success":
                    f.write(f"✓ {task_name}\n")
                    f.write(f"  Test Cases: {result.get('test_cases', 'N/A')}\n")
                    f.write(f"  Branches: {result.get('covered_branches', 'N/A')}\n")
                    f.write(f"  Output: {result.get('output_file', 'N/A')}\n")
                else:
                    f.write(f"✗ {task_name}\n")
                    f.write(f"  Error: {result.get('error', 'Unknown')}\n")
                f.write("\n")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="DSE Fuzzer - Dynamic Symbolic Execution for ST Programs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run single task
  python -m tools.fuzzers.dse.run_dse --task 211_StackMin

  # Run all tasks
  python -m tools.fuzzers.dse.run_dse --all

  # Run with pattern
  python -m tools.fuzzers.dse.run_dse --all --pattern "21*"

  # Debug mode
  python -m tools.fuzzers.dse.run_dse --task 211_StackMin --debug
        """
    )

    parser.add_argument("--task", type=str, help="Single task name (e.g., 211_StackMin)")
    parser.add_argument("--all", action="store_true", help="Run all tasks in benchmark")
    parser.add_argument("--pattern", type=str, help="Filter tasks by pattern (e.g., '21*')")
    parser.add_argument("--output", type=str, default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--max-unwind", type=int, default=10, help="Max loop unrolling (default: 10)")
    parser.add_argument("--max-depth", type=int, default=50, help="Max exploration depth (default: 50)")
    parser.add_argument("--max-cycles", type=int, default=50, help="Max cycles per test case (default: 50)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per task (default: 120s)")
    parser.add_argument("--plateau-limit", type=int, default=20, help="Stagnation threshold (default: 20)")
    parser.add_argument("--max-workers", type=int, default=1, help="Parallel workers (default: 1=serial)")
    parser.add_argument("--task-timeout", type=int, default=300, help="Per-task timeout in seconds (default: 300)")
    parser.add_argument("--no-coverage", action="store_true", help="Disable coverage collection")

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Configure CLI
    config = {
        "max_unwind": args.max_unwind,
        "max_depth": args.max_depth,
        "max_cycles": args.max_cycles,
        "timeout": args.timeout,
        "plateau_limit": args.plateau_limit,
        "max_workers": args.max_workers,
        "task_timeout": args.task_timeout,
        "with_coverage": not args.no_coverage,
        "debug": args.debug
    }

    cli = DSECli(config)

    # Run
    if args.task:
        # Single task mode
        task_dir = BENCHMARK_ROOT / args.task
        st_dir = task_dir / "plc_st_files"
        if not st_dir.exists():
            print(f"Error: Task not found: {args.task}")
            return 1

        st_files = list(st_dir.glob("*.st"))
        if not st_files:
            print(f"Error: No ST files found in {st_dir}")
            return 1

        st_file = sorted(st_files)[0]
        result = cli.run_single_task(
            task_name=args.task,
            st_file=st_file,
            output_dir=output_dir / args.task
        )

        if result["status"] == "success":
            print(f"\n[+] Success: {result['test_cases']} test cases, {result['covered_branches']} branches")
            return 0
        else:
            print(f"\n[!] Failed: {result.get('error', 'Unknown error')}")
            return 1

    elif args.all:
        # Batch mode
        result = cli.run_all_tasks(
            output_dir=output_dir,
            pattern=args.pattern
        )

        if result.get("status") != "error":
            print(f"\n[+] Batch complete: {result['success']}/{result['total']} succeeded")
            return 0
        else:
            print(f"\n[!] Batch failed")
            return 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
