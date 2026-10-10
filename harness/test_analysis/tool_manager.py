"""
Test Analysis Tool Manager - Tool registration for test analysis agent.

Reference the design of GeneratorToolManager to provide tool registration functionality for the Test Analysis Agent.

Usage:
    from harness.test_analysis.tool_manager import TestAnalysisToolManager

    tool_manager = TestAnalysisToolManager(
        st_path="path/to/file.st",
        harness_path="path/to/harness.c"
    )

    # Get LangChain tools for LLM binding
    langchain_tools = tool_manager.get_langchain_tools()
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
from langchain_core.tools import tool as lc_tool
import logging

# Project root: tool_manager.py → test_analysis → harness → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

# PLCHaT imports - global relative position reference
from harness.registry.tool_registry import ToolRegistry, registry
from harness.test_analysis.execution import (
    execute_with_assertions,
    collect_coverage_with_assertions
)
from core.data_types.execution_coverage import STExecutionResult, CoverageRunResult
from core.data_types.test_analysis_types import TestCaseReport


logger = logging.getLogger(__name__)


class TestAnalysisToolManager:
    """
Manage tool registration for Test Analysis Agent.

Responsibility:
- Register execution and coverage collection tools
Create LangChain-compatible tools
- Provide tool registry

Design reference:
- Tool registration pattern of GeneratorToolManager
- Use @lc_tool decorator to create tool
- Manage tool lifecycle through ToolRegistry
    """

    def __init__(
        self,
        st_path: str,
        harness_path: str,
        tool_registry: Optional[ToolRegistry] = None
    ):
        """
Initialize the tool manager.

        Args:
st_path: ST source code path
harness_path: Harness code path
tool_registry: optional custom ToolRegistry
        """
        self.st_path = st_path
        self.harness_path = harness_path

        # Use the provided registry or global default
        self.registry = tool_registry or registry

        # Register tool
        self._register_tools()

    def _register_tools(self):
        """Register all test analysis tools (v2: two independent modes)."""
        # Get registered tool name
        tool_names = [spec.name for spec in self.registry.list_tools()]

        # Create and register tool - separate mode A and mode B
        tools_to_register = [
            self._create_collect_coverage_baseline_tool(),     # Pattern A: Coverage collection
            self._create_monitor_with_assertions_tool(),         # Mode B: assertion-based monitoring
            self._create_analyze_test_quality_tool(),            # Analysis tool
            self._create_design_next_targets_tool()              # Next step suggestion
        ]

        for tool_impl in tools_to_register:
            if tool_impl.name not in tool_names:
                self.registry.register(
                    name=tool_impl.name,
                    tool=tool_impl,
                    description=tool_impl.description,
                    tool_type="langchain"
                )
                logger.info(f"Registered tool: {tool_impl.name}")

    def _create_collect_coverage_baseline_tool(self):
        """Create coverage baseline collection tool (Mode A)."""

        @lc_tool
        def collect_coverage_baseline(
            test_inputs: List[str],
            timeout: int = 5
        ) -> Dict[str, Any]:
            """
Collect the coverage baseline of test cases (Mode A).

Use the original harness (no assertions) to collect coverage data for evaluating test case quality.
This is the first step to evaluate test completeness, and must be run separately from assertion-based monitoring.

            Args:
test_inputs: test input list
timeout: execution timeout

            Returns:
Coverage baseline data:
                {
                    "test_case_count": int,
                    "coverage_summary": {...},
                    "uncovered_regions": [...],
                    "quality_score": int
                }
            """
            logger.info(f"Mode A: Collecting coverage baseline with {len(test_inputs)} inputs")

            try:
                # Use the original harness path (remove the _assertioned suffix)
                base_harness = self.harness_path
                if "_assertioned.c" in base_harness:
                    base_harness = base_harness.replace("_assertioned.c", ".c")
                elif "harness_assertioned.c" in base_harness:
                    base_harness = base_harness.replace("harness_assertioned.c", "harness.c")

                logger.info(f"Mode A: Using original harness: {base_harness}")

                # Collect coverage
                cov_result = collect_coverage_with_assertions(
                    st_path=Path(self.st_path),
                    harness_path=Path(base_harness),
                    test_inputs=test_inputs
                )

                # Parse coverage data
                coverage_summary = {"line_coverage": 0.0, "branch_coverage": 0.0, "function_coverage": 0.0}

                if cov_result.coverage_data and cov_result.coverage_data.coverage_summary:
                    cs = cov_result.coverage_data.coverage_summary
                    def parse_pct(p):
                        if p:
                            try:
                                return float(p.rstrip('%'))
                            except:
                                return 0.0
                        return 0.0

                    coverage_summary = {
                        "line_coverage": parse_pct(cs.line_coverage.percentage) if cs.line_coverage else 0.0,
                        "branch_coverage": parse_pct(cs.branch_coverage.percentage) if cs.branch_coverage else 0.0,
                        "function_coverage": parse_pct(cs.function_coverage.percentage) if cs.function_coverage else 0.0
                    }

                # Calculate quality score (simple version: average coverage)
                avg_coverage = (coverage_summary["line_coverage"] + coverage_summary["branch_coverage"]) / 2
                quality_score = int(avg_coverage)

                return {
                    "test_case_count": len(test_inputs),
                    "coverage_summary": coverage_summary,
                    "uncovered_regions": [],  # TODO: Extract from coverage details
                    "quality_score": quality_score,
                    "mode": "A_coverage_baseline",
                    "message": f"Mode A: Coverage Baseline - Line {coverage_summary['line_coverage']:.1f}% Branch {coverage_summary['branch_coverage']:.1f}%"
                }

            except Exception as e:
                logger.error(f"collect_coverage_baseline failed: {e}")
                return {"error": str(e), "mode": "A_error", "message": f"Mode A execution failed: {e}"}

        return collect_coverage_baseline

    def _create_monitor_with_assertions_tool(self):
        """Create assertion-based monitoring tool (Mode B)."""

        @lc_tool
        def monitor_with_assertions(
            test_inputs: List[str],
            timeout: int = 5
        ) -> Dict[str, Any]:
            """
Use assertions to monitor program execution (Mode B).

Monitor abnormal behavior using the harness after inserting assertions, to discover vulnerabilities and design issues.
Must be run separately after coverage collection is complete, as assertions will change the execution flow.

            Args:
test_inputs: test input list
timeout: execution timeout

            Returns:
Assertion-based Monitoring Results:
                {
                    "test_case_count": int,
                    "assertion_failures": [...],
                    "anomaly_behaviors": [...],
                    "vulnerability_indicators": [...]
                }
            """
            logger.info(f"Mode B: Monitoring with assertions, {len(test_inputs)} inputs")

            try:
                # Execute the first input check assertion
                first_input = test_inputs[0] if test_inputs else ""
                exec_result = execute_with_assertions(
                    st_path=Path(self.st_path),
                    harness_path=Path(self.harness_path),
                    test_input=first_input
                )

                # Parse assertion failed
                assertion_failures = []
                anomaly_behaviors = []
                vulnerability_indicators = []

                if exec_result.raw_stderr:
                    for line in exec_result.raw_stderr.split('\n'):
                        if 'AUDIT FAIL:' in line or 'SECURITY_ASSERT' in line or 'SECURITY ASSERT' in line:
                            assertion_failures.append(line.strip())
                            # Classify anomalous behavior
                            line_lower = line.lower()
                            if "hazardous" in line_lower or "dangerous" in line_lower:
                                anomaly_behaviors.append("hazardous_state_detected")
                                vulnerability_indicators.append("high_risk")
                            elif "overflow" in line_lower or "underflow" in line_lower:
                                anomaly_behaviors.append("overflow_detected")
                                vulnerability_indicators.append("medium_risk")
                            elif "invalid" in line_lower or "out of" in line_lower:
                                anomaly_behaviors.append("invalid_value_detected")
                                vulnerability_indicators.append("low_risk")
                            elif "constraint" in line_lower or "violation" in line_lower:
                                anomaly_behaviors.append("constraint_violation")
                                vulnerability_indicators.append("medium_risk")

                # Risk assessment
                if vulnerability_indicators:
                    risk_counts = {"high_risk": 0, "medium_risk": 0, "low_risk": 0}
                    for r in vulnerability_indicators:
                        risk_counts[r] = risk_counts.get(r, 0) + 1
                    if risk_counts["high_risk"] > 0:
                        risk_assessment = "high"
                    elif risk_counts["medium_risk"] > 0:
                        risk_assessment = "medium"
                    else:
                        risk_assessment = "low"
                else:
                    risk_assessment = "low"

                return {
                    "test_case_count": len(test_inputs),
                    "assertion_failures": assertion_failures,
                    "anomaly_behaviors": anomaly_behaviors,
                    "vulnerability_indicators": vulnerability_indicators,
                    "risk_assessment": risk_assessment,
                    "execution_status": exec_result.status,
                    "exit_code": exec_result.return_code,
                    "mode": "B_assertion_monitoring",
                    "message": f"Mode B: Detected {len(assertion_failures)} assertion failures, Risk Assessment: {risk_assessment}"
                }

            except Exception as e:
                logger.error(f"monitor_with_assertions failed: {e}")
                return {"error": str(e), "mode": "B_error", "message": f"Mode B execution failed: {e}"}

        return monitor_with_assertions

    def _create_analyze_test_quality_tool(self):
        """Create a test case quality analysis tool."""

        @lc_tool
        def analyze_test_quality(
            coverage_data: Dict[str, Any],
            assertion_result: Dict[str, Any]
        ) -> Dict[str, Any]:
            """
Analyze test case quality and functional significance.

Combine coverage and assertion results to evaluate test completeness.

            Args:
coverage_data: Coverage data (from mode A)
assertion_result: Assertion result (from pattern B)

            Returns:
Quality analysis result:
                {
                    "test_case_summary": str,
                    "functional_analysis": str,
                    "quality_assessment": str,
                    "completeness": str
                }
            """
            logger.info("Analyzing test quality from both modes")

            try:
                # extract coverage data
                test_case_count = coverage_data.get("test_case_count", 0)
                coverage_summary = coverage_data.get("coverage_summary", {})
                quality_score = coverage_data.get("quality_score", 0)

                # Extract assertion result
                assertion_count = len(assertion_result.get("assertion_failures", []))
                anomaly_behaviors = assertion_result.get("anomaly_behaviors", [])
                risk_assessment = assertion_result.get("risk_assessment", "unknown")

                # Generate test case summary
                test_case_summary = f"Submitted {test_case_count} test cases"

                # Functional significance analysis
                functional_analysis_parts = []
                if assertion_count > 0:
                    functional_analysis_parts.append(f"Detected {assertion_count} assertion failures")
                if anomaly_behaviors:
                    functional_analysis_parts.append(f"Found anomalous behaviors: {', '.join(set(anomaly_behaviors))}")
                if risk_assessment != "low":
                    functional_analysis_parts.append(f"Risk Assessment: {risk_assessment}")
                functional_analysis = "; ".join(functional_analysis_parts) if functional_analysis_parts else "All assertions passed, no anomalies detected"

                # Evaluate completeness
                line_cov = coverage_summary.get("line_coverage", 0)
                if line_cov >= 80:
                    completeness = "sufficient"
                elif line_cov >= 50:
                    completeness = "moderate"
                else:
                    completeness = "insufficient"

                return {
                    "test_case_summary": test_case_summary,
                    "functional_analysis": functional_analysis,
                    "quality_assessment": f"Quality Score {quality_score}/100",
                    "completeness": completeness,
                    "message": f"Test Completeness: {completeness}, Functional Analysis: {functional_analysis}"
                }

            except Exception as e:
                logger.error(f"analyze_test_quality failed: {e}")
                return {"error": str(e), "message": f"Quality analysis failed: {e}"}

        return analyze_test_quality

    def _create_design_next_targets_tool(self):
        """Create the next round of test target design tools."""

        @lc_tool
        def design_next_targets(
            current_coverage: Dict[str, Any],
            completeness: str,
            risk_assessment: str = "medium"
        ) -> Dict[str, Any]:
            """
Design the next round of test objectives based on the current coverage rate.

Analyze uncovered code areas and generate targeted test suggestions.

            Args:
current coverage data
completeness: Test completeness evaluation
risk_assessment: risk assessment

            Returns:
Test target suggestions:
                {
                    "priority_targets": [...],
                    "suggested_inputs": [...],
                    "coverage_breakthrough": [...]
                }
            """
            logger.info("Designing next test targets")

            try:
                line_cov = current_coverage.get("line_coverage", 0)
                branch_cov = current_coverage.get("branch_coverage", 0)

                # Generate coverage breakthrough suggestions
                coverage_breakthrough = []
                suggested_inputs = []

                if line_cov < 50:
                    coverage_breakthrough.append("Current line coverage is low, need to increase basic functional testing")
                    suggested_inputs.append("Add normal path test cases")
                if branch_cov < 50:
                    coverage_breakthrough.append("Current branch coverage is low, need to increase boundary condition testing")
                    suggested_inputs.append("Add boundary value tests (max/min/zero)")

                if risk_assessment == "high":
                    coverage_breakthrough.append("High-risk issues detected, need targeted security testing")
                    suggested_inputs.append("Add abnormal input tests (overflow/invalid values)")
                elif risk_assessment == "medium":
                    coverage_breakthrough.append("Medium-risk issues detected, suggest increasing constraint testing")
                    suggested_inputs.append("Add constraint violation tests")

                # Priority target
                priority_targets = []
                if line_cov < 80:
                    priority_targets.append("Increase line coverage to above 80%")
                if branch_cov < 70:
                    priority_targets.append("Increase branch coverage to above 70%")
                if completeness == "insufficient":
                    priority_targets.append("Add error handling path tests")

                return {
                    "priority_targets": priority_targets,
                    "suggested_inputs": suggested_inputs,
                    "coverage_breakthrough": coverage_breakthrough,
                    "message": f"Suggestion: {'; '.join(coverage_breakthrough[:3])}"
                }

            except Exception as e:
                logger.error(f"design_next_targets failed: {e}")
                return {"error": str(e), "message": f"Target design failed: {e}"}

        return design_next_targets

    def _create_execute_with_coverage_tool(self):
        """Create execution and coverage collection tool (deprecated - use separated Mode A and Mode B)."""

        @lc_tool
        def execute_with_coverage(
            test_inputs: List[str],
            timeout: int = 5
        ) -> Dict[str, Any]:
            """
⚠️ Deprecated: This tool mixes two modes, violating design principles.

Please use:
- collect_coverage_baseline (Mode A): Coverage collection
- monitor_with_assertions (Mode B): assertion-based monitoring

Keep this tool only for backward compatibility; not recommended for use.
            """
            logger.warning("execute_with_coverage is deprecated, use separate modes")

            # For backward compatibility, use mode A
            return self._create_collect_coverage_baseline_tool().invoke({"test_inputs": test_inputs, "timeout": timeout})

    def _create_analyze_assertion_result_tool(self):
        """# Create a tool for analyzing assertion results."""

        @lc_tool
        def analyze_assertion_result(
            assertion_failures: List[str],
            coverage_data: Dict[str, Any]
        ) -> Dict[str, Any]:
            """
Analyze the validity of the assertion results.

Analyze the relationship between assertion failure and coverage to determine whether the assertion is effective.
Reveals coverage gap.

            Args:
assertion failure message list
coverage_data: coverage data

            Returns:
Assertion validity analysis result:
                {
                    "total_assertions": int,
                    "failed_assertions": int,
                    "assertion_effectiveness": "high" | "medium" | "low",
                    "coverage_insights": [...],
                    "recommendations": [...]
                }
            """
            logger.info(f"Tool: analyze_assertion_result with {len(assertion_failures)} failures")

            failed_count = len(assertion_failures)

            # Analyze assertion validity
            insights = []
            recommendations = []

            if failed_count > 0:
                insights.append(f"Detected {failed_count} assertion failures")
                insights.append("Assertions successfully captured anomalous behavior")

                # Analyze failure type
                for fail_msg in assertion_failures:
                    if "hazardous" in fail_msg.lower() or "dangerous" in fail_msg.lower():
                        insights.append("Detected hazardous state assertion")
                        recommendations.append("Prioritize fixing hazardous state related code")
                    elif "overflow" in fail_msg.lower():
                        insights.append("Detected overflow assertion")
                        recommendations.append("Check boundary condition handling")
            else:
                insights.append("All assertions passed")
                recommendations.append("Consider adding more boundary condition tests")

            # Evaluate assertion effectiveness
            effectiveness = "medium"
            if failed_count > 0:
                effectiveness = "high"
            elif coverage_data.get("line_percent", 0) < 50:
                effectiveness = "low"
                recommendations.append("Current coverage is low, assertions may not be fully tested")

            return {
                "total_assertions": len(assertion_failures),
                "failed_assertions": failed_count,
                "assertion_effectiveness": effectiveness,
                "coverage_insights": insights,
                "recommendations": recommendations,
                "message": f"Assertion Effectiveness: {effectiveness}"
            }

        return analyze_assertion_result

    def _create_design_coverage_target_tool(self):
        """Tool for designing test objectives for the next round."""

        @lc_tool
        def design_coverage_target(
            current_coverage: Dict[str, Any],
            uncovered_lines: List[int],
            test_intent: str
        ) -> Dict[str, Any]:
            """
Based on the current coverage, design the next round of test objectives.

Analyze uncovered code lines and generate targeted test suggestions.

            Args:
current coverage data
list of uncovered code lines
test intent description

            Returns:
Test target suggestion:
                {
                    "priority_targets": [...],
                    "suggested_inputs": [...],
                    "expected_coverage_gain": float,
                    "strategy": str
                }
            """
            logger.info(f"Tool: design_coverage_target with {len(uncovered_lines)} uncovered lines")

            # Simplified version: generate suggestions based on uncovered lines
            # In actual implementation, LLM can be used to analyze code structure

            priority_targets = []
            suggested_inputs = []

            # Analyze the pattern of uncovered lines
            if uncovered_lines:
                # Group by line number
                line_groups = []
                current_group = [uncovered_lines[0]]
                for line in uncovered_lines[1:]:
                    if line == current_group[-1] + 1:
                        current_group.append(line)
                    else:
                        line_groups.append(current_group)
                        current_group = [line]
                line_groups.append(current_group)

                # Generate targets for each group
                for group in line_groups[:5]:  # Up to 5 targets
                    if len(group) == 1:
                        priority_targets.append(f"line {group[0]}")
                    else:
                        priority_targets.append(f"lines {group[0]}-{group[-1]}")

                # Generate suggested input (simplified version)
                suggested_inputs = [
                    "Test boundary values: max/min/zero",
                    "Test abnormal inputs: overflow/underflow",
                    "Test state transitions: trigger uncovered branches"
                ]

            # Estimate coverage gain
            current_cov = current_coverage.get("line_percent", 0)
            expected_gain = min(20, (100 - current_cov) * 0.3)

            return {
                "priority_targets": priority_targets,
                "suggested_inputs": suggested_inputs,
                "expected_coverage_gain": round(expected_gain, 1),
                "strategy": f"Design tests for {len(priority_targets)} uncovered areas",
                "message": f"Suggest testing {len(priority_targets)} uncovered areas, expected coverage gain: {expected_gain:.1f}%"
            }

        return design_coverage_target

    # ========================================================================
    # Public API
    # ========================================================================

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self.registry

    def get_langchain_tools(self) -> List:
        """Get all tools in LangChain format."""
        return self.registry.to_langchain_tools()

    def get_tool(self, name: str):
        """Get a specific tool by name."""
        return self.registry.get(name)

    def list_tools(self) -> List[str]:
        """List all available tools."""
        return [spec.name for spec in self.registry.list_tools()]


__all__ = ["TestAnalysisToolManager"]
