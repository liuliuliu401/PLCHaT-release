#!/usr/bin/env python3
"""
PLCHaT End-to-End Testing Framework - Unified Entry Point

This script provides a unified, flexible entry point for end-to-end testing:
- Demo Mode: Interactive ReAct loop for debugging/demonstration
- Experiment Mode: Complete RQ3 runner with assertion generation, keyframes, DDMIN
- Rich Configuration: Termination conditions, feature toggles, routing strategies

Usage:
    # Quick demo with default settings
    python run.py --task 211_StackMin

    # Full experiment with all features
    python run.py --task 211_StackMin --mode experiment --enable-all

    # Custom configuration
    python run.py --task 211_StackMin --mode demo \\
        --router llm --budget 120 --stop-when agent-done

    # Mutation testing
    python run.py --task 211_StackMin --mutation mutation_0 \\
        --mode experiment --enable-assertions --enable-ddmin

Results:
    Demo mode:     output/demo/<task_id>_<timestamp>/
    Experiment:    results/rq3/rq3_<config>/<task_id>/run_*/
    Summary:       Console output + JSON reports
"""

import sys
import os
import argparse
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import after path setup
from harness.compiler.utils import Logger, LEVEL
from config import get_config


# ============================================================================
# Configuration Classes
# ============================================================================

class TerminationConfig:
    """Controls when the testing loop should terminate."""

    CONDITIONS = ["budget-elapsed", "agent-done", "coverage-plateau", "max-iterations"]

    def __init__(self, condition: str = "budget-elapsed", plateau_iters: int = 3, plateau_delta: float = 1.0):
        """
        Args:
            condition: Primary termination condition
            plateau_iters: Iterations with <plateau_delta% coverage gain to consider plateaued
            plateau_delta: Coverage gain percentage threshold for plateau detection
        """
        if condition not in self.CONDITIONS:
            raise ValueError(f"Invalid condition: {condition}. Choose from {self.CONDITIONS}")
        self.condition = condition
        self.plateau_iters = plateau_iters
        self.plateau_delta = plateau_delta


class FeatureConfig:
    """Controls which analysis features are enabled."""

    def __init__(
        self,
        enable_assertions: bool = False,
        enable_keyframes: bool = False,
        enable_ddmin: bool = False,
        enable_suite_reduction: bool = False,
        enable_ground_truth_verify: bool = True
    ):
        self.assertions = enable_assertions
        self.keyframes = enable_keyframes
        self.ddmin = enable_ddmin
        self.suite_reduction = enable_suite_reduction
        self.ground_truth_verify = enable_ground_truth_verify

    @classmethod
    def from_preset(cls, preset: str) -> 'FeatureConfig':
        """Create feature config from preset name."""
        presets = {
            "minimal": cls(False, False, False, False, False),
            "basic": cls(False, False, False, False, True),
            "assertions-only": cls(True, False, False, False, True),
            "analysis": cls(True, True, True, False, True),
            "full": cls(True, True, True, True, True),
        }
        if preset not in presets:
            raise ValueError(f"Unknown preset: {preset}. Choose from {list(presets.keys())}")
        return presets[preset]


class RouterConfig:
    """Controls the agent's tool routing strategy."""

    STRATEGIES = ["random", "llm", "mab", "fixed"]

    def __init__(self, strategy: str = "random", tool_params: Optional[Dict[str, Any]] = None):
        """
        Args:
            strategy: Routing strategy
            tool_params: Tool-specific parameters (e.g., {"random_fuzzing": {"budget_sec": 30}})
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}. Choose from {self.STRATEGIES}")
        self.strategy = strategy
        self.tool_params = tool_params or {}


class ExperimentConfig:
    """Complete configuration for an end-to-end test run."""

    def __init__(
        self,
        task_id: str,
        mode: str = "demo",
        mutation: Optional[str] = None,
        budget_sec: int = 300,
        max_iterations: int = 200,
        cases_per_iteration: int = 5,
        termination: Optional[TerminationConfig] = None,
        features: Optional[FeatureConfig] = None,
        router: Optional[RouterConfig] = None,
        work_dir: Optional[Path] = None,
        debug: bool = False
    ):
        self.task_id = task_id
        self.mode = mode  # "demo" or "experiment"
        self.mutation = mutation  # e.g., "mutation_0"
        self.budget_sec = budget_sec
        self.max_iterations = max_iterations
        self.cases_per_iteration = cases_per_iteration
        self.termination = termination or TerminationConfig()
        self.features = features or FeatureConfig()
        self.router = router or RouterConfig()
        self.work_dir = work_dir
        self.debug = debug

        # Set work_dir based on mode if not specified
        if not self.work_dir:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if self.mode == "demo":
                self.work_dir = PROJECT_ROOT / "output" / "demo" / f"{task_id}_{timestamp}"
            else:
                self.work_dir = PROJECT_ROOT / "results" / "rq3" / "custom" / task_id / f"run_{timestamp}"


# ============================================================================
# Demo Mode Runner
# ============================================================================

class DemoRunner:
    """Interactive ReAct loop for demonstration and debugging."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.work_dir = config.work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

        log_dir = self.work_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        self.logger = Logger(str(log_dir), "demo.log", level=LEVEL.DEBUG if config.debug else LEVEL.INFO)

        from agents.generator import Generator
        from tools.fuzzers.random.generator import RandomCaseGenerator
        from core.data_types.exp_types import ExpUnifiedIR

        self.generator = None
        self.random_gen = RandomCaseGenerator()

    def run(self) -> Dict[str, Any]:
        """Run demo mode with interactive ReAct loop."""
        self.logger.info(f"=== Demo Mode: {self.config.task_id} ===")
        start_time = time.time()

        result = {
            "task_id": self.config.task_id,
            "mode": "demo",
            "status": "RUNNING",
            "iterations": 0,
            "total_cases": 0,
            "coverage_line": 0.0,
            "coverage_branch": 0.0,
            "duration_sec": 0.0,
            "router_strategy": self.config.router.strategy
        }

        try:
            # Initialize components
            self._initialize()

            # Run iterations
            for iteration in range(1, self.config.max_iterations + 1):
                if time.time() - start_time >= self.config.budget_sec:
                    self.logger.info(f"Budget exhausted after {iteration - 1} iterations")
                    break

                iter_result = self._run_iteration(iteration, start_time)
                result["iterations"] = iteration
                result["total_cases"] += iter_result["cases"]

                # Check termination conditions
                if self._should_terminate(iter_result, iteration, start_time):
                    self.logger.info(f"Termination condition met: {self.config.termination.condition}")
                    break

            result["status"] = "SUCCESS"
            result["duration_sec"] = time.time() - start_time

        except Exception as e:
            self.logger.error(f"Demo failed: {e}")
            result["status"] = "FAILED"
            result["error"] = str(e)

        # Save result
        self._save_result(result)
        self._print_summary(result)

        return result

    def _initialize(self):
        """Initialize generator and harness."""
        from harness.compiler.st_coverage_collector import STCoverageCollector

        benchmark_root = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_raw"
        task_dir = benchmark_root / self.config.task_id

        self.st_path = task_dir / "plc_st_files" / f"{self.config.task_id}.st"
        self.harness_path = task_dir / "plc_c_files" / "harness.c"
        self.schema_path = task_dir / "input" / "input_schema_v2.json"

        if not all(p.exists() for p in [self.st_path, self.harness_path, self.schema_path]):
            raise FileNotFoundError(f"Harness files not found for {self.config.task_id}")

        self.coverage_collector = STCoverageCollector(
            root_dir=str(PROJECT_ROOT),
            logger=self.logger,
            default_output_format="StoredTestCase",
            llvm_version=18
        )

        self.generator = Generator(
            st_path=str(self.st_path),
            benchmark_dir=str(task_dir)
        )

        self.logger.info("Demo mode initialized")

    def _run_iteration(self, iteration: int, start_time: float) -> Dict[str, Any]:
        """Run a single iteration."""
        iter_start = time.time()
        budget_remaining = int(self.config.budget_sec - (iter_start - start_time))

        self.logger.info(f"[Iteration {iteration}] Budget remaining: {budget_remaining}s")

        # Build context
        context = {
            "iteration": iteration,
            "first_round": iteration == 1,
        }

        # Generate cases with LLM
        goal = f"Maximize branch coverage. Budget: ~{budget_remaining}s remaining. "
        if iteration == 1:
            goal += "Start with random_fuzzing to explore."

        llm_cases = self.generator.generate(
            goal=goal,
            context=context,
            max_tool_calls=3
        )

        # Add random cases
        from core.data_types.exp_types import ExpUnifiedIR
        import uuid

        st_code = self.st_path.read_text(encoding='utf-8')
        with open(self.schema_path) as f:
            schema = json.load(f)

        random_cases = []
        for _ in range(min(10, self.config.cases_per_iteration)):
            tl = {}
            for cyc in range(5):
                p = self.random_gen.generate_case(st_code, schema)
                if p:
                    tl[cyc] = p
            if tl:
                random_cases.append(ExpUnifiedIR(
                    exp_id=f"{self.config.task_id}_rnd_{uuid.uuid4().hex[:4]}",
                    target_st_path=str(self.st_path),
                    schema_path=str(self.schema_path),
                    tester_type="demo_random",
                    total_cycles=len(tl),
                    sparse_timeline=tl
                ))

        all_cases = [c for c in llm_cases if hasattr(c, 'sparse_timeline')] + random_cases

        # Execute and collect coverage
        if all_cases:
            exec_result = self.coverage_collector.execute_with_multiple_coverage(
                st_code_input=str(self.st_path),
                harness_input=str(self.harness_path),
                input_data_list=all_cases[:50],
                benchmark_case=f"{self.config.task_id}_demo",
                reuse_compilation=True,
                output_format="StoredTestCase"
            )

            cov_data = exec_result.get("coverage_data")
            if cov_data and hasattr(cov_data, "coverage_summary"):
                line_cov = cov_data.coverage_summary.line_coverage
                branch_cov = cov_data.coverage_summary.branch_coverage
                line_pct = float(line_cov.percentage.replace("%", "")) if line_cov and line_cov.percentage else 0.0
                branch_pct = float(branch_cov.percentage.replace("%", "")) if branch_cov and branch_cov.percentage else 0.0

                self.logger.info(f"[Iteration {iteration}] Coverage: Line={line_pct:.1f}%, Branch={branch_pct:.1f}%, Cases={len(all_cases)}")

                return {
                    "cases": len(all_cases),
                    "line_coverage": line_pct,
                    "branch_coverage": branch_pct
                }

        return {"cases": len(all_cases), "line_coverage": 0.0, "branch_coverage": 0.0}

    def _should_terminate(self, iter_result: Dict, iteration: int, start_time: float) -> bool:
        """Check if termination condition is met."""
        cond = self.config.termination.condition

        if cond == "budget-elapsed":
            return time.time() - start_time >= self.config.budget_sec

        if cond == "max-iterations":
            return iteration >= self.config.max_iterations

        # agent-done and coverage-plateau require tracking state across iterations
        # For demo mode, simplify to budget/iterations
        return False

    def _save_result(self, result: Dict):
        """Save result to JSON."""
        result_path = self.work_dir / "demo_result.json"
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        self.logger.info(f"Result saved to {result_path}")

    def _print_summary(self, result: Dict):
        """Print execution summary."""
        print(f"\n{'='*60}")
        print(f"Demo Mode Complete: {self.config.task_id}")
        print(f"{'='*60}")
        print(f"Status:        {result['status']}")
        print(f"Iterations:    {result['iterations']}")
        print(f"Total Cases:   {result['total_cases']}")
        print(f"Duration:      {result['duration_sec']:.1f}s")
        print(f"Router:        {result['router_strategy']}")
        print(f"Work Dir:      {self.work_dir}")
        print(f"{'='*60}\n")


# ============================================================================
# Experiment Mode Runner (RQ3)
# ============================================================================

class ExperimentRunner:
    """Complete RQ3 experimental runner."""

    # Map feature config to RQ3 config ID
    CONFIG_MAP = {
        ("minimal",): "E_raw",
        ("basic",): "C0",
        ("assertions-only",): "C4",
        ("analysis",): "C1",
        ("full",): "C1",
    }

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.work_dir = config.work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> Dict[str, Any]:
        """Run experiment mode using RQ3 runner."""
        print(f"\n{'='*60}")
        print(f"Experiment Mode: {self.config.task_id}")
        print(f"{'='*60}\n")

        # Import RQ3 runner
        from experiments.rq3.rq3_runner_v3 import RQ3Runner, AblationConfig

        # Determine RQ3 config from feature settings
        rq3_config_id = self._map_to_rq3_config()

        # Setup logger
        log_dir = self.work_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        logger = Logger(str(log_dir), "rq3.log", level=LEVEL.DEBUG if self.config.debug else LEVEL.WARNING)

        # Create mutation task string
        mutation_task = None
        if self.config.mutation:
            mutation_task = f"{self.config.task_id}/{self.config.mutation}"

        # Initialize RQ3 runner
        rq3_config = AblationConfig(rq3_config_id)
        runner = RQ3Runner(
            task_id=self.config.task_id,
            config=rq3_config,
            work_dir=self.work_dir,
            logger=logger,
            mutation_task=mutation_task
        )

        # Run the experiment
        summary = runner.run(
            time_budget=self.config.budget_sec,
            cases_per_iter=self.config.cases_per_iteration,
            max_iterations=self.config.max_iterations
        )

        # Print summary
        self._print_summary(summary)

        return summary

    def _map_to_rq3_config(self) -> str:
        """Map feature configuration to RQ3 config ID."""
        features = self.config.features

        # Determine based on enabled features
        if features.assertions and features.keyframes and features.ddmin:
            return "C1"  # Full framework
        elif features.assertions and not features.keyframes:
            return "C4"  # No oracle in feedback
        elif not features.assertions and not features.keyframes:
            return "E_raw"  # Raw output
        else:
            return "C1"  # Default to full

    def _print_summary(self, summary: Dict):
        """Print experiment summary."""
        print(f"\n{'='*60}")
        print(f"Experiment Complete: {self.config.task_id}")
        print(f"{'='*60}")
        print(f"Config:           {summary.get('config', 'N/A')}")
        print(f"Iterations:       {summary.get('total_iterations', 0)}")
        print(f"Total Cases:      {summary.get('total_cases', 0)}")
        print(f"Total Cycles:     {summary.get('total_cycles', 0)}")
        print(f"Line Coverage:    {summary.get('final_line_coverage', 0):.1f}%")
        print(f"Branch Coverage:  {summary.get('final_branch_coverage', 0):.1f}%")
        print(f"Assertions:       {summary.get('assertion_generated', 0)} generated")
        print(f"Assertion Trigs:  {summary.get('assertion_triggers', 0)} total")
        print(f"                  {summary.get('distinct_assertions_triggered', 0)} distinct")
        print(f"Ground Truth:     {'HIT' if summary.get('ground_truth_detected') else 'MISS'}")
        print(f"Token Input:      {summary.get('total_token_input', 0)}")
        print(f"Token Output:     {summary.get('total_token_output', 0)}")
        print(f"Duration:         {summary.get('total_elapsed', 0):.1f}s")
        print(f"Work Dir:         {self.work_dir}")
        print(f"{'='*60}\n")


# ============================================================================
# Main Entry Point
# ============================================================================

def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="PLCHaT End-to-End Testing Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick demo
  python run.py --task 211_StackMin

  # Full experiment with all features
  python run.py --task 211_StackMin --mode experiment --enable-all

  # Custom configuration
  python run.py --task 211_StackMin --mode demo \\
      --router llm --budget 120 --stop-when agent-done

  # Mutation testing
  python run.py --task 211_StackMin --mutation mutation_0 \\
      --mode experiment --feature-preset full

Results Location:
  Demo mode:     output/demo/<task_id>_<timestamp>/
  Experiment:    results/rq3/custom/<task_id>/run_<timestamp>/
        """
    )

    # ========================================================================
    # Required Arguments
    # ========================================================================
    parser.add_argument("--task", required=True,
                        help="Task ID (e.g., 211_StackMin)")

    # ========================================================================
    # Mode Selection
    # ========================================================================
    parser.add_argument("--mode", choices=["demo", "experiment"], default="demo",
                        help="Execution mode (demo: interactive, experiment: RQ3 runner)")

    # ========================================================================
    # Task Configuration
    # ========================================================================
    parser.add_argument("--mutation", help="Mutation variant (e.g., mutation_0)")

    # ========================================================================
    # Termination Conditions
    # ========================================================================
    parser.add_argument("--budget", type=int, default=300,
                        help="Time budget in seconds (default: 300)")
    parser.add_argument("--max-iterations", type=int, default=200,
                        help="Maximum iterations (default: 200)")
    parser.add_argument("--cases-per-iter", type=int, default=5,
                        help="Test cases per iteration (default: 5)")
    parser.add_argument("--stop-when", dest="stop_condition",
                        choices=["budget-elapsed", "agent-done", "coverage-plateau", "max-iterations"],
                        default="budget-elapsed",
                        help="Primary termination condition (default: budget-elapsed)")

    # ========================================================================
    # Feature Configuration
    # ========================================================================
    feature_group = parser.add_argument_group("Feature Configuration")

    feature_group.add_argument("--feature-preset",
                               choices=["minimal", "basic", "assertions-only", "analysis", "full"],
                               help="Use a feature preset (overrides individual flags)")

    feature_group.add_argument("--enable-all", action="store_true",
                               help="Enable all features")
    feature_group.add_argument("--enable-assertions", action="store_true",
                               help="Enable assertion generation")
    feature_group.add_argument("--enable-keyframes", action="store_true",
                               help="Enable keyframe distillation")
    feature_group.add_argument("--enable-ddmin", action="store_true",
                               help="Enable DDMIN reduction")
    feature_group.add_argument("--enable-suite-reduction", action="store_true",
                               help="Enable test suite reduction")

    # ========================================================================
    # Router Configuration
    # ========================================================================
    router_group = parser.add_argument_group("Router Configuration")

    router_group.add_argument("--router",
                              choices=["random", "llm", "mab", "fixed"],
                              default="random",
                              help="Tool routing strategy (default: random)")

    # ========================================================================
    # Tool Parameters (advanced)
    # ========================================================================
    tool_group = parser.add_argument_group("Tool Parameters (Advanced)")

    tool_group.add_argument("--random-budget", type=int, metavar="SEC",
                            help="Random fuzzing budget in seconds")
    tool_group.add_argument("--afl-budget", type=int, metavar="SEC",
                            help="AFL mutation budget in seconds")
    tool_group.add_argument("--dse-budget", type=int, metavar="SEC",
                            help="DSE budget in seconds")

    # ========================================================================
    # Output Configuration
    # ========================================================================
    output_group = parser.add_argument_group("Output Configuration")

    output_group.add_argument("--work-dir", metavar="PATH",
                              help="Custom working directory")
    output_group.add_argument("--debug", action="store_true",
                              help="Enable debug logging")
    output_group.add_argument("--quiet", "-q", action="store_true",
                              help="Suppress progress output")

    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # ========================================================================
    # Build Configuration
    # ========================================================================

    # Termination config
    termination = TerminationConfig(condition=args.stop_condition)

    # Feature config
    if args.feature_preset:
        features = FeatureConfig.from_preset(args.feature_preset)
    else:
        features = FeatureConfig(
            enable_assertions=args.enable_assertions or args.enable_all,
            enable_keyframes=args.enable_keyframes or args.enable_all,
            enable_ddmin=args.enable_ddmin or args.enable_all,
            enable_suite_reduction=args.enable_suite_reduction or args.enable_all,
        )

    # Router config with tool parameters
    tool_params = {}
    if args.random_budget:
        tool_params["random_fuzzing"] = {"budget_sec": args.random_budget}
    if args.afl_budget:
        tool_params["run_afl_mutation"] = {"budget_sec": args.afl_budget}
    if args.dse_budget:
        tool_params["run_full_dse"] = {"budget_sec": args.dse_budget}

    router = RouterConfig(strategy=args.router, tool_params=tool_params if tool_params else None)

    # Complete experiment config
    config = ExperimentConfig(
        task_id=args.task,
        mode=args.mode,
        mutation=args.mutation,
        budget_sec=args.budget,
        max_iterations=args.max_iterations,
        cases_per_iteration=args.cases_per_iter,
        termination=termination,
        features=features,
        router=router,
        work_dir=Path(args.work_dir) if args.work_dir else None,
        debug=args.debug
    )

    # ========================================================================
    # Print Configuration
    # ========================================================================
    if not args.quiet:
        print(f"\n{'='*60}")
        print(f"PLCHaT End-to-End Testing")
        print(f"{'='*60}")
        print(f"Task:              {config.task_id}")
        print(f"Mode:              {config.mode}")
        if config.mutation:
            print(f"Mutation:          {config.mutation}")
        print(f"Budget:            {config.budget_sec}s")
        print(f"Max Iterations:    {config.max_iterations}")
        print(f"Cases/Iteration:   {config.cases_per_iteration}")
        print(f"Termination:       {config.termination.condition}")
        print(f"Features:")
        print(f"  Assertions:      {config.features.assertions}")
        print(f"  Keyframes:       {config.features.keyframes}")
        print(f"  DDMIN:           {config.features.ddmin}")
        print(f"  Suite Reduce:    {config.features.suite_reduction}")
        print(f"Router:            {config.router.strategy}")
        print(f"Work Dir:          {config.work_dir}")
        print(f"{'='*60}\n")

    # ========================================================================
    # Run Appropriate Mode
    # ========================================================================
    try:
        if config.mode == "demo":
            runner = DemoRunner(config)
            result = runner.run()
            return 0 if result.get("status") == "SUCCESS" else 1

        else:  # experiment
            runner = ExperimentRunner(config)
            result = runner.run()
            return 0

    except KeyboardInterrupt:
        print("\n[Interrupted] User cancelled execution")
        return 130

    except Exception as e:
        print(f"\n[Error] {e}")
        if config.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
