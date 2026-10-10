#!/usr/bin/env python3
"""
PLCHaT Experiments - Unified Entry Point

This script provides a unified entry point for all RQ experiments:
- RQ1: Harness Generation Effectiveness
- RQ2: Cross-engine Testing Capability
- RQ3: Component Ablation and Strategy Sensitivity

Usage:
    # RQ1 experiments - PLCHaT (ours)
    python -m experiments.run rq1 --baseline ours --table1 --fast

    # RQ1 experiments - Baselines
    python -m experiments.run rq1 --baseline claude-code --table1
    python -m experiments.run rq1 --baseline swe-agent --table1 --external-lib swe-agent=/path/to/swe-agent
    python -m experiments.run rq1 --baseline koziolek --table1 --external-lib koziolek=/path/to/LLM-CodeGen-TestGen

    # RQ2 experiments
    python -m experiments.run rq2 --mode random --fast

    # RQ3 experiments
    python -m experiments.run rq3 --router mab --budget 300

External Libraries Configuration:
    Some baselines require external libraries. Configure them via:
    - Command line: --external-lib name=/path/to/lib
    - Environment: PLCHAT_EXTERNAL_LIB_NAME=/path/to/lib
    - Config file: .claude/external_libs.conf

    Run --help-external-libs for details.
"""

import argparse
import sys
from pathlib import Path

# Project root: experiments/run.py → PROJECT_ROOT (1 parent)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.external_libs import get_manager, print_help as print_external_libs_help


def print_help():
    """Print detailed help information."""
    help_text = """
PLCHaT Experiments - Unified Entry Point

RQ1: Harness Generation Effectiveness
    Evaluates PLCHaT's ability to generate executable test wrappers and
    assertion-based oracles compared to existing approaches.

    Baselines:
      --baseline ours         PLCHaT (default)
      --baseline claude-code  Claude Code/OpenCode style agent
      --baseline swe-agent    SWE-agent (requires --external-lib swe-agent)
      --baseline koziolek     LLM-CodeGen-TestGen (requires --external-lib koziolek)

    Modes:
      --table1       Run Table 1 pipeline quality tests (suite generation mode)
      --table2       Run Table 2 oracle quality tests (assertion generation mode)
      --tasks LIST   Specific tasks to run
      --fast         Fast mode (3 tasks for testing)
      --clean        Clean existing results

    Note:
      Table 1: Pipeline quality metrics (Transpilation, Compilation, Execution)
              No external dependencies required

      Table 2: Oracle quality metrics (Assertions, Trigger Rate)
              Requires LLM API configuration; only the 'ours' baseline is supported
              Setup:
              1. Copy config/local.yaml.example to config/local.yaml
              2. Set up the LLM API (base_url, api_key, model)
              3. Or set environment variables: PLCHAT_LLM_API_KEY, PLCHAT_LLM_BASE_URL

    Input Data Support:
      Table 1 execution uses benchmark's pre-defined test inputs from
      benchmark/<task>/input/input.txt. The harness auto-generates
      input parsing code (read_inputs()) to handle these test cases.

    Example:
      python -m experiments.run rq1 --baseline ours --table1 --fast
      python -m experiments.run rq1 --baseline swe-agent --table1 --external-lib swe-agent=/path/to/swe-agent

RQ2: Cross-engine Testing Capability
    Evaluates different testing engines (AFL++, Random, DSE, Direct LLM)
    on code coverage and fault detection.

    Options:
      --mode MODE       Testing method (random, afl, dse, llm, all)
      --exp-type TYPE   Experiment type (coverage or mutation)
                         coverage: Tests on benchmark_raw, collects coverage metrics
                         mutation: Tests on benchmark_mutated, measures kill rate
      --tasks LIST      Specific tasks to run
      --fast            Fast mode for testing (limits to 1 mutation per task)
      --clean           Clean existing results

    Examples:
      # Coverage test with all engines
      python -m experiments.run rq2 --mode all --exp-type coverage --tasks 211_StackMin

      # Mutation test with random engine
      python -m experiments.run rq2 --mode random --exp-type mutation --tasks 211_StackMin

    Results:
      Saved to output/rq2_results/{coverage,mutation}_results_rq2_{mode}.csv

    API Key Configuration:
      For LLM mode, set OPENAI_API_KEY or configure in config/local.yaml:
        tools:
          direct_llm:
            api_key: "your-api-key"

RQ3: Component Ablation Studies
    Evaluates the impact of individual harness components on testing effectiveness.

    Configurations:
      C1     Full Framework (distill + oracle)
      C2     w/o Distill (naive truncation)
      C3     w/o Trace Distillation (raw trace)
      C4     w/o Active Oracle in feedback
      C0     No inter-round feedback
      E_raw  Raw output (no oracle/metrics)

    Options:
      --config ID         Ablation config (C1, C2, C3, C4, C0, E_raw)
      --tasks LIST        Specific tasks to run
      --max-mutations N   Maximum mutations per task
      --fast              Fast mode (3 tasks, shorter budget)

    Examples:
      python -m experiments.run rq3 --config C1 --fast
      python -m experiments.run rq3 --config C4 --tasks 211_StackMin 212_FindMinMaxValues

External Libraries:
    Some baselines require external libraries. Use:
      --external-lib name=/path/to/lib
      --help-external-libs    Show detailed help
      --check-external-libs   Check current configuration

Results Directory:
    All results are saved to: output/rq{N}_results/
    RQ3 results: results/rq3/ with per-config subdirectories (rq3_C1, rq3_C2, etc.)

RQ3 Result Collection:
    Use --collect to aggregate all summary.json files into a single CSV:
    python -m experiments.rq3.rq3_runner_v3 --collect --collect-out results/rq3_collected.csv
"""
    print(help_text)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PLCHaT Experiments Unified Entry Point",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("rq", nargs='?', choices=["rq1", "rq2", "rq3"],
                        help="Research question to run (can be omitted for --help-external-libs)")
    parser.add_argument("--help-detail", action="store_true",
                        help="Show detailed help information")
    parser.add_argument("--help-external-libs", action="store_true",
                        help="Show help on configuring external libraries")
    parser.add_argument("--check-external-libs", action="store_true",
                        help="Check external libraries configuration")

    # Common arguments
    parser.add_argument("--tasks", nargs="+", default=None,
                        help="Specific tasks to run")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode for testing")
    parser.add_argument("--clean", action="store_true",
                        help="Clean existing results")

    # External libraries
    parser.add_argument("--external-lib", action="append", dest="external_libs",
                        metavar="NAME=PATH",
                        help="Specify external library path (e.g., swe-agent=/path/to/swe-agent)")

    # RQ1 specific
    parser.add_argument("--baseline", default="ours",
                        choices=["ours", "claude-code", "swe-agent", "koziolek"],
                        help="Baseline method for RQ1 (default: ours)")
    parser.add_argument("--table1", action="store_true",
                        help="Run Table 1 pipeline quality tests (RQ1)")
    parser.add_argument("--table2", action="store_true",
                        help="Run Table 2 oracle quality tests (RQ1)")

    # RQ2 specific
    parser.add_argument("--mode", default="random",
                        choices=["random", "afl", "dse", "llm", "all"],
                        help="Testing method (RQ2)")
    parser.add_argument("--exp-type", default="mutation",
                        choices=["coverage", "mutation"],
                        help="Experiment type (RQ2): coverage or mutation")

    # RQ3 specific
    parser.add_argument("--config", help="Ablation config (RQ3): C1, C2, C3, C4, C0, E_raw")
    parser.add_argument("--max-mutations", type=int, default=None,
                        help="Maximum mutations per task (RQ3)")

    args = parser.parse_args()

    # Handle help options that don't require rq argument
    if args.help_external_libs:
        print_external_libs_help()
        return

    if args.check_external_libs:
        get_manager().print_status()
        return

    # Require rq for other operations
    if not args.rq:
        parser.print_help()
        return

    if args.help_detail:
        print_help()
        return

    # Configure external libraries from command line
    manager = get_manager()
    if args.external_libs:
        for lib_spec in args.external_libs:
            if "=" not in lib_spec:
                print(f"Error: Invalid external lib specification: {lib_spec}")
                print("Expected format: --external-lib name=/path/to/lib")
                sys.exit(1)
            name, path = lib_spec.split("=", 1)
            manager.set_lib_path(name, Path(path))

    print(f"\nPLCHaT Experiments")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"RQ: {args.rq}")
    if args.rq == "rq1":
        print(f"Baseline: {args.baseline}")
    print(f"Fast mode: {args.fast}")
    print()

    if args.rq == "rq1":
        # Check baseline requirements
        is_ready, msg = manager.check_baseline_requirements(args.baseline)
        if not is_ready:
            print(f"Error: {msg}")
            print("\nUse --external-lib to specify library paths, or --help-external-libs for help.")
            sys.exit(1)

        # Get and run the appropriate baseline
        try:
            runner = manager.get_baseline_runner(
                args.baseline,
                fast_mode=args.fast
            )
            runner.init_env(clean_existing=args.clean)

            if args.table1:
                results = runner.run_table1_batch(tasks=args.tasks)
                print(f"\n✓ RQ1 Table 1 completed: {len(results)} tasks")
                print(f"  Results: {runner.results_table1}")
            elif args.table2:
                # Check if runner supports table2
                if hasattr(runner, 'run_table2_full_batch'):
                    results = runner.run_table2_full_batch(tasks=args.tasks)
                    print(f"\n✓ RQ1 Table 2 completed: {len(results)} tasks")
                    print(f"  Results: {runner.results_table2}")
                else:
                    print(f"✗ {args.baseline} baseline does not support Table 2 (assertion generation)")
                    print(f"  Table 2 is only supported by the 'ours' baseline")
            else:
                print("Please specify --table1 or --table2")

        except Exception as e:
            print(f"Error running {args.baseline} baseline: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    elif args.rq == "rq2":
        from experiments.rq2.runner import RQ2Runner, EXPERIMENT_COVERAGE, EXPERIMENT_MUTATION
        runner = RQ2Runner(
            mode=args.mode,
            experiment_type=args.exp_type,
            fast_mode=args.fast
        )
        runner.init_env(clean_existing=args.clean)

        tasks = runner.list_tasks(include=args.tasks)
        print(f"Running RQ2: type={args.exp_type}, mode={args.mode}, tasks={len(tasks)}")

        for task in tasks:
            print(f"\n  Processing: {task}")
            results = runner.run_task_batch(
                task,
                methods=None if args.mode == "all" else [args.mode],
                max_mutations=1 if args.fast else None
            )
            print(f"    Completed: {len(results)} results")

        print(f"\n✓ RQ2 completed")
        print(f"  Results: {runner.results_file}")

    elif args.rq == "rq3":
        # RQ3 uses rq3_runner_v3.py as the verified implementation
        from experiments.rq3.rq3_runner_v3 import main as rq3_main

        if not args.config:
            print("Error: --config is required for RQ3")
            print("Available configs: C1, C2, C3, C4, C0, E_raw")
            sys.exit(1)

        # Build args for rq3_runner_v3
        rq3_args = argparse.Namespace()
        rq3_args.task = args.tasks[0] if args.tasks else "211_StackMin"
        rq3_args.config = args.config
        rq3_args.configs = None
        rq3_args.mutation = None
        rq3_args.mutation_all = False
        rq3_args.full_dataset = False
        rq3_args.phase1_only = False
        rq3_args.task_workers = 5
        rq3_args.budget = 300
        rq3_args.cases_per_iter = 5
        rq3_args.max_iterations = 200
        rq3_args.hang_timeout = 0
        rq3_args.skip_existing = False
        rq3_args.only_tasks = None
        rq3_args.debug = False
        rq3_args.local_api = False
        rq3_args.collect = False
        rq3_args.collect_out = str(PROJECT_ROOT / "results" / "rq3" / "rq3_collected.csv")

        # Override fast mode to reduce budget for quick testing
        if args.fast:
            rq3_args.budget = 60
            rq3_args.max_iterations = 5
            rq3_args.cases_per_iter = 2

        # Call rq3_runner_v3 main with sys.argv hack
        old_argv = sys.argv
        sys.argv = ["rq3_runner_v3.py",
                    f"--task={rq3_args.task}",
                    f"--config={rq3_args.config}",
                    f"--budget={rq3_args.budget}",
                    f"--cases-per-iter={rq3_args.cases_per_iter}",
                    f"--max-iterations={rq3_args.max_iterations}"]
        try:
            rq3_main()
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    main()
