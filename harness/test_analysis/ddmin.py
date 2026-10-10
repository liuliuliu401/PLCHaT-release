"""
ddmin (Delta Debugging Minimization) for PLC test case reduction.

Algorithm: Iteratively removes cycles from a test case while checking if the
reduced test case still triggers the target assertion. Produces a 1-minimal
test case (no single cycle can be removed without losing the assertion).

Reference: Zeller & Hildebrandt, "Simplifying and Isolating Failure-Inducing Input"
"""

import sys, json
from pathlib import Path
from typing import Dict, List, Callable, Tuple, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_types.exp_types import ExpUnifiedIR


def ddmin_minimize(
    original_timeline: Dict[str, Dict[str, Any]],
    st_path: str,
    schema_path: str,
    harness_path: str,
    benchmark_case: str,
    max_iterations: int = 100,
) -> Tuple[Dict, int]:
    """
    Minimize a test case using Delta Debugging.
    
    Args:
        original_timeline: The original sparse_timeline that triggers the assertion
        st_path: Path to ST source file
        schema_path: Path to input schema
        harness_path: Path to assertion-instrumented harness
        benchmark_case: Benchmark case identifier
        max_iterations: Maximum ddmin iterations
    
    Returns:
        (reduced_timeline, iteration_count)
    """
    # Convert timeline keys to a sorted list for partitioning
    cycles = sorted(original_timeline.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
    
    if len(cycles) <= 1:
        return original_timeline, 0
    
    # Create oracle: tests if reduced timeline still triggers assertion.
    # PLC cycles are STATEFUL, so the kept subsequence is RE-INDEXED to a contiguous
    # 0-based sequence and executed back-to-back: the FB state evolves through exactly
    # the kept cycles in scan order. This makes the verified-minimal case identical to
    # what we later re-execute/display (no gap-filled phantom cycles).
    def oracle(reduced_cycles: List[str]) -> bool:
        ordered = sorted(reduced_cycles, key=lambda x: int(x) if str(x).isdigit() else 0)
        reduced = {str(i): original_timeline[k] for i, k in enumerate(ordered)}
        return _test_timeline(reduced, st_path, schema_path, harness_path, benchmark_case)
    
    # ddmin recursive minimization
    current = cycles.copy()
    n = 2
    iterations = 0
    
    while len(current) > 1 and iterations < max_iterations:
        iterations += 1
        
        # Partition into n subsets
        subsets = _partition(current, n)
        
        # Test each subset's complement
        found_reduction = False
        for i in range(len(subsets)):
            complement = []
            for j, subset in enumerate(subsets):
                if j != i:
                    complement.extend(subset)
            
            if oracle(complement):
                current = complement
                found_reduction = True
                n = 2  # Reset granularity
                break
        
        if not found_reduction:
            if n >= len(current):
                break  # 1-minimal reached
            n = min(n * 2, len(current))
    
    # Return the 1-minimal case, re-indexed to a contiguous 0-based sequence so it is
    # a genuine, self-contained N-cycle test (identical to what the oracle certified).
    ordered = sorted(current, key=lambda x: int(x) if str(x).isdigit() else 0)
    reduced = {str(i): original_timeline[k] for i, k in enumerate(ordered)}
    return reduced, iterations


def _partition(items: List, n: int) -> List[List]:
    """Partition items into n roughly equal subsets."""
    subset_size = max(1, len(items) // n)
    subsets = []
    for i in range(n):
        start = i * subset_size
        end = min((i + 1) * subset_size, len(items))
        if start < len(items):
            subsets.append(items[start:end])
    return subsets


def _test_timeline(
    timeline: Dict[str, Dict[str, Any]],
    st_path: str,
    schema_path: str,
    harness_path: str,
    benchmark_case: str,
) -> bool:
    """
    Execute a test case against the assertion harness and check if assertion triggers.
    Returns True if assertion triggered (i.e., the reduced case still reproduces the bug).
    """
    import subprocess, uuid
    from harness.compiler.st_coverage_collector import STCoverageCollector
    from harness.compiler.utils import Logger, LEVEL
    
    try:
        dummy = ExpUnifiedIR(
            exp_id=f"ddmin_{uuid.uuid4().hex[:6]}",
            target_st_path=st_path,
            schema_path=schema_path,
            tester_type="ddmin",
            total_cycles=len(timeline),
            sparse_timeline=timeline,
        )
        
        cc = STCoverageCollector(
            root_dir=str(PROJECT_ROOT),
            logger=Logger("/tmp/ddmin_logs", "ddmin.log", level=LEVEL.ERROR, console_output=False),
            debug=False,
            default_output_format="StoredTestCase",
            llvm_version=18,
        )
        
        # NOTE: reuse_compilation=True is correct AFTER stale cache entries for this
        # ST+harness pair have been cleared (stale cache may produce wrong FB state
        # transitions — see _fuzzy_match + 999_trafficLight investigation 2026-06-23).
        # If ddmin produces unexpected false positives, clear /tmp/plchat_cache/compile_reuse/.
        result = cc.execute_with_multiple_coverage(
            st_code_input=st_path,
            harness_input=harness_path,
            input_data_list=[dummy],
            benchmark_case=benchmark_case,
            reuse_compilation=True,
            output_format="StoredTestCase",
        )
        
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        # Check for assertion trigger
        return "AUDIT FAIL" in stdout or "AUDIT FAIL" in stderr or "SECURITY_ASSERTION_FAILED" in stderr
    
    except Exception:
        return False


# ============================================================================
# Integration helper for RQ3Runner
# ============================================================================

def reduce_case_with_ddmin(
    case_timeline: Dict[str, Dict[str, Any]],
    st_path: str,
    schema_path: str,
    assertion_harness_path: str,
    task_id: str,
    max_iters: int = 100,
) -> Tuple[Dict, int]:
    """
    Convenience wrapper for calling ddmin from RQ3Runner.
    Returns (reduced_timeline, iterations_taken).
    """
    return ddmin_minimize(
        case_timeline,
        st_path,
        schema_path,
        assertion_harness_path,
        task_id,
        max_iterations=max_iters,
    )
