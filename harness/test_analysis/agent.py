"""
Test Analysis Agent - Autonomous test coverage analysis.

Refer to the design of Generator Agent, provide autonomous test coverage analysis functionality.

Usage:
    from harness.test_analysis.agent import TestAnalysisAgent

    agent = TestAnalysisAgent(
        st_path="path/to/file.st",
        harness_path="path/to/harness.c"
    )

    report = agent.analyze(
Analyze the coverage completeness of channel boundary condition tests
        test_inputs=["80\\n", "100\\n", "0\\n"]
    )
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# LangChain imports
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage
)
from langchain_openai import ChatOpenAI

# Project root: agent.py → test_analysis → harness → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

# Config imports
import importlib.util
spec = importlib.util.spec_from_file_location("config", PROJECT_ROOT / "config.py")
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)

# PLCHaT imports - global relative position references
from core.data_types.test_analysis_types import TestCaseReport, TestIntent
from harness.test_analysis.tool_manager import TestAnalysisToolManager


logger = logging.getLogger(__name__)


class TestAnalysisAgent:
    """
Test Analysis Agent - autonomous test coverage analysis.

Use LLM and toolchain to analyze the coverage completeness of test cases:
- Run tests and collect coverage
- Analyze assertion validity
- Identify coverage gaps
# Generate analysis report

Design reference:
- Autonomous loop mode of Generator Agent
- ToolManager tool registration
- LLM tool calling
    """

    def __init__(
        self,
        st_path: str,
        harness_path: str,
        custom_tools: Optional[Dict[str, Any]] = None,
        tool_registry: Optional[Any] = None
    ):
        """
Initialize Test Analysis Agent.

        Args:
: ST source code path
harness_path: Harness code path
custom_tools: optional custom tool dictionary
tool_registry: optional custom ToolRegistry
        """
        self.st_path = st_path
        self.harness_path = harness_path

        # Read ST code
        try:
            self.st_code = Path(st_path).read_text(encoding='utf-8')
        except Exception as e:
            raise ValueError(f"Failed to read ST file {st_path}: {e}")

        # Initialize tool manager
        self.tool_manager = TestAnalysisToolManager(
            st_path=st_path,
            harness_path=harness_path,
            tool_registry=tool_registry
        )

        # Get the registry
        self.registry = self.tool_manager.get_registry()

        # Initialize LLM
        self.llm = ChatOpenAI(
            temperature=0.3,
            model=config_module.generator_model,
            api_key=config_module.generator_api_key,
            base_url=config_module.generator_base_url,
        )

        # Binding tool
        self.llm_with_tools = self.llm.bind_tools(
            self.tool_manager.get_langchain_tools()
        )

        # Metadata tracking
        self.metadata = {
            "input_tokens": 0,
            "output_tokens": 0,
            "api_calls": 0,
            "tools_used": {}
        }

    def analyze(
        self,
        test_intent: str,
        test_inputs: List[str],
        max_tool_calls: int = 5
    ) -> TestCaseReport:
        """
Analyze the coverage completeness of test cases.

        Args:
test_intent: test intent description
test_inputs: test input list
max_tool_calls: Maximum number of tool calls

        Returns:
TestCaseReport: test analysis report
        """
        logger.info(f"Starting analysis: {test_intent}")

        # Reset metadata
        self._reset_metadata()

        # Format prompt
        tool_definitions = self._get_tool_definitions()
        prompt = self._format_initial_prompt(
            test_intent=test_intent,
            input_count=len(test_inputs),
            tool_definitions=tool_definitions
        )

        # Agent loop
        messages = [
            SystemMessage(content=self._get_system_directive()),
            HumanMessage(content=prompt)
        ]

        analysis_result = {
            "test_scenario": test_intent,
            "findings": [],
            "assertion_results": [],
            "coverage_data": None,
            "coverage_insights": []
        }

        for call_count in range(max_tool_calls):
            response = self.llm_with_tools.invoke(messages)

            # Track metadata
            self._track_response(response)

            logger.debug(f"LLM Response (call {call_count + 1}):")
            logger.debug(f"  - Has tool_calls: {hasattr(response, 'tool_calls') and bool(response.tool_calls)}")

            # Check tool call
            if not isinstance(response, AIMessage) or not response.tool_calls:
                logger.debug("No tool calls, stopping.")
                # Extract LLM's final analysis
                if hasattr(response, 'content'):
                    analysis_result["llm_summary"] = response.content
                break

            messages.append(response)

            # Execute each tool call
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                arguments = tool_call["args"]

                logger.info("=" * 60)
                logger.info(f"🔀 [ROUTING] LLM selected tool: {tool_name}")
                logger.info("=" * 60)
                logger.info(f"📋 [PARAMS] LLM injected parameters:")
                for key, value in arguments.items():
                    logger.info(f"     - {key}: {value}")
                logger.info("=" * 60)

                try:
                    result = self._execute_tool(tool_name, arguments)

                    # Update analysis results
                    self._update_analysis_result(analysis_result, tool_name, result)

                    # Format the results and feed back to LLM
                    result_msg = self._format_tool_result(result)
                    messages.append(ToolMessage(
                        content=result_msg,
                        tool_call_id=tool_call["id"]
                    ))

                    # Track tool usage
                    if tool_name not in self.metadata["tools_used"]:
                        self.metadata["tools_used"][tool_name] = 0
                    self.metadata["tools_used"][tool_name] += 1

                except Exception as e:
                    import traceback
                    logger.error(f"Tool execution failed: {str(e)}")
                    logger.error(f"Traceback:\n{traceback.format_exc()}")
                    error_msg = f"Tool execution failed: {str(e)}"
                    messages.append(ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call["id"]
                    ))

        # Generate final report
        return self._generate_report(analysis_result)

    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute the tool and return the result."""
        # Get tool from registry
        spec = self.registry.get(tool_name)
        if not spec:
            raise ValueError(f"Tool not found: {tool_name}")

        # Execute according to tool type
        if spec.tool_type == "langchain":
            # LangChain tool - with invoke()
            logger.debug(f"Calling LangChain tool: {tool_name}")
            raw_result = spec.implementation.invoke(arguments)
            logger.debug(f"Tool result type: {type(raw_result)}")
            return raw_result
        else:
            raise ValueError(f"Unknown tool type: {spec.tool_type}")

    def _update_analysis_result(
        self,
        analysis_result: Dict[str, Any],
        tool_name: str,
        tool_result: Any
    ):
        """Update analysis results based on tool results (v2: supports two modes)."""
        if tool_name == "collect_coverage_baseline" or tool_name == "collect_coverage_baseline":
            # Mode A: coverage collection
            if isinstance(tool_result, dict):
                analysis_result["coverage_data"] = tool_result.get("coverage_summary", {})
                analysis_result["test_case_count"] = tool_result.get("test_case_count", 0)
                analysis_result["quality_score"] = tool_result.get("quality_score", 0)
                analysis_result["mode_a_complete"] = True

        elif tool_name == "monitor_with_assertions" or tool_name == "monitor_with_assertions":
            # Pattern B: Assertion-based monitoring
            if isinstance(tool_result, dict):
                analysis_result["assertion_results"] = tool_result.get("assertion_failures", [])
                analysis_result["anomaly_behaviors"] = tool_result.get("anomaly_behaviors", [])
                analysis_result["risk_assessment"] = tool_result.get("risk_assessment", "unknown")
                analysis_result["execution_status"] = tool_result.get("execution_status", "unknown")
                analysis_result["mode_b_complete"] = True

        elif tool_name == "analyze_test_quality" or tool_name == "analyze_test_quality":
            # Comprehensive analysis
            if isinstance(tool_result, dict):
                analysis_result["test_case_summary"] = tool_result.get("test_case_summary", "")
                analysis_result["functional_analysis"] = tool_result.get("functional_analysis", "")
                analysis_result["completeness"] = tool_result.get("completeness", "unknown")

        elif tool_name == "design_next_targets" or tool_name == "design_next_targets":
            # Next step suggestion
            if isinstance(tool_result, dict):
                analysis_result["coverage_breakthrough"] = tool_result.get("coverage_breakthrough", [])
                analysis_result["suggested_inputs"] = tool_result.get("suggested_inputs", [])
                analysis_result["priority_targets"] = tool_result.get("priority_targets", [])

        # Backward compatibility
        elif tool_name == "execute_with_coverage":
            if isinstance(tool_result, dict):
                analysis_result["coverage_data"] = tool_result.get("coverage_details", {})
                analysis_result["assertion_results"] = tool_result.get("assertion_failures", [])
                analysis_result["execution_status"] = tool_result.get("execution_status")

    def _generate_report(self, analysis_result: Dict[str, Any]) -> TestCaseReport:
        """Generate the final test report (v2: complete four-part report)."""
        # 1. Test case input summary
        test_case_count = analysis_result.get("test_case_count", 0)
        test_case_summary = analysis_result.get("test_case_summary", f"Input {test_case_count} test cases")

        # 2. Functional significance analysis
        functional_analysis = analysis_result.get("functional_analysis", "")
        risk_assessment = analysis_result.get("risk_assessment", "unknown")
        anomaly_behaviors = analysis_result.get("anomaly_behaviors", [])

        # 3. Test case quality assessment
        coverage = analysis_result.get("coverage_data", {})
        quality_score = analysis_result.get("quality_score", 0)
        completeness = analysis_result.get("completeness", "unknown")

        # 4. Next Steps Suggestion
        coverage_breakthrough = analysis_result.get("coverage_breakthrough", [])
        suggested_inputs = analysis_result.get("suggested_inputs", [])

        # Build discovery list
        findings = []
        if test_case_summary:
            findings.append(f"[Test Cases] {test_case_summary}")
        if functional_analysis:
            findings.append(f"[Functional Analysis] {functional_analysis}")
        if completeness:
            findings.append(f"[Test Completeness] {completeness}")
        if coverage_breakthrough:
            findings.append(f"[Coverage Breakthrough] {'; '.join(coverage_breakthrough[:3])}")

        # Build executive summary
        line_cov = coverage.get("line_coverage", 0) if isinstance(coverage, dict) else 0
        branch_cov = coverage.get("branch_coverage", 0) if isinstance(coverage, dict) else 0
        execution_summary = (
            f"Input {test_case_count} test cases, "
            f"line coverage {line_cov:.1f}%, branch coverage {branch_cov:.1f}%, "
            f"quality score {quality_score}/100, risk assessment {risk_assessment}"
        )

        return TestCaseReport(
            case_id=Path(self.st_path).stem,
            test_scenario=analysis_result["test_scenario"],
            findings=findings,
            execution_summary=execution_summary,
            assertion_results=analysis_result.get("assertion_results", []),
            analysis_time_sec=0.0,
            confidence_score=0.8  # Based on tool call result
        )

    def _format_tool_result(self, result: Any) -> str:
        """Formatting tool results are used for LLM feedback."""
        if isinstance(result, dict):
            if "message" in result:
                return result["message"]
            if "error" in result:
                return f"Error: {result['error']}"
            # Simplify output
            simplified = {}
            for key, value in result.items():
                if isinstance(value, (str, int, float, bool)):
                    simplified[key] = value
                elif isinstance(value, list):
                    simplified[key] = f"[{len(value)} items]"
                else:
                    simplified[key] = f"{type(value).__name__}"
            return f"Result: {simplified}"
        return str(result)[:500]  # Limit length

    def _format_initial_prompt(
        self,
        test_intent: str,
        input_count: int,
        tool_definitions: str
    ) -> str:
        """Format the initial prompt (v2: two-stage analysis process)."""
        return f"""You are a test analysis expert. Please analyze the coverage completeness of the following tests.

**Test intent:** {test_intent}

**Test input:** {input_count} test cases

**Available tools:**
{tool_definitions}

**Important - Two-stage analysis process:**

Phase 1 - Coverage Collection (Mode A):
1. Call collect_coverage_baseline to collect coverage baseline
2. Use the original harness, do not insert assertions

Phase 2 - Assertive Monitoring (Mode B):
3. Call monitor_with_assertions to perform assertion-based monitoring
4. Use patched harness to detect abnormal behavior.

Comprehensive analysis:
5. Call analyze_test_quality to comprehensively evaluate quality and functional significance
6. Call design_next_targets to get next step suggestions

Please start the analysis.
"""

    def _get_system_directive(self) -> str:
        """Get system instruction (v2: two-stage analysis)."""
        return """You are a test analysis expert, focusing on analyzing the coverage completeness of test cases.

Your task is:
Execute tests and collect coverage data (Mode A: Using original harness)
2. Use assertions to monitor program execution (Mode B: Using patched harness)
3. Analyze test case quality and functional significance
4. Provide suggestions for coverage breakthrough

**Important principle:**
- Coverage collection and assertion-based monitoring must run separately
- First run mode A to evaluate test quality, then run mode B to discover abnormal behavior
- Combine the results of the two modes to generate a complete report

Use available tools to obtain actual data, do not guess results.
"""

    def _get_tool_definitions(self) -> str:
        """Get the tool description."""
        definitions = []
        for spec in self.registry.list_tools():
            if spec.name.startswith("test_analysis_"):  # Only include the tools we registered
                definitions.append(f"- {spec.name}: {spec.description}")
        return "\n".join(definitions) if definitions else "No available tools"

    def _reset_metadata(self):
        """Reset metadata tracking."""
        self.metadata = {
            "input_tokens": 0,
            "output_tokens": 0,
            "api_calls": 0,
            "tools_used": {}
        }

    def _track_response(self, response):
        """# Track token usage."""
        self.metadata["api_calls"] += 1
        if hasattr(response, "response_metadata"):
            usage = response.response_metadata.get("token_usage", {})
            self.metadata["input_tokens"] += usage.get("prompt_tokens", 0)
            self.metadata["output_tokens"] += usage.get("completion_tokens", 0)

    def list_available_tools(self) -> List[str]:
        """List all available tools."""
        return self.tool_manager.list_tools()


__all__ = ["TestAnalysisAgent"]
