#!/usr/bin/env python3
"""
PLCHaT Main Entry Point

Usage:
    python main.py --help
    python main.py -v                # verify installation
    python main.py -i                # show system information
    python main.py --generate <st_file> -o <output_dir>
    python main.py --pipeline <st_file> -o <output_dir>
    python main.py --demo
"""

from pathlib import Path
import sys
import argparse

# Project root resolution
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from cli import (
    cmd_info, cmd_verify, cmd_cache,
    cmd_matiec_check, cmd_matiec_install_guide,
    cmd_harness_generate, cmd_harness_compile, cmd_coverage_collect,
    cmd_pipeline_run, cmd_pipeline_demo
)
from cli.full_pipeline import cmd_full_run, cmd_full_list


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plchat",
        description="PLCHaT - Unified Agentic Harness for Automated Testing of PLC Programs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py -v                       Verify installation
  python main.py -i                       Show system information
  python main.py --cache-status           Show cache status
  python main.py --cache-clean --all      Clean all caches
  python main.py --matiec-check           Check MatIEC installation

  # Harness generation
  python main.py --generate <st_file> -o <output_dir>

  # Pipeline (end-to-end)
  python main.py --pipeline <st_file> -o <output_dir> -s random
  python main.py --demo                   Run with sample task

  # Full RQ3 pipeline
  python main.py --full 211_StackMin --mode full --assertions
  python main.py --list-tasks             List available tasks

For experiments, see experiments/ directory:
  python experiments/run.py --help
        """
    )

    # ========================================================================
    # System
    # ========================================================================
    parser.add_argument("-v", "--verify", dest="do_verify", action="store_true",
                        help="Verify installation")
    parser.add_argument("-i", "--info", dest="do_info", action="store_true",
                        help="Show system information")

    # Cache management
    parser.add_argument("--cache-status", dest="status", action="store_true",
                        help="Show cache status")
    parser.add_argument("--cache-clean", dest="clean", action="store_true",
                        help="Clean cache")
    parser.add_argument("--all", dest="all", action="store_true",
                        help="With --cache-clean: clean all caches")
    parser.add_argument("--compilation", action="store_true",
                        help="With --cache-clean: clean compilation cache")
    parser.add_argument("--coverage-cache", dest="coverage", action="store_true",
                        help="With --cache-clean: clean coverage cache")
    parser.add_argument("--schema-cache", dest="schema", action="store_true",
                        help="With --cache-clean: clean schema cache")
    parser.add_argument("--harness-cache", dest="harness_cache_clean", action="store_true",
                        help="With --cache-clean: clean harness cache")

    # ========================================================================
    # MatIEC
    # ========================================================================
    parser.add_argument("--matiec-check", dest="do_matiec_check", action="store_true",
                        help="Check MatIEC installation")
    parser.add_argument("--matiec-guide", dest="do_matiec_guide", action="store_true",
                        help="Show MatIEC installation guide")

    # ========================================================================
    # Harness operations
    # ========================================================================
    parser.add_argument("-g", "--generate", dest="gen_st", metavar="ST_FILE",
                        help="Generate a test harness from an ST source file")
    parser.add_argument("--compile", dest="compile_harness", metavar="HARNESS_C",
                        help="Compile a harness.c file to a binary")

    # ========================================================================
    # Pipeline
    # ========================================================================
    parser.add_argument("-p", "--pipeline", dest="pipe_st", metavar="ST_FILE",
                        help="Run the end-to-end testing pipeline on an ST file")
    parser.add_argument("--demo", dest="do_demo", action="store_true",
                        help="Run the pipeline with a sample task")
    parser.add_argument("--coverage", dest="cov_bin", metavar="BINARY",
                        help="Collect coverage from a compiled binary")

    # Full RQ3 pipeline
    parser.add_argument("-f", "--full", dest="full_task", metavar="TASK",
                        help="Run the full RQ3 pipeline on a task (e.g., 211_StackMin)")
    parser.add_argument("--list-tasks", dest="do_list_tasks", action="store_true",
                        help="List available tasks")

    # ========================================================================
    # Shared options
    # ========================================================================
    parser.add_argument("-o", "--output", dest="output",
                        help="Output directory")
    parser.add_argument("-s", "--strategy", dest="strategy", default="random",
                        choices=["random", "llm", "fixed", "mab"],
                        help="Routing strategy (pipeline)")
    parser.add_argument("--profdata",
                        help="Existing profdata path (coverage)")
    parser.add_argument("-m", "--mode", choices=["basic", "llm", "full"], default="basic",
                        help="Execution mode for --full: basic=random, llm=LLM-guided, full=complete RQ3")
    parser.add_argument("-r", "--router", choices=["random", "llm", "mab"], default="random",
                        help="Tool routing strategy for --full")
    parser.add_argument("--assertions", action="store_true",
                        help="With --full: enable assertion generation")
    parser.add_argument("--key-frames", action="store_true",
                        help="With --full: enable keyframe distillation")
    parser.add_argument("--ddmin", action="store_true",
                        help="With --full: enable ddmin reduction")
    parser.add_argument("--suite-reduce", action="store_true",
                        help="With --full: enable suite reduction")
    parser.add_argument("-b", "--budget", type=int, default=300,
                        help="Time budget in seconds for --full")
    parser.add_argument("-n", "--iterations", type=int, default=10,
                        help="Maximum iterations for --full")
    parser.add_argument("--force", action="store_true",
                        help="Force rebuild")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode")

    return parser


def main():
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.harness_cache_clean:
        args.harness = True

    # ========================================================================
    # Route to the requested operation
    # ========================================================================
    if args.do_verify:
        sys.exit(cmd_verify(args))
    if args.do_info:
        cmd_info(args)
        return
    if args.do_matiec_check:
        sys.exit(cmd_matiec_check(args))
    if args.do_matiec_guide:
        cmd_matiec_install_guide(args)
        return
    if args.status or args.clean or args.all or args.compilation \
            or args.coverage or args.schema or args.harness_cache_clean:
        cmd_cache(args)
        return
    if args.gen_st is not None:
        args.st_path = args.gen_st
        sys.exit(cmd_harness_generate(args))
    if args.compile_harness is not None:
        args.harness = args.compile_harness
        sys.exit(cmd_harness_compile(args))
    if args.pipe_st is not None:
        args.st_path = args.pipe_st
        sys.exit(cmd_pipeline_run(args))
    if args.do_demo:
        sys.exit(cmd_pipeline_demo(args))
    if args.cov_bin is not None:
        args.binary = args.cov_bin
        sys.exit(cmd_coverage_collect(args))
    if args.full_task is not None:
        args.task = args.full_task
        sys.exit(cmd_full_run(args))
    if args.do_list_tasks:
        sys.exit(cmd_full_list(args))

    parser.print_help()


if __name__ == "__main__":
    main()
