"""
LLM Router - Agent specifies tools, Router handles parameter injection

The agent specifies tools via simple parameters; the Router automatically
injects complex objects (ST code, full test cases, etc.).
"""

from pathlib import Path
import sys
import re
import json
import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_types.exp_types import ExpUnifiedIR
from core.data_types.plan_types import ExecutionStrategy
from core.protocols.action_protocol import ToolCallRequest, ActionType
from tools.fuzzers.random import RandomFuzzerTool
from tools.solvers import SMTTool
from tools.fuzzers.dse import DSETool


@dataclass
class RouterRequest:
    """Router request - simple agent input"""
    goal: str                          # Goal description
    strategy: Optional[str] = None     # Strategy name
    seed_case_id: Optional[str] = None # Case ID reference (not the full object)
    target_details: Optional[str] = None # Specific goal details
    # Simple parameters, no complex objects


@dataclass
class InjectedContext:
    """Injected context - complex tool inputs"""
    st_path: str                       # ST file path
    st_code: str                       # ST code content (read automatically)
    schema_path: str                   # Schema path
    seed_case: Optional[ExpUnifiedIR] = None  # Full test case object (resolved automatically)
    snapshot: Optional[Dict] = None     # Execution snapshot
    goal: str = ""
    target_details: str = ""
    # Full objects required for tool execution


class LLMRouter:
    """
    LLM Router - Agent specifies tools, Router handles injection

    Responsibilities:
    1. Receive simple agent parameters (goal, seed_case_id)
    2. Inject complex objects (st_code, full ExpUnifiedIR, schema_path)
    3. Call the corresponding tool
    4. Return the generated test cases

    Agent usage:
        router.route("solve_with_z3", RouterRequest(goal="trigger overflow"), context)

    The Router handles automatically:
        - seed_case_id -> ExpUnifiedIR object
        - st_path -> st_code content
        - benchmark_dir -> schema_path
    """

    def __init__(self, st_path: str, benchmark_dir: str):
        """
        Initialize the Router

        Args:
            st_path: ST source file path
            benchmark_dir: benchmark directory
        """
        self.st_path = st_path
        self.benchmark_dir = benchmark_dir
        self.schema_path = Path(benchmark_dir) / "input" / "input_schema_v2.json"

        # Case ID registry for resolution
        self._case_registry: Dict[str, ExpUnifiedIR] = {}

        # Initialize harness tools
        self.smt_tool = SMTTool(benchmark_dir)
        self.random_tool = RandomFuzzerTool(benchmark_dir)
        self.dse_tool = DSETool(benchmark_dir)

    def route(
        self,
        tool_name: str,
        request: RouterRequest,
        context: Optional[Dict[str, Any]] = None
    ) -> List[ExpUnifiedIR]:
        """
        Route a tool call

        Args:
            tool_name: tool name specified by the agent
            request: simple agent input
            context: context containing existing test cases, snapshots, etc.

        Returns:
            List of generated test cases
        """
        if context is None:
            context = {}

        # 1. Inject complex objects
        injected = self._inject_context(request, context)

        # 2. Call the tool
        try:
            return self._execute_tool(tool_name, injected)
        except Exception as e:
            print(f"[Router] Tool execution failed: {e}")
            return []

    def _inject_context(
        self,
        request: RouterRequest,
        context: Dict[str, Any]
    ) -> InjectedContext:
        """Inject simple parameters as complex objects"""

        # Read ST code
        try:
            st_code = Path(self.st_path).read_text(encoding='utf-8')
        except Exception as e:
            st_code = ""

        # Resolve seed_case_id into the full object
        seed_case = None
        if request.seed_case_id:
            seed_case = self._resolve_case_id(request.seed_case_id, context)

        # Extract snapshot
        snapshot = context.get("last_snapshot", context.get("snapshot", {}))

        return InjectedContext(
            st_path=self.st_path,
            st_code=st_code,
            schema_path=str(self.schema_path),
            seed_case=seed_case,
            snapshot=snapshot,
            goal=request.goal,
            target_details=request.target_details or ""
        )

    def _resolve_case_id(
        self,
        case_id: str,
        context: Dict[str, Any]
    ) -> Optional[ExpUnifiedIR]:
        """
        Resolve a case ID into the full object

        Supports multiple reference styles:
        1. Direct ID match
        2. Context key match
        3. Regex match (fault tolerance)
        """
        # 1. Check local registry
        if case_id in self._case_registry:
            return self._case_registry[case_id]

        # 2. Check context
        if case_id in context:
            val = context[case_id]
            if isinstance(val, ExpUnifiedIR):
                return val
            elif isinstance(val, dict):
                if "sparse_timeline" in val:
                    return ExpUnifiedIR(**val)

        # 3. Check regex match (fault tolerance)
        for key, val in context.items():
            if isinstance(val, ExpUnifiedIR):
                if case_id in val.exp_id or re.search(case_id, val.exp_id):
                    return val
            elif isinstance(val, dict) and "exp_id" in val:
                if case_id in val["exp_id"] or re.search(case_id, val["exp_id"]):
                    return ExpUnifiedIR(**val)

        return None

    def _execute_tool(
        self,
        tool_name: str,
        injected: InjectedContext
    ) -> List[ExpUnifiedIR]:
        """Execute a tool call"""

        if tool_name == "solve_with_z3":
            return self._execute_smt(injected)
        elif tool_name == "whitebox_generate":
            return self._execute_whitebox(injected)
        elif tool_name == "random_fuzzing":
            return self._execute_random(injected)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _execute_smt(self, injected: InjectedContext) -> List[ExpUnifiedIR]:
        """Execute the SMT tool"""
        request = ToolCallRequest(
            action_id="smt_solve",
            action_type=ActionType.GENERATE,
            tool_name="smt",
            parameters={
                "mode": "trace_fix",
                "st_code": injected.st_code,
                "plan_context": {
                    "goal": injected.goal,
                    "target_details": injected.target_details,
                    "snapshot": injected.snapshot
                }
            }
        )

        response = self.smt_tool.execute(request)

        # Extract cases
        if response.status == "success" and response.data:
            if "exp_ir" in response.data:
                raw_result = [response.data["exp_ir"]]
            elif "generated_cases" in response.data:
                raw_result = response.data["generated_cases"]
            else:
                raw_result = response.data

            return self._convert_to_exp_ir(raw_result)

        return []

    def _execute_whitebox(self, injected: InjectedContext) -> List[ExpUnifiedIR]:
        """Execute the white-box generation tool"""
        # Internal LLM generation
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        from agents.prompts import GeneratorPrompts

        llm = ChatOpenAI(temperature=0.3)

        prompt = GeneratorPrompts.WHITE_BOX_GENERATION_PROMPT.format(
            goal=injected.goal,
            plc_code=injected.st_code,
            input_schema=self._load_schema()
        )

        response = llm.invoke([HumanMessage(content=prompt)])

        # Parse response
        cases = self._parse_llm_cases(response.content)
        return self._convert_to_exp_ir(cases)

    def _execute_random(self, injected: InjectedContext) -> List[ExpUnifiedIR]:
        """Execute the random fuzzing tool"""
        from pathlib import Path as P

        task_name = P(self.st_path).parent.parent.name

        request = ToolCallRequest(
            action_id="random_fuzz",
            action_type=ActionType.GENERATE,
            tool_name="random",
            parameters={
                "task_name": task_name,
                "max_runtime_sec": 30,
                "batch_size": 10,
                "max_iterations": 1000
            }
        )

        response = self.random_tool.execute(request)

        if response.status == "success" and response.data:
            cases = response.data.get("generated_cases", [])
            return self._convert_to_exp_ir(cases)

        return []

    def _convert_to_exp_ir(self, raw_result: Any) -> List[ExpUnifiedIR]:
        """Convert tool output into a list of ExpUnifiedIR"""
        cases = []

        if not raw_result:
            return cases

        if isinstance(raw_result, dict):
            raw_result = [raw_result]

        if isinstance(raw_result, list):
            for item in raw_result:
                if isinstance(item, ExpUnifiedIR):
                    cases.append(item)
                elif isinstance(item, dict):
                    if "error" in item:
                        continue

                    if "sparse_timeline" in item:
                        item.setdefault("exp_id", item.get("exp_id", f"route_{uuid.uuid4().hex[:6]}"))
                        item.setdefault("target_st_path", self.st_path)
                        item.setdefault("schema_path", str(self.schema_path))
                        item.setdefault("tester_type", "Router")
                        item.setdefault("total_cycles", len(item.get("sparse_timeline", {})))
                        try:
                            cases.append(ExpUnifiedIR(**item))
                        except Exception as e:
                            print(f"[Router] Failed to convert dict: {e}")

        return cases

    def _parse_llm_cases(self, content: str) -> List[Dict]:
        """Parse the LLM response"""
        try:
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]

            data = json.loads(content.strip())

            if isinstance(data, dict):
                if "sparse_timeline" in data:
                    data = [data]
                elif "test_cases" in data:
                    data = data["test_cases"]
                else:
                    data = [{"sparse_timeline": {0: data}}]

            return data if isinstance(data, list) else [data]
        except Exception as e:
            return [{"error": f"Failed to parse: {e}"}]

    def _load_schema(self) -> Dict:
        """Load the schema"""
        try:
            if self.schema_path.exists():
                with open(self.schema_path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def register_case(self, case: ExpUnifiedIR) -> None:
        """Register a generated case for later ID reference"""
        self._case_registry[case.exp_id] = case

    def list_cases(self) -> List[str]:
        """List registered case IDs"""
        return list(self._case_registry.keys())


__all__ = ["LLMRouter", "RouterRequest", "InjectedContext"]
