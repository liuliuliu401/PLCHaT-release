"""
Generator Agent - Test Case Generation for PLC Programs

Migrated from: FuzzGen/agents/generator.py
Simplified: Core test generation with 3 tools, autonomous agent design.

Usage:
    from agents import Generator

    generator = Generator(
        st_path="path/to/file.st",
        benchmark_dir="path/to/benchmark"
    )

    cases = generator.generate(
        goal="Trigger stack overflow",
        strategy=ExecutionStrategy.BOUNDARY_MUTATION
    )
"""

from pathlib import Path
import sys
import json
import uuid
import logging
from typing import List, Dict, Any, Optional, Union, Callable

# LangChain imports
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage
)
from langchain_openai import ChatOpenAI

# Project root resolution
# agents/generator.py → agents → PROJECT_ROOT (2 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Config imports - import from config.py file (not config package)
# Use importlib to avoid config/__init__.py shadowing
import importlib.util
spec = importlib.util.spec_from_file_location("config", PROJECT_ROOT / "config.py")
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)

generator_model = config_module.generator_model
generator_api_key = config_module.generator_api_key
generator_base_url = config_module.generator_base_url

# PLCHaT imports
from core.data_types.plan_types import (
    ExecutionStrategy,
    PlanPayload
)
from core.data_types.exp_types import ExpUnifiedIR
from core.protocols.action_protocol import (
    ToolCallRequest,
    ActionType
)

# Local imports
from .prompts import GeneratorPrompts
from .tool_manager import GeneratorToolManager

# Tool Registry - MCP-compatible design
from harness.registry.tool_registry import ToolRegistry, registry


# Module logger
logger = logging.getLogger(__name__)


class Generator:
    """
    Generator Agent - Autonomous test case generation.

    Generates test cases for PLC programs using:
    - Symbolic execution (SMT/Z3)
    - LLM-based white-box generation
    - Coverage-guided random fuzzing

    This is an autonomous agent that can be used in workflows.
    """

    def __init__(
        self,
        st_path: str,
        benchmark_dir: str,
        custom_tools: Optional[Dict[str, Any]] = None,
        tool_registry: Optional[ToolRegistry] = None
    ):
        """
        Initialize the Generator agent.

        Args:
            st_path: Path to the ST source file (must exist and be readable)
            benchmark_dir: Path to the benchmark directory
            custom_tools: Optional dict of custom tool instances to inject
                           {"smt_tool": SMTTool, ...}
            tool_registry: Optional custom ToolRegistry instance

        Raises:
            FileNotFoundError: If ST file does not exist
            ValueError: If ST file is empty or cannot be read
        """
        self.st_path = st_path
        self.benchmark_dir = benchmark_dir

        # Validate and read ST code at initialization (fail fast)
        try:
            st_code = Path(st_path).read_text(encoding='utf-8')
        except FileNotFoundError:
            raise FileNotFoundError(f"ST file not found: {st_path}")
        except PermissionError:
            raise PermissionError(f"No permission to read ST file: {st_path}")
        except Exception as e:
            raise ValueError(f"Failed to read ST file {st_path}: {e}")

        if not st_code.strip():
            raise ValueError(f"ST file is empty: {st_path}")

        self.st_code = st_code

        # Default schema path (can be overridden via context)
        self.schema_path = Path(benchmark_dir) / "input" / "input_schema_v2.json"

        # Initialize tool manager (decouples tool registration logic)
        self.tool_manager = GeneratorToolManager(
            benchmark_dir=benchmark_dir,
            st_path=st_path,
            st_code=st_code,
            custom_tools=custom_tools,
            tool_registry=tool_registry
        )

        # Get registry from tool manager
        self.registry = self.tool_manager.get_registry()

        # Initialize LLM - using config from config.py
        self.llm = ChatOpenAI(
            temperature=0.3,
            model=generator_model,
            api_key=generator_api_key,
            base_url=generator_base_url,
        )

        # Set LLM reference for tools that need it (whitebox_generate)
        self.tool_manager.set_llm_reference(
            llm=self.llm,
            schema_loader=lambda: self._load_schema()
        )

        # Bind tools from registry
        self.llm_with_tools = self.llm.bind_tools(
            self.tool_manager.get_langchain_tools()
        )

        # Metadata tracking
        self.metadata = {
            "input_tokens": 0,
            "output_tokens": 0,
            "api_calls": 0,
            "tools_used": {},
            "tool_log": []
        }

    # ========================================================================
    # Public API
    # ========================================================================

    def generate(
        self,
        goal: str,
        strategy: Optional[ExecutionStrategy] = None,
        context: Optional[Dict[str, Any]] = None,
        max_tool_calls: int = 3
    ) -> List[ExpUnifiedIR]:
        """
        Generate test cases for the given goal.

        Args:
            goal: Description of the test generation goal
            strategy: Recommended strategy (optional)
            context: Additional context (seed cases, etc.)
            max_tool_calls: Maximum number of tool calls to make

        Returns:
            List of generated test cases (ExpUnifiedIR)
        """
        if context is None:
            context = {}

        # Extract schema_path from context if available (for workflow integration)
        current_schema_path = context.get("schema_path", self.schema_path)

        # Reset metadata
        self._reset_metadata()

        # Format prompt
        tool_definitions = self._get_tool_definitions()
        input_schema = self._load_schema(current_schema_path)

        strategy_str = strategy.value if strategy else "auto"
        prompt = GeneratorPrompts.format_initial_prompt(
            st_path=self.st_path,
            goal=goal,
            strategy=strategy_str,
            context=context,
            tool_definitions=tool_definitions,
            input_schema=input_schema
        )

        # Agent loop
        messages = [
            SystemMessage(content=GeneratorPrompts.CAMPAIGN_DIRECTIVE),
            HumanMessage(content=prompt)
        ]

        generated_cases = []

        for call_count in range(max_tool_calls):
            response = self.llm_with_tools.invoke(messages)

            # Track metadata
            self._track_response(response)

            # Debug logging
            logger.debug(f"LLM Response (call {call_count + 1}):")
            logger.debug(f"  - Type: {type(response).__name__}")
            logger.debug(f"  - Has tool_calls: {hasattr(response, 'tool_calls') and bool(response.tool_calls)}")
            if hasattr(response, 'tool_calls') and response.tool_calls:
                logger.debug(f"  - Tool call count: {len(response.tool_calls)}")
                for tc in response.tool_calls:
                    logger.debug(f"    - Tool: {tc.get('name', 'unknown')}")
            elif hasattr(response, 'content'):
                content_preview = str(response.content)[:200]
                logger.debug(f"  - Content preview: {content_preview}...")

            # Check for tool calls
            if not isinstance(response, AIMessage) or not response.tool_calls:
                logger.debug("No tool calls, stopping.")
                break

            messages.append(response)

            # Execute each tool call
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                arguments = tool_call["args"]

                # Log routing decision
                logger.info("="*60)
                logger.info(f"🔀 [ROUTING] LLM Selected Tool: {tool_name}")
                logger.info("="*60)
                logger.info(f"📋 [PARAMS] Injected by LLM:")
                for key, value in arguments.items():
                    logger.info(f"     - {key}: {value}")
                logger.info("="*60)

                try:
                    result = self._execute_tool(tool_name, arguments, context)
                    logger.debug(f"Tool execution result: {type(result)}, {len(result) if hasattr(result, '__len__') else 'N/A'} items")
                    if result:
                        for i, r in enumerate(result[:3]):
                            logger.debug(f"    - Result {i+1}: {type(r).__name__}")
                            if hasattr(r, 'exp_id'):
                                logger.debug(f"      exp_id: {r.exp_id}")

                    generated_cases.extend(result)

                    # Format result for LLM
                    result_msg = self._format_tool_result(result)
                    messages.append(ToolMessage(
                        content=result_msg,
                        tool_call_id=tool_call["id"]
                    ))

                    # Track tool usage
                    if tool_name not in self.metadata["tools_used"]:
                        self.metadata["tools_used"][tool_name] = 0
                    self.metadata["tools_used"][tool_name] += 1
                    self.metadata["tool_log"].append({
                        "tool": tool_name,
                        "args": {k: (str(v)[:120]) for k, v in arguments.items()},
                        "n_results": len(result) if hasattr(result, "__len__") else 0,
                        "status": "ok",
                    })

                except Exception as e:
                    import traceback
                    logger.error(f"Tool execution failed: {str(e)}")
                    logger.error(f"Traceback:\n{traceback.format_exc()}")
                    error_msg = f"Tool execution failed: {str(e)}"
                    self.metadata["tool_log"].append({
                        "tool": tool_name,
                        "args": {k: (str(v)[:120]) for k, v in arguments.items()},
                        "n_results": 0,
                        "status": "error",
                        "error": str(e)[:200],
                    })
                    messages.append(ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call["id"]
                    ))

        # Attach metadata to cases
        for case in generated_cases:
            if hasattr(case, "metadata"):
                case.metadata["generator"] = self.metadata.copy()

        return generated_cases

    # ========================================================================
    # Internal Methods
    # ========================================================================

    def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[ExpUnifiedIR]:
        """Execute a tool and return ExpUnifiedIR cases."""
        # Get tool from registry
        spec = self.registry.get(tool_name)
        if not spec:
            raise ValueError(f"Tool not found: {tool_name}")

        logger.debug(f"Tool spec: name={spec.name}, type={spec.tool_type}")

        # Execute based on tool type
        if spec.tool_type == "langchain":
            # LangChain tool - has invoke()
            logger.debug(f"Invoking LangChain tool...")
            raw_result = spec.implementation.invoke(arguments)
            logger.debug(f"LangChain tool result type: {type(raw_result)}")
            logger.debug(f"LangChain tool result: {raw_result}")
        elif spec.tool_type == "basetool":
            # BaseTool - needs ToolCallRequest
            request = ToolCallRequest(
                action_id=tool_name,
                action_type=ActionType.GENERATE,
                tool_name=tool_name,
                parameters=arguments
            )
            response = spec.implementation.execute(request)
            raw_result = self._format_action_response(response)
            logger.debug(f"BaseTool result: {raw_result}")
        else:
            raise ValueError(f"Unknown tool type: {spec.tool_type}")

        # Convert to ExpUnifiedIR
        cases = self._convert_to_exp_ir(raw_result)
        logger.debug(f"Converted to {len(cases)} ExpUnifiedIR cases")
        return cases

    def _format_action_response(self, response) -> Any:
        """Format ActionResponse for LLM consumption."""
        # Check if response has test_cases
        if hasattr(response, 'data') and response.data:
            if "exp_ir" in response.data:
                return [response.data["exp_ir"]]
            elif "generated_cases" in response.data:
                return response.data["generated_cases"]
            return response.data
        # Return raw response
        return response

    def _convert_to_exp_ir(self, raw_result: Any) -> List[ExpUnifiedIR]:
        """Convert tool output to ExpUnifiedIR list.
        
        Handles multiple formats:
        - Already ExpUnifiedIR objects
        - Dicts with sparse_timeline (converted to ExpUnifiedIR)
        - Error dicts (skipped with log)
        """
        cases = []

        # Handle None or non-iterable
        if not raw_result:
            return cases

        # Handle single dict
        if isinstance(raw_result, dict):
            raw_result = [raw_result]

        # Handle different output formats
        if isinstance(raw_result, list):
            for item in raw_result:
                if isinstance(item, ExpUnifiedIR):
                    cases.append(item)
                elif isinstance(item, dict):
                    # Skip error dicts
                    if "error" in item:
                        logger.warning(f"Tool returned error: {item.get('error', 'Unknown')}")
                        continue

                    # Convert dict to ExpUnifiedIR
                    try:
                        if "sparse_timeline" in item:
                            item.setdefault("exp_id", f"gen_{uuid.uuid4().hex[:6]}")
                            item.setdefault("target_st_path", self.st_path)
                            item.setdefault("schema_path", str(self.schema_path))
                            item.setdefault("tester_type", "Generator")
                            item.setdefault("total_cycles", len(item.get("sparse_timeline", {})))
                            cases.append(ExpUnifiedIR(**item))
                        elif "generated_cases" in item:
                            # Handle tool wrapper format: {"status":..., "generated_cases": [...]}
                            sub_cases = item["generated_cases"]
                            processed = self._convert_to_exp_ir(sub_cases)
                            cases.extend(processed)
                        elif "exp_ir" in item:
                            # Handle Single-item wrapper
                            processed = self._convert_to_exp_ir([item["exp_ir"]])
                            cases.extend(processed)
                        else:
                            logger.warning(f"Dict missing sparse_timeline, keys: {list(item.keys())[:5]}")
                    except Exception as e:
                        logger.warning(f"Failed to convert dict to ExpUnifiedIR: {e}")
                        # Debug: show what we got
                        if isinstance(item, dict):
                            logger.debug(f"  Dict keys: {list(item.keys())[:10]}")

        return cases


    def _format_tool_result(self, result: List[ExpUnifiedIR]) -> str:
        """Format tool result for LLM feedback."""
        if not result:
            return "No test cases generated."

        return f"Generated {len(result)} test case(s). First case ID: {result[0].exp_id}"

    # ========================================================================
    # Dynamic Tool Injection
    # ========================================================================

    def inject_tool(
        self,
        tool_func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None
    ):
        """
        Inject a new tool at runtime.

        After injection, the tool becomes available to the LLM for
        subsequent generate() calls.

        Args:
            tool_func: Callable function decorated with @tool or plain function
            name: Optional custom name (defaults to function name)
            description: Optional custom description (defaults to docstring)

        Example:
            @tool
            def custom_analyzer(goal: str, depth: int = 1) -> Dict[str, Any]:
                '''Analyze code for patterns.'''
                return {"patterns": [...]}

            agent.inject_tool(custom_analyzer)
        """
        tool_name = name or tool_func.__name__

        # Delegate to tool manager
        self.tool_manager.inject_tool(tool_func, name=tool_name, description=description)

        # Re-bind tools to include the new one
        self.llm_with_tools = self.llm.bind_tools(self.tool_manager.get_langchain_tools())

        return tool_name

    def list_available_tools(self) -> List[str]:
        """
        List all tools currently available to the agent.

        Returns: List of tool names.
        """
        return self.tool_manager.list_tools()

    def _load_schema(self, schema_path: Optional[Path] = None) -> Dict[str, Any]:
        """Load input schema."""
        try:
            path = schema_path or self.schema_path
            if path and Path(path).exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _get_tool_definitions(self) -> str:
        """Get tool descriptions for prompt."""
        definitions = []
        for spec in self.registry.list_tools():
            definitions.append(f"- {spec.name}: {spec.description}")
        return "\n".join(definitions)

    def _reset_metadata(self):
        """Reset metadata tracking."""
        self.metadata = {
            "input_tokens": 0,
            "output_tokens": 0,
            "api_calls": 0,
            "tools_used": {},
            "tool_log": []
        }

    def _track_response(self, response):
        """Track token usage from response."""
        self.metadata["api_calls"] += 1
        if hasattr(response, "response_metadata"):
            usage = response.response_metadata.get("token_usage", {})
            self.metadata["input_tokens"] += usage.get("prompt_tokens", 0)
            self.metadata["output_tokens"] += usage.get("completion_tokens", 0)


__all__ = ["Generator"]
