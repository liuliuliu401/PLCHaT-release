"""
PLCHaT ST State Analyzer

State analysis system for PLC execution results.
Extracts sparse timelines, detects state changes, and extracts keyframes.

Key features:
- Sparse timeline extraction (filter flat cycles)
- State change detection
- Keyframe extraction
- State comparison and delta analysis
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Set
from dataclasses import dataclass, field

# Add parent directory to path for imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from harness.compiler.utils import Logger, LEVEL
from core.data_types.execution_coverage import STExecutionResult
from core.data_types.test_case_types import PLCTestCase, PLCCycle, PLCVarState


@dataclass
class StateDelta:
    """Represents changes in PLC state between cycles."""
    cycle_index: int
    var_changes: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)  # var_name -> (old_value, new_value)
    new_vars: Dict[str, Any] = field(default_factory=dict)  # Newly added variables
    removed_vars: Set[str] = field(default_factory=set)  # Removed variable names


@dataclass
class SparseTimeline:
    """
    Sparse timeline representation with only state-changing cycles.

    Attributes:
        original_cycles: Total number of original cycles
        sparse_cycles: List of (cycle_index, cycle) tuples where state changed
        filtered_cycles: Number of filtered (flat) cycles
        compression_ratio: Ratio of sparse to original cycles
    """
    original_cycles: int
    sparse_cycles: List[Tuple[int, PLCCycle]] = field(default_factory=list)
    filtered_cycles: int = 0
    compression_ratio: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "original_cycles": self.original_cycles,
            "sparse_cycles": [
                {
                    "cycle_index": idx,
                    "cycle_number": cycle.cycle,
                    "before_execution": {
                        "VAR_INPUT": dict(cycle.before_execution.VAR_INPUT),
                        "VAR_OUTPUT": dict(cycle.before_execution.VAR_OUTPUT),
                        "VAR_INTERNAL": dict(cycle.before_execution.VAR_INTERNAL)
                    },
                    "after_execution": {
                        "VAR_INPUT": dict(cycle.after_execution.VAR_INPUT),
                        "VAR_OUTPUT": dict(cycle.after_execution.VAR_OUTPUT),
                        "VAR_INTERNAL": dict(cycle.after_execution.VAR_INTERNAL)
                    }
                }
                for idx, cycle in self.sparse_cycles
            ],
            "filtered_cycles": self.filtered_cycles,
            "compression_ratio": self.compression_ratio
        }


@dataclass
class Keyframe:
    """
    Keyframe representation at a specific cycle with important state changes.

    Attributes:
        cycle_index: Index of the cycle
        cycle_number: Original cycle number
        state_delta: Changes from previous cycle
        importance_score: Score indicating importance (0-1)
        reason: Reason why this is a keyframe
    """
    cycle_index: int
    cycle_number: int
    state_delta: StateDelta
    importance_score: float = 0.5
    reason: str = ""


class STStateAnalyzer:
    """
    State analysis system for PLC execution results.

    Extracts sparse timelines by filtering out flat cycles where
    no state changes occur, and identifies keyframes with important
    state transitions.
    """

    def __init__(
        self,
        logger: Optional[Logger] = None,
        debug: bool = False
    ):
        """
        Initialize state analyzer.

        Args:
            logger: Logger instance
            debug: Enable debug logging
        """
        self.logger = logger or Logger("/tmp/plchat_state_analyzer_logs", "st_state_analyzer.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug

    def extract_sparse_timeline(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0,
        include_outputs: bool = True,
        include_internal: bool = True
    ) -> SparseTimeline:
        """
        Extract sparse timeline from execution result.

        Filters out cycles where no state changes occur, keeping only
        cycles where at least one variable value changes.

        Args:
            execution_result: Execution result to analyze
            test_case_index: Index of test case to analyze (default: 0)
            include_outputs: Include VAR_OUTPUT in change detection
            include_internal: Include VAR_INTERNAL in change detection

        Returns:
            SparseTimeline with only state-changing cycles
        """
        self.logger.info_print(f"Extracting sparse timeline from test case {test_case_index}")

        if not execution_result.test_cases:
            self.logger.warning_print("No test cases in execution result")
            return SparseTimeline(original_cycles=0)

        if test_case_index >= len(execution_result.test_cases):
            self.logger.warning_print(f"Test case index {test_case_index} out of range")
            return SparseTimeline(original_cycles=0)

        test_case = execution_result.test_cases[test_case_index]
        cycles = test_case.cycles

        if not cycles:
            self.logger.info_print("No cycles in test case")
            return SparseTimeline(original_cycles=0)

        sparse_cycles = []
        prev_state = None

        for idx, cycle in enumerate(cycles):
            # Always include first cycle
            if idx == 0:
                sparse_cycles.append((idx, cycle))
                prev_state = cycle.after_execution
                continue

            # Compare current state with previous state
            has_changes = self._has_state_changes(
                prev_state,
                cycle.after_execution,
                include_outputs=include_outputs,
                include_internal=include_internal
            )

            if has_changes:
                sparse_cycles.append((idx, cycle))
                prev_state = cycle.after_execution

        original_count = len(cycles)
        sparse_count = len(sparse_cycles)
        filtered_count = original_count - sparse_count
        compression_ratio = sparse_count / original_count if original_count > 0 else 1.0

        self.logger.info_print(
            f"Sparse timeline extracted: {sparse_count}/{original_count} cycles "
            f"(filtered {filtered_count}, compression ratio: {compression_ratio:.2f})"
        )

        return SparseTimeline(
            original_cycles=original_count,
            sparse_cycles=sparse_cycles,
            filtered_cycles=filtered_count,
            compression_ratio=compression_ratio
        )

    def _has_state_changes(
        self,
        prev_cycle: PLCVarState,
        curr_cycle: PLCVarState,
        include_outputs: bool = True,
        include_internal: bool = True
    ) -> bool:
        """
        Check if there are any state changes between two cycles.

        Args:
            prev_cycle: Previous cycle state
            curr_cycle: Current cycle state
            include_outputs: Check VAR_OUTPUT for changes
            include_internal: Check VAR_INTERNAL for changes

        Returns:
            True if there are any changes, False otherwise
        """
        # Note: We skip VAR_INPUT as it typically doesn't change in execution
        # and is provided externally

        if include_outputs:
            if prev_cycle.VAR_OUTPUT != curr_cycle.VAR_OUTPUT:
                return True

        if include_internal:
            if prev_cycle.VAR_INTERNAL != curr_cycle.VAR_INTERNAL:
                return True

        return False

    def compute_state_delta(
        self,
        prev_cycle: PLCVarState,
        curr_cycle: PLCVarState
    ) -> StateDelta:
        """
        Compute state delta between two cycles.

        Args:
            prev_cycle: Previous cycle state
            curr_cycle: Current cycle state

        Returns:
            StateDelta with all changes
        """
        delta = StateDelta(cycle_index=0)

        # Check VAR_OUTPUT changes
        for var_name, new_value in curr_cycle.VAR_OUTPUT.items():
            if var_name in prev_cycle.VAR_OUTPUT:
                old_value = prev_cycle.VAR_OUTPUT[var_name]
                if old_value != new_value:
                    delta.var_changes[var_name] = (old_value, new_value)
            else:
                delta.new_vars[var_name] = new_value

        # Check removed variables in VAR_OUTPUT
        for var_name in prev_cycle.VAR_OUTPUT:
            if var_name not in curr_cycle.VAR_OUTPUT:
                delta.removed_vars.add(var_name)

        # Check VAR_INTERNAL changes
        for var_name, new_value in curr_cycle.VAR_INTERNAL.items():
            if var_name in prev_cycle.VAR_INTERNAL:
                old_value = prev_cycle.VAR_INTERNAL[var_name]
                if old_value != new_value:
                    var_key = f"internal.{var_name}"
                    delta.var_changes[var_key] = (old_value, new_value)
            else:
                var_key = f"internal.{var_name}"
                delta.new_vars[var_key] = new_value

        return delta

    def extract_keyframes(
        self,
        sparse_timeline: SparseTimeline,
        max_keyframes: Optional[int] = None,
        min_change_count: int = 1
    ) -> List[Keyframe]:
        """
        Extract keyframes from sparse timeline based on importance.

        Keyframes are cycles with significant state changes.
        Importance is determined by the number of variables that changed.

        Args:
            sparse_timeline: Sparse timeline to analyze
            max_keyframes: Maximum number of keyframes to return
            min_change_count: Minimum number of changed variables to be considered a keyframe

        Returns:
            List of keyframes sorted by importance
        """
        self.logger.info_print("Extracting keyframes from sparse timeline")

        if not sparse_timeline.sparse_cycles:
            self.logger.warning_print("No sparse cycles to analyze")
            return []

        keyframes = []

        for idx, (cycle_index, cycle) in enumerate(sparse_timeline.sparse_cycles):
            # Get previous state (if available)
            if idx > 0:
                prev_cycle = sparse_timeline.sparse_cycles[idx - 1][1].after_execution
            else:
                # For first cycle, use before_execution as previous
                prev_cycle = cycle.before_execution

            # Compute state delta
            state_delta = self.compute_state_delta(prev_cycle, cycle.after_execution)

            # Calculate importance score based on number of changes
            change_count = len(state_delta.var_changes) + len(state_delta.new_vars) + len(state_delta.removed_vars)

            if change_count >= min_change_count:
                # Normalize score to 0-1 range (heuristic)
                importance_score = min(1.0, change_count / 10.0)

                # Determine reason
                if change_count > 5:
                    reason = f"Major state change: {change_count} variables affected"
                elif change_count > 2:
                    reason = f"Moderate state change: {change_count} variables affected"
                else:
                    reason = f"Minor state change: {change_count} variables affected"

                keyframe = Keyframe(
                    cycle_index=cycle_index,
                    cycle_number=cycle.cycle,
                    state_delta=state_delta,
                    importance_score=importance_score,
                    reason=reason
                )
                keyframes.append(keyframe)

        # Sort by importance score (descending)
        keyframes.sort(key=lambda kf: kf.importance_score, reverse=True)

        # Apply max limit if specified
        if max_keyframes and len(keyframes) > max_keyframes:
            keyframes = keyframes[:max_keyframes]

        self.logger.info_print(f"Extracted {len(keyframes)} keyframes")

        return keyframes

    def detect_violations(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Detect potential violations in execution result.

        Checks for:
        - Crash/timeout errors
        - Abnormal variable values (NaN, infinity)
        - Unexpected state transitions

        Args:
            execution_result: Execution result to analyze
            test_case_index: Index of test case to analyze

        Returns:
            List of violation dictionaries
        """
        self.logger.info_print(f"Detecting violations in test case {test_case_index}")

        violations = []

        # Check execution status
        if execution_result.status != "success":
            violations.append({
                "type": "execution_failure",
                "severity": "high",
                "message": f"Execution failed with status: {execution_result.status}",
                "return_code": execution_result.return_code
            })

        # Check for timeout
        if execution_result.status == "timeout":
            violations.append({
                "type": "timeout",
                "severity": "high",
                "message": "Execution timed out"
            })

        # Analyze cycles for abnormal values
        if test_case_index < len(execution_result.test_cases):
            test_case = execution_result.test_cases[test_case_index]

            for cycle in test_case.cycles:
                # Check VAR_OUTPUT for abnormal values
                for var_name, value in cycle.after_execution.VAR_OUTPUT.items():
                    if self._is_abnormal_value(value):
                        violations.append({
                            "type": "abnormal_value",
                            "severity": "medium",
                            "message": f"Abnormal value detected: {var_name} = {value}",
                            "cycle": cycle.cycle,
                            "variable": var_name,
                            "value": value
                        })

                # Check VAR_INTERNAL for abnormal values
                for var_name, value in cycle.after_execution.VAR_INTERNAL.items():
                    if self._is_abnormal_value(value):
                        violations.append({
                            "type": "abnormal_value",
                            "severity": "medium",
                            "message": f"Abnormal internal value: {var_name} = {value}",
                            "cycle": cycle.cycle,
                            "variable": f"internal.{var_name}",
                            "value": value
                        })

        self.logger.info_print(f"Detected {len(violations)} violations")

        return violations

    def _is_abnormal_value(self, value: Any) -> bool:
        """
        Check if a value is abnormal (NaN, infinity, etc.).

        Args:
            value: Value to check

        Returns:
            True if value is abnormal, False otherwise
        """
        try:
            # Check for NaN and infinity in float values
            if isinstance(value, float):
                import math
                if math.isnan(value) or math.isinf(value):
                    return True
            return False
        except:
            return False

    def summarize_execution(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0
    ) -> Dict[str, Any]:
        """
        Generate a summary of execution results.

        Args:
            execution_result: Execution result to summarize
            test_case_index: Index of test case to summarize

        Returns:
            Dictionary with execution summary
        """
        self.logger.info_print(f"Summarizing execution for test case {test_case_index}")

        summary = {
            "status": execution_result.status,
            "return_code": execution_result.return_code,
            "message": execution_result.message,
            "total_test_cases": len(execution_result.test_cases),
        }

        if test_case_index < len(execution_result.test_cases):
            test_case = execution_result.test_cases[test_case_index]

            summary.update({
                "test_case_name": test_case.test_case_name,
                "total_cycles": test_case.summary.total_cycles,
                "final_state": {
                    "VAR_OUTPUT": dict(test_case.summary.final_state.VAR_OUTPUT),
                    "VAR_INTERNAL": dict(test_case.summary.final_state.VAR_INTERNAL)
                }
            })

            # Extract sparse timeline
            sparse_timeline = self.extract_sparse_timeline(execution_result, test_case_index)
            summary["sparse_timeline"] = sparse_timeline.to_dict()

            # Extract keyframes
            keyframes = self.extract_keyframes(sparse_timeline, max_keyframes=5)
            summary["keyframes"] = [
                {
                    "cycle_index": kf.cycle_index,
                    "cycle_number": kf.cycle_number,
                    "importance_score": kf.importance_score,
                    "reason": kf.reason,
                    "changes_count": len(kf.state_delta.var_changes) + len(kf.state_delta.new_vars)
                }
                for kf in keyframes
            ]

            # Detect violations
            violations = self.detect_violations(execution_result, test_case_index)
            summary["violations"] = violations
            summary["violation_count"] = len(violations)

        return summary
