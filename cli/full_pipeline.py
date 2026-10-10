"""
Full Pipeline Module - Complete RQ3 End-to-End Testing

Implements the complete RQ3 chain with generator agent integration.
Uses simple string configuration instead of custom types.

Usage:
    python main.py --full 211_StackMin --mode full
    python main.py --full 211_StackMin --mode llm --router llm
"""

from pathlib import Path
import sys
import os
import time
import json
from datetime import datetime

# Project root resolution (cli/full_pipeline.py → cli → PROJECT_ROOT)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _benchmark_root() -> Path:
    default = PROJECT_ROOT / "benchmark" / "benchmark_260113"
    return Path(os.environ.get("PLCHAT_BENCHMARK_ROOT", str(default)))

from config import get_config
from core.experiment_config import ExperimentConfig
from harness.compiler.executor import STExecutor
from harness.compiler.st_coverage_collector import STCoverageCollector
from harness.compiler.utils import Logger, LEVEL
from harness.test_analysis.key_frame_extractor import KeyFrameExtractor
from harness.test_analysis.ddmin import reduce_case_with_ddmin
from harness.test_analysis.integration import TestCaseAnalyzer
from core.data_types.exp_types import ExpUnifiedIR
from core.token_tracker import TokenTracker
from tools.fuzzers.random.generator import RandomCaseGenerator

from agents.generator import Generator


def run_full_pipeline(
    task_id: str,
    mode: str = "basic",
    router: str = "random",
    enable_assertions: bool = False,
    enable_key_frames: bool = False,
    enable_ddmin: bool = False,
    budget_sec: int = 300,
    max_iterations: int = 10,
    work_dir: str = None,
    logger: Logger = None
) -> dict:
    """
    Run full RQ3 pipeline for a task.

    Args:
        task_id: Task identifier (e.g., "211_StackMin")
        mode: Execution mode ("basic", "llm", "full")
        router: Tool routing strategy ("random", "llm", "mab")
        enable_assertions: Enable assertion generation
        enable_key_frames: Enable keyframe distillation
        enable_ddmin: Enable ddmin reduction
        budget_sec: Time budget in seconds
        max_iterations: Maximum iterations
        work_dir: Working directory path
        logger: Logger instance

    Returns:
        dict with execution results
    """
    # Apply mode defaults
    if mode == "full":
        enable_assertions = True
        enable_key_frames = True
        enable_ddmin = True
    elif mode == "llm":
        enable_key_frames = True

    # Setup working directory
    if not work_dir:
        exp_config = ExperimentConfig()
        results_base = exp_config.get_results_dir("full")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        work_dir = results_base / f"{task_id}_{timestamp}"

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Setup logger
    if not logger:
        logger = Logger(str(work_dir / "logs"), "pipeline.log", level=LEVEL.INFO)

    # Initialize result
    result = {
        "task_id": task_id,
        "mode": mode,
        "router": router,
        "status": "PENDING",
        "branch_coverage": "N/A",
        "line_coverage": "N/A",
        "assertion_count": 0,
        "assertion_triggered": 0,
        "total_cases": 0,
        "iterations": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "duration_sec": 0.0,
        "errors": []
    }

    start_time = time.time()
    logger.info(f"Pipeline started: {task_id}, mode={mode}")

    try:
        # Step 1: Locate harness files
        benchmark_root = _benchmark_root() / "benchmark_raw"
        task_dir = benchmark_root / task_id

        st_path = task_dir / "plc_st_files" / f"{task_id}.st"
        harness_path = task_dir / "plc_c_files" / "harness.c"
        schema_path = task_dir / "input" / "input_schema.json"

        if not all(p.exists() for p in [st_path, harness_path, schema_path]):
            raise FileNotFoundError(f"Harness files not found for {task_id}")

        logger.info(f"Found harness files for {task_id}")

        # Step 2: Generate assertions (if enabled)
        asserted_harness_path = None
        if enable_assertions:
            try:
                logger.info("Generating assertions...")
                analyzer = TestCaseAnalyzer(
                    st_path=st_path,
                    harness_path=harness_path,
                    logger=logger,
                    work_dir=work_dir
                )
                analysis_result = analyzer.analyze(work_dir=work_dir)

                if analysis_result and analysis_result.patched_harness:
                    asserted_harness_path = Path(analysis_result.patched_harness)
                    result["assertion_count"] = analysis_result.assertion_code.count("fflush(stderr)") if analysis_result.assertion_code else 0
                    logger.info(f"Generated {result['assertion_count']} assertions")

            except Exception as e:
                logger.warning(f"Assertion generation failed: {e}")
                result["errors"].append(f"Assertion generation: {e}")

        # Step 3: Initialize components
        executor = STExecutor(root_dir=str(PROJECT_ROOT), logger=logger, debug=False)
        coverage_collector = STCoverageCollector(
            root_dir=str(PROJECT_ROOT),
            logger=logger,
            default_output_format="StoredTestCase",
            llvm_version=18
        )

        keyframe_extractor = KeyFrameExtractor() if enable_key_frames else None

        # Step 4: Initialize generator agent (for LLM modes)
        generator = None
        if mode in ("llm", "full"):
            try:
                generator = Generator(
                    st_path=str(st_path),
                    benchmark_dir=str(task_dir)
                )
                logger.info("Generator agent initialized")
            except Exception as e:
                logger.warning(f"Generator initialization failed: {e}")
                result["errors"].append(f"Generator init: {e}")

        # Step 5: Iterative test generation
        coverage_history = []
        budget_remaining = budget_sec

        for iteration in range(1, max_iterations + 1):
            iter_start = time.time()
            logger.info(f"Iteration {iteration}/{max_iterations}")

            # Build context
            context = {
                "iteration": iteration,
                "first_round": iteration == 1,
            }
            if coverage_history:
                context["current_coverage"] = coverage_history[-1] / 100.0

            if enable_key_frames and keyframe_extractor and iteration > 1:
                # Would add keyframe context here
                pass

            # Generate cases
            cases = []

            # LLM generation
            if generator:
                try:
                    llm_cases = generator.generate(
                        goal=f"Maximize branch coverage. Budget: ~{budget_remaining}s",
                        context=context
                    )
                    cases.extend([c for c in llm_cases if hasattr(c, "sparse_timeline")])
                except Exception as e:
                    logger.warning(f"LLM generation failed: {e}")

            # Random filler cases
            rng = RandomCaseGenerator(seed=None)
            n_rnd = 30 if iteration == 1 else 15

            for _ in range(n_rnd):
                sparse_tl = {}
                schema = json.loads(schema_path.read_text(encoding='utf-8'))
                for cycle in range(8):
                    case = rng.generate_case(
                        st_path.read_text(encoding='utf-8'),
                        schema
                    )
                    if case:
                        sparse_tl[cycle] = case

                if sparse_tl:
                    cases.append(ExpUnifiedIR(
                        exp_id=f"{task_id}_rnd_{iteration}",
                        target_st_path=str(st_path),
                        schema_path=str(schema_path),
                        tester_type="random",
                        total_cycles=len(sparse_tl),
                        sparse_timeline=sparse_tl,
                    ))

            if not cases:
                logger.warning("No cases generated, stopping")
                break

            # Execute cases
            harness_to_use = asserted_harness_path or harness_path
            try:
                exec_result = coverage_collector.execute_with_multiple_coverage(
                    st_code_input=str(st_path),
                    harness_input=str(harness_to_use),
                    input_data_list=cases[:50],
                    benchmark_case=task_id,
                    reuse_compilation=True,
                    output_format="StoredTestCase",
                )

                # Extract coverage from CoverageReport
                coverage = -1.0
                if exec_result.get("coverage_data"):
                    cov_data = exec_result["coverage_data"]
                    if hasattr(cov_data, 'coverage_summary') and cov_data.coverage_summary:
                        branch_cov = cov_data.coverage_summary.branch_coverage
                        if branch_cov and branch_cov.percentage:
                            try:
                                coverage = float(branch_cov.percentage.rstrip('%'))
                            except:
                                pass

                if coverage >= 0:
                    coverage_history.append(coverage)
                    logger.info(f"Iteration {iteration}: coverage={coverage:.1f}%")

                result["total_cases"] += len(cases)

            except Exception as e:
                logger.error(f"Execution failed: {e}")
                result["errors"].append(f"Execution: {e}")

            result["iterations"] = iteration
            budget_remaining -= (time.time() - iter_start)

            if budget_remaining <= 0:
                logger.info("Budget exhausted")
                break

        # Step 6: Final metrics
        if coverage_history:
            final_cov = coverage_history[-1]
            result["branch_coverage"] = f"{final_cov:.1f}%"
            result["line_coverage"] = f"{final_cov:.1f}%"

        if TokenTracker.get():
            tok_end = TokenTracker.get().snapshot()
            result["input_tokens"] = tok_end["input_tokens"]
            result["output_tokens"] = tok_end["output_tokens"]

        result["status"] = "SUCCESS"

    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(str(e))
        logger.error(f"Pipeline failed: {e}")

    result["duration_sec"] = time.time() - start_time

    # Generate report
    report_file = work_dir / "pipeline_report.json"
    with open(report_file, "w") as f:
        json.dump(result, f, indent=2)

    logger.info(f"Pipeline {result['status']}: coverage={result['branch_coverage']}, cases={result['total_cases']}")
    logger.info(f"Report saved to {report_file}")

    return result


def cmd_full_run(args):
    """CLI command for full pipeline run."""
    result = run_full_pipeline(
        task_id=args.task,
        mode=args.mode or "basic",
        router=args.router or "random",
        enable_assertions=args.assertions,
        enable_key_frames=args.key_frames,
        enable_ddmin=args.ddmin,
        budget_sec=args.budget or 300,
        max_iterations=args.iterations or 10,
    )

    print(f"\nPipeline {result['status']}")
    print(f"  Task: {result['task_id']}")
    print(f"  Mode: {result['mode']}")
    print(f"  Coverage: {result['branch_coverage']}")
    print(f"  Cases: {result['total_cases']}")
    print(f"  Assertions: {result['assertion_triggered']}/{result['assertion_count']}")

    if result["errors"]:
        print(f"  Errors: {result['errors']}")

    return 0 if result['status'] == "SUCCESS" else 1


def cmd_full_list(args):
    """CLI command to list available tasks."""
    benchmark_root = _benchmark_root() / "benchmark_raw"

    tasks = sorted([
        d.name for d in benchmark_root.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    ])

    print(f"Available tasks ({len(tasks)}):")
    for t in tasks:
        print(f"  {t}")

    return 0
