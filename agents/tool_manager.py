"""
Generator Tool Manager - Internal tool registration and management.

Decouples tool registration logic from Generator initialization.
Provides a clean interface for managing the Generator's tool ecosystem.

Usage:
    from agents.tool_manager import GeneratorToolManager

    tool_manager = GeneratorToolManager(
        benchmark_dir="path/to/benchmark",
        custom_tools={"smt_tool": my_smt_tool}
    )

    # Get tool registry
    registry = tool_manager.get_registry()

    # Get LangChain tools
    langchain_tools = tool_manager.get_langchain_tools()
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
from langchain_core.tools import tool as lc_tool
from langchain_core.messages import HumanMessage

# Project root resolution
# agents/tool_manager.py → agents → PROJECT_ROOT (2 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

# PLCHaT imports
from tools.fuzzers.random import RandomFuzzerTool
from tools.solvers import SMTTool
from tools.fuzzers.dse import DSETool
from tools.fuzzers.afl.mutation_tool import MutationFuzzerTool
from harness.registry.tool_registry import ToolRegistry, registry
from core.protocols.action_protocol import ToolCallRequest, ActionType
from core.data_types.exp_types import ExpUnifiedIR


class GeneratorToolManager:
    """
    Manages tool registration and lifecycle for Generator Agent.

    Responsibilities:
    - Initialize harness tools (SMT, Random, DSE)
    - Create and register LangChain tools
    - Provide tool registry for LLM binding
    - Handle custom tool injection

    Design:
    - Harness tools (SMT, Random, DSE) are managed internally
    - LangChain tools are created and registered
    - whitebox_generate requires LLM reference, set via set_llm_reference()
    """

    def __init__(
        self,
        benchmark_dir: str,
        st_path: str,
        st_code: str,
        custom_tools: Optional[Dict[str, Any]] = None,
        tool_registry: Optional[ToolRegistry] = None
    ):
        """
        Initialize the tool manager.

        Args:
            benchmark_dir: Path to benchmark directory
            st_path: Path to ST source file
            st_code: ST source code (already validated)
            custom_tools: Optional dict of custom tool instances
            tool_registry: Optional custom ToolRegistry instance
        """
        self.benchmark_dir = benchmark_dir
        self.st_path = st_path
        self.st_code = st_code

        # Use provided registry or global default
        self.registry = tool_registry or registry

        # LLM reference (set later by Generator)
        self._llm = None
        self._schema_loader = None

        # Initialize harness tools
        self._init_harness_tools(custom_tools or {})

        # Register internal tools (except whitebox which needs LLM)
        self._register_internal_tools()

        # Inject custom tools
        if custom_tools:
            self._inject_custom_tools(custom_tools)

    def set_llm_reference(self, llm, schema_loader):
        """
        Set LLM reference for tools that need it (whitebox_generate).

        Args:
            llm: LangChain ChatOpenAI instance
            schema_loader: Callable to load input schema
        """
        self._llm = llm
        self._schema_loader = schema_loader
        # Re-register to update whitebox tool
        self._register_whitebox_tool()

    def _init_harness_tools(self, custom_tools: Dict[str, Any]):
        """
        Initialize harness tools (SMT, Random, DSE).

        Uses custom tools if provided, otherwise creates new instances.
        Note: RandomFuzzerTool expects benchmark_root to be the parent
        directory containing task subdirectories.
        """
        # Extract task_name and correct benchmark_root for Random Fuzzer
        # ST path: .../benchmark_raw/211_StackMin/plc_st_files/211_StackMin.st
        # benchmark_root should be: .../benchmark_raw
        # task_name should be: 211_StackMin

        st_path = Path(self.st_path)
        task_name = st_path.parent.parent.name  # 211_StackMin
        benchmark_root = str(st_path.parent.parent.parent)  # benchmark_raw

        self.smt_tool = custom_tools.get("smt_tool", SMTTool(self.benchmark_dir))
        self.random_tool = custom_tools.get(
            "random_tool",
            RandomFuzzerTool(benchmark_root)
        )
        self.dse_tool = custom_tools.get("dse_tool", DSETool(self.benchmark_dir))
        # AFL++ coverage-guided mutation fuzzer (τmut). benchmark_root must be the
        # parent dir containing <task_name>/plc_st_files/<task_name>.st (same as Random).
        self.afl_tool = custom_tools.get("afl_tool", MutationFuzzerTool(benchmark_root))
        # task_name / benchmark_root resolved once for auto-injection into DSE/AFL.
        self._task_name = task_name
        self._benchmark_root = benchmark_root
        # Seed pools for AFL seed-injection, set per-iteration by the runner via
        # set_seed_pools(). Maps strategy name -> list of cases (objects/dicts with
        # .sparse_timeline). The LLM picks a strategy; we inject the actual seeds.
        self._seed_pools: Dict[str, List[Any]] = {}

    def _register_internal_tools(self):
        """Register internal LangChain tools with the registry."""
        # Get already registered tool names
        tool_names = [spec.name for spec in self.registry.list_tools()]

        # Create and register tools that don't need LLM
        internal_tools = [
            self._create_solve_with_z3_tool(),
            self._create_random_fuzzing_tool(),
            self._create_run_full_dse_tool(),
            self._create_run_afl_mutation_tool()
        ]

        for tool_impl in internal_tools:
            if tool_impl.name not in tool_names:
                self.registry.register(
                    name=tool_impl.name,
                    tool=tool_impl,
                    description=tool_impl.description,
                    tool_type="langchain"
                )

    def _register_whitebox_tool(self):
        """Register whitebox_generate tool (requires LLM reference)."""
        if self._llm is None:
            return

        tool_names = [spec.name for spec in self.registry.list_tools()]
        whitebox_tool = self._create_whitebox_generate_tool()

        if whitebox_tool.name not in tool_names:
            self.registry.register(
                name=whitebox_tool.name,
                tool=whitebox_tool,
                description=whitebox_tool.description,
                tool_type="langchain"
            )

    def _inject_custom_tools(self, custom_tools: Dict[str, Any]):
        """
        Inject custom tools into the registry.

        Skips harness tools (smt_tool, random_tool, dse_tool)
        as they are already initialized.
        """
        harness_tool_keys = {"smt_tool", "random_tool", "dse_tool"}

        for name, tool in custom_tools.items():
            if name in harness_tool_keys:
                continue
            if callable(tool):
                self.registry.register(tool, name=name, tool_type="auto")

    # ========================================================================
    # Tool Creation Methods
    # ========================================================================

    def _create_solve_with_z3_tool(self):
        """Create Z3 symbolic execution tool."""

        @lc_tool
        def solve_with_z3(
            goal: str,
            target_details: str = ""
        ) -> List[Dict[str, Any]]:
            """
            Solve a LOCAL/targeted constraint with the Z3 SMT solver (partial solving:
            you describe one specific hard branch/condition and it returns an input
            satisfying it).

            Use for:
            - A specific arithmetic/logic branch random keeps missing
            - Precise boundary conditions, complex IF-conditions

            ⏱ COST: cheap-moderate (one solver call). ⚠ PITFALL: NARROW — only targets the
            condition you name; it does not explore the whole program. For a single stubborn
            branch, not for broad coverage.

            Args:
                goal: The goal to achieve
                target_details: Specific target details (branch, condition)
            """
            request = ToolCallRequest(
                action_id="z3_solve",
                action_type=ActionType.GENERATE,
                tool_name="smt",
                parameters={
                    "mode": "trace_fix",
                    "st_code": self.st_code,
                    "plan_context": {
                        "goal": goal,
                        "target_details": target_details
                    }
                }
            )

            try:
                response = self.smt_tool.execute(request)

                if response.status == "success" and response.data:
                    if "exp_ir" in response.data:
                        return [response.data["exp_ir"]]
                    elif "generated_cases" in response.data:
                        return response.data["generated_cases"]
                    return response.data
                else:
                    return [{"error": response.error_message or "SMT solving failed"}]

            except Exception as e:
                return [{"error": f"SMTTool execution failed: {e}"}]

        return solve_with_z3

    def _create_whitebox_generate_tool(self):
        """Create LLM-based white-box generation tool."""

        @lc_tool
        def whitebox_generate(
            goal: str,
            cycles: int = 10
        ) -> List[Dict[str, Any]]:
            """
            Generate test cases by white-box LLM analysis: reads the code structure and
            crafts targeted multi-cycle inputs aimed at a specific behavior/branch.

            ⏱ COST: moderate (one extra LLM call). ⚠ PITFALL: relies on the model reasoning
            correctly about the code; good for targeted logic/sequence cases, weaker at
            blind broad exploration. A good source of high-quality SEEDS for run_afl_mutation.

            Args:
                goal: The goal to achieve
                cycles: Number of execution cycles (default 10)
            """
            from agents.prompts import GeneratorPrompts
            import json

            # Load schema
            if self._schema_loader:
                schema = self._schema_loader()
            else:
                schema = {}

            # Format prompt
            prompt = GeneratorPrompts.WHITE_BOX_GENERATION_PROMPT.format(
                goal=goal,
                plc_code=self.st_code,
                input_schema=GeneratorPrompts._refine_schema(schema)
            )

            # Call LLM
            try:
                if self._llm is None:
                    return [{"error": "LLM not initialized"}]

                response = self._llm.invoke([HumanMessage(content=prompt)])

                # Parse response
                content = response.content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]

                data = json.loads(content.strip())

                # Normalize to list
                if isinstance(data, dict):
                    if "sparse_timeline" in data:
                        data = [data]
                    elif "test_cases" in data:
                        data = data["test_cases"]
                    else:
                        data = [{"sparse_timeline": {0: data}}]

                return data if isinstance(data, list) else [data]

            except Exception as e:
                return [{"error": f"LLM generation failed: {e}"}]

        return whitebox_generate

    def _create_random_fuzzing_tool(self):
        """Create coverage-guided random fuzzing tool."""

        @lc_tool
        def random_fuzzing(
            goal: str,
            budget_sec: int = 10,
            batch_size: int = 5
        ) -> Dict[str, Any]:
            """
            High-speed random fuzzing with coverage guidance.

            Use for:
            - Rapid, cheap coverage exploration (good default first move)
            - Quickly populating high-quality SEEDS for run_afl_mutation

            ⏱ COST: cheap and fast. ⚠ PITFALL: shallow — plateaus quickly and rarely cracks
            deep/precise branches on its own. When it stalls, switch to solve_with_z3
            (one branch), run_full_dse (whole-program paths), or run_afl_mutation (mutate seeds).

            Args:
                goal: The goal to achieve
                budget_sec: Time budget in seconds (default 10)
                batch_size: Number of cases per batch (default 5)
            """
            # Extract task_name from ST path
            st_path = Path(self.st_path)
            task_name = st_path.parent.parent.name  # e.g., 211_StackMin

            request = ToolCallRequest(
                action_id="random_fuzz",
                action_type=ActionType.GENERATE,
                tool_name="random",
                parameters={
                    "task_name": task_name,
                    "st_code": self.st_code,
                    "max_runtime_sec": budget_sec,
                    "batch_size": batch_size,
                    "max_iterations": 1000,
                    "plateau_limit": 3,
                    "max_depth": 200,
                    "max_cycles": 50,
                }
            )

            try:
                response = self.random_tool.execute(request)

                result = {
                    "status": response.status,
                    "goal": goal
                }

                if response.status == "success" and response.data:
                    data = response.data
                    result["total_generated"] = data.get("total_generated", 0)
                    result["statistics"] = data.get("statistics", {})
                    result["generated_cases"] = data.get("generated_cases", [])
                else:
                    result["error"] = response.error_message or "Random fuzzing failed"

                return result

            except Exception as e:
                return {
                    "status": "error",
                    "error": f"RandomFuzzerTool execution failed: {e}",
                    "goal": goal
                }

        return random_fuzzing

    def _create_run_full_dse_tool(self):
        """Create whole-program Dynamic Symbolic Execution (DSE) tool.

        Difference from solve_with_z3: solve_with_z3 (SMT trace_fix) writes a LOCAL
        target condition as constraints and solves it; run_full_dse throws the WHOLE
        program into the symbolic-execution engine to systematically enumerate feasible
        paths. State-explosion is bounded by timeout_sec + max_depth (hard guards)."""

        @lc_tool
        def run_full_dse(goal: str, target_details: str = "", timeout_sec: int = 60) -> List[Dict[str, Any]]:
            """
            Whole-program symbolic execution to systematically discover inputs that
            reach deep/rare branches the random/whitebox tools keep missing.

            Use for:
            - Hard, deeply-nested branch conditions
            - Exact integer/boundary path constraints across the whole POU
            - When coverage has plateaued and you suspect unreachable-by-random paths

            ⏱ COST: SLOW (up to timeout_sec, default 60s) and consumes a big slice of your
            campaign budget → fewer later iterations. Use deliberately, usually once.
            ⚠ PITFALL: may hit STATE EXPLOSION on loop-heavy code; it is hard-bounded by
            timeout_sec and an internal depth cap, returning whatever it found so far (may
            be partial or empty on pathological loops).

            Args:
                goal: The coverage/branch goal to achieve
                target_details: Specific target branch/condition to steer exploration
                timeout_sec: Hard wall-clock budget (state-explosion guard, default 60)
            """
            request = ToolCallRequest(
                action_id="run_full_dse",
                action_type=ActionType.GENERATE,
                tool_name="dse",
                parameters={
                    "task_name": self._task_name,
                    "st_code_path": str(self.st_path),
                    "timeout": int(max(15, min(timeout_sec, 90))),  # clamp 15..90s
                    "max_depth": 30,        # bounded exploration cycles (anti-explosion)
                    "max_cycles": 8,        # align with loop's per-case cycle count
                    "with_coverage": False, # runner measures coverage; skip internal eval
                    "plateau_limit": 8,
                },
            )
            try:
                response = self.dse_tool.execute(request)
                if response.status == "success" and response.data:
                    return response.data.get("generated_cases", []) or [
                        {"error": "DSE produced no cases"}]
                return [{"error": response.error_message or "DSE failed"}]
            except Exception as e:
                return [{"error": f"DSETool execution failed: {e}"}]

        return run_full_dse

    def _create_run_afl_mutation_tool(self):
        """Create AFL++ coverage-guided mutation fuzzing tool (τmut).

        AFL needs runtime to evolve; with a short budget its value comes mainly from
        mutating GOOD seeds. The LLM should call this to break a coverage plateau after
        it (or random) has already produced promising inputs."""

        @lc_tool
        def run_afl_mutation(goal: str, budget_sec: int = 90,
                             seed_strategy: str = "triggered") -> List[Dict[str, Any]]:
            """
            AFL++ coverage-guided mutation fuzzing. Best for BREAKING THROUGH a coverage
            plateau by mutating EXISTING high-quality inputs into nearby corner cases.

            ⏱ COST: EXPENSIVE. Recompiles with instrumentation + fuzzes; allow ~60-120s to
            pay off (short budgets explore too shallowly). Calling this consumes a large
            slice of your total campaign budget, so it leaves you FEWER later iterations —
            use it deliberately, typically once, after a plateau.
            ⚠ PITFALL: AFL is near-useless cold. Its value comes from GOOD SEEDS — always
            set seed_strategy to inject your best historical inputs as the mutation corpus:
              - "triggered": cases that already tripped an assertion (highest signal)
              - "distilled": the minimized/distilled high-value subset
              - "recent":    the most recent batch of generated cases
              - "all":       a sample across all generated cases so far
              - "none":      start cold (NOT recommended)

            Args:
                goal: The coverage goal to achieve
                budget_sec: Mutation time budget in seconds (default 90; up to 120)
                seed_strategy: Which historical seeds to inject (default "triggered")
            """
            seeds = self._resolve_afl_seeds(seed_strategy)
            request = ToolCallRequest(
                action_id="run_afl_mutation",
                action_type=ActionType.GENERATE,
                tool_name="afl",
                parameters={
                    "task_name": self._task_name,
                    "max_runtime_sec": int(max(20, min(budget_sec, 120))),
                    "max_cycles": 8,
                    "max_eval_cases": 50,
                    "stop_on_crash": False,
                    "initial_seeds": seeds,
                },
            )
            try:
                response = self.afl_tool.execute(request)
                if response.status == "success" and response.data:
                    raw = response.data.get("generated_cases", []) or []
                    # AFL IR carries extra fields (meta_discovery_time_ms, is_crash) that
                    # ExpUnifiedIR(**dict) rejects -> conversion drops every case. Keep only
                    # the fields ExpUnifiedIR accepts so the converter succeeds.
                    keep = {"exp_id", "target_st_path", "schema_path", "tester_type",
                            "scan_cycle_ms", "total_cycles", "sparse_timeline", "metadata"}
                    cases = [{k: v for k, v in c.items() if k in keep}
                             for c in raw if isinstance(c, dict) and "sparse_timeline" in c]
                    return cases or [{"error": "AFL produced no cases"}]
                return [{"error": response.error_message or "AFL failed"}]
            except Exception as e:
                return [{"error": f"MutationFuzzerTool execution failed: {e}"}]

        return run_afl_mutation

    def _resolve_afl_seeds(self, strategy: str, max_seeds: int = 12) -> List[Dict[str, Any]]:
        """Resolve an LLM-chosen seed_strategy into concrete AFL seeds.

        Reads from self._seed_pools (set per-iteration by the runner) and normalises each
        case (ExpUnifiedIR object or dict) to {'sparse_timeline': {...}, 'total_cycles': n}.
        """
        if not strategy or strategy == "none":
            return []
        pool = self._seed_pools.get(strategy) or []
        seeds = []
        for c in pool[:max_seeds]:
            tl = getattr(c, "sparse_timeline", None)
            if tl is None and isinstance(c, dict):
                tl = c.get("sparse_timeline")
            if not tl:
                continue
            tl = {str(k): v for k, v in tl.items()}
            seeds.append({"sparse_timeline": tl, "total_cycles": len(tl)})
        return seeds

    def set_seed_pools(self, pools: Dict[str, List[Any]]):
        """Set the per-iteration seed pools the LLM can inject into AFL.

        pools maps strategy name (triggered/distilled/recent/all) -> list of cases
        (ExpUnifiedIR objects or dicts with sparse_timeline). Called by the runner before
        each generation round."""
        self._seed_pools = pools or {}

    # ========================================================================
    # Public API
    # ========================================================================

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self.registry

    def get_langchain_tools(self) -> List:
        """Get all tools as LangChain format."""
        return self.registry.to_langchain_tools()

    def get_tool(self, name: str):
        """Get a specific tool by name."""
        return self.registry.get(name)

    def inject_tool(self, tool_func, name: str, description: str = "") -> str:
        """
        Inject a new tool at runtime.

        Args:
            tool_func: Callable function
            name: Tool name
            description: Tool description

        Returns:
            The registered tool name
        """
        self.registry.register(tool_func, name=name, description=description)
        return name

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools."""
        return [spec.name for spec in self.registry.list_tools()]


__all__ = ["GeneratorToolManager"]
