"""
Converters between Protocol Layer and Data Layer
Handle conversion between protocols/ (API layer) and data_types/ (data layer)

Design:
- Protocol Layer (API): Action*Result types - simplified format for Agent-Harness communication
- Data Layer (Internal): ST* types, Report types - complete internal data structures
"""

from typing import Optional, List, Dict, Any
from core.data_types import (
    STExecutionResult, CoverageReport, AnalysisReport,
    PLCVarState, PLCTestCase, PLCCycle, CoverageSummary, CoverageBreakdown,
)
from core.protocols import (
    ActionExecutionResult, ActionCoverageResult, ActionAnalysisResult,
)


class ExecutionConverter:
    """
    Converter between STExecutionResult (data layer) and ActionExecutionResult (protocol layer).

    Data Layer: STExecutionResult - Complete internal execution result with all details
    Protocol Layer: ActionExecutionResult - Simplified API format for Agent communication
    """

    @staticmethod
    def to_action_response(st_result: STExecutionResult, test_case_id: str = None) -> ActionExecutionResult:
        """
        Convert internal STExecutionResult to API-layer ActionExecutionResult.

        Args:
            st_result: Internal execution result
            test_case_id: Optional test case ID (auto-detected if not provided)

        Returns:
            ActionExecutionResult for API response
        """
        # Auto-detect test case ID if not provided
        if test_case_id is None and st_result.test_cases:
            test_case_id = st_result.test_cases[0].test_case_name
        elif test_case_id is None:
            test_case_id = "unknown"

        # Extract final state from last cycle of first test case
        final_state = {}
        state_trace = []

        if st_result.test_cases:
            tc = st_result.test_cases[0]
            for cycle in tc.cycles:
                state_trace.append({
                    "cycle": cycle.cycle,
                    "VAR_OUTPUT": dict(cycle.after_execution.VAR_OUTPUT),
                    "VAR_INTERNAL": dict(cycle.after_execution.VAR_INTERNAL),
                })
            if tc.cycles:
                final_state = {
                    "VAR_OUTPUT": dict(tc.cycles[-1].after_execution.VAR_OUTPUT),
                    "VAR_INTERNAL": dict(tc.cycles[-1].after_execution.VAR_INTERNAL),
                }

        # Extract coverage information
        coverage_summary = None
        uncovered_branches = None
        uncovered_lines = None

        # Problems from execution
        problems = []
        if st_result.message and st_result.status != "success":
            problems.append({
                "type": "execution_error",
                "message": st_result.message,
            })

        return ActionExecutionResult(
            test_case_id=test_case_id,
            execution_status=st_result.status.value if hasattr(st_result.status, 'value') else str(st_result.status),
            final_state=final_state,
            state_trace=state_trace,
            coverage_summary=coverage_summary,
            uncovered_branches=uncovered_branches,
            uncovered_lines=uncovered_lines,
            problems=problems,
            stdout=st_result.raw_stdout if st_result.raw_stdout else None,
            stderr=st_result.raw_stderr if st_result.raw_stderr else None,
        )


class CoverageConverter:
    """
    Converter between CoverageReport (data layer) and ActionCoverageResult (protocol layer).

    Data Layer: CoverageReport - Complete internal coverage data with files, summaries
    Protocol Layer: ActionCoverageResult - Simplified API format for Agent communication
    """

    @staticmethod
    def to_action_response(cov_report: CoverageReport) -> ActionCoverageResult:
        """
        Convert internal CoverageReport to API-layer ActionCoverageResult.

        Args:
            cov_report: Internal coverage report

        Returns:
            ActionCoverageResult for API response
        """
        # Extract summary information
        summary = {}
        uncovered_lines = []
        uncovered_branches = []
        uncovered_functions = []
        line_coverage = None
        branch_coverage = None
        function_coverage = None

        if cov_report.coverage_summary:
            cs = cov_report.coverage_summary

            # Build summary from all coverage types
            if cs.line_coverage:
                if cs.line_coverage.percentage:
                    try:
                        summary["line_percentage"] = float(cs.line_coverage.percentage.rstrip("%"))
                    except:
                        pass
                if cs.line_coverage.covered is not None:
                    summary["lines_covered"] = cs.line_coverage.covered
                if cs.line_coverage.total is not None:
                    summary["lines_total"] = cs.line_coverage.total

            if cs.branch_coverage:
                if cs.branch_coverage.percentage:
                    try:
                        summary["branch_percentage"] = float(cs.branch_coverage.percentage.rstrip("%"))
                    except:
                        pass

            # Extract line_coverage detailed breakdown
            if cs.line_coverage and (cs.line_coverage.total or cs.line_coverage.missed is not None):
                line_coverage = {
                    "percentage": cs.line_coverage.percentage,
                    "total": cs.line_coverage.total,
                    "missed": cs.line_coverage.missed,
                    "covered": cs.line_coverage.covered,
                }

            # Extract branch_coverage detailed breakdown
            if cs.branch_coverage and (cs.branch_coverage.total or cs.branch_coverage.missed is not None):
                branch_coverage = {
                    "percentage": cs.branch_coverage.percentage,
                    "total": cs.branch_coverage.total,
                    "missed": cs.branch_coverage.missed,
                    "covered": cs.branch_coverage.covered,
                }

            # Extract function_coverage detailed breakdown
            if cs.function_coverage and (cs.function_coverage.total or cs.function_coverage.missed is not None):
                function_coverage = {
                    "percentage": cs.function_coverage.percentage,
                    "total": cs.function_coverage.total,
                    "missed": cs.function_coverage.missed,
                    "covered": cs.function_coverage.covered,
                }

        return ActionCoverageResult(
            coverage_type="line",  # Default type
            summary=summary,
            line_coverage=line_coverage,
            branch_coverage=branch_coverage,
            function_coverage=function_coverage,
            uncovered_lines=uncovered_lines,
            uncovered_branches=uncovered_branches,
            uncovered_functions=uncovered_functions,
        )


class AnalysisConverter:
    """
    Converter between AnalysisReport (data layer) and ActionAnalysisResult (protocol layer).

    Data Layer: AnalysisReport - Complete internal analysis with oracle violations
    Protocol Layer: ActionAnalysisResult - Simplified API format for Agent communication
    """

    @staticmethod
    def to_action_response(analysis_report: AnalysisReport, analysis_type: str = "general") -> ActionAnalysisResult:
        """
        Convert internal AnalysisReport to API-layer ActionAnalysisResult.

        Args:
            analysis_report: Internal analysis report
            analysis_type: Type of analysis performed

        Returns:
            ActionAnalysisResult for API response
        """
        # Build findings from analysis report
        findings = []
        if analysis_report.is_interesting:
            findings.append({
                "type": "vulnerability",
                "subtype": analysis_report.vulnerability_type,
                "description": analysis_report.details,
            })

        # Build coverage analysis
        coverage_analysis = None
        if analysis_report.coverage_gain:
            coverage_analysis = {
                "gain": analysis_report.coverage_gain,
            }

        # Build problem analysis from oracle violations
        problem_analysis = None
        if analysis_report.oracle_violations:
            problem_analysis = {
                "violations": [
                    {
                        "test_item_id": v.test_item_id,
                        "name": v.name,
                        "severity": v.severity,
                        "reason": v.reason,
                        "evidence": v.evidence,
                    }
                    for v in analysis_report.oracle_violations
                ]
            }

        return ActionAnalysisResult(
            analysis_type=analysis_type,
            findings=findings,
            coverage_analysis=coverage_analysis,
            problem_analysis=problem_analysis,
            state_analysis=None,
            suggestions=analysis_report.suggestions,
            next_actions=[],  # Could be derived from suggestions
        )


# Convenience export
__all__ = [
    "ExecutionConverter",
    "CoverageConverter",
    "AnalysisConverter",
]
