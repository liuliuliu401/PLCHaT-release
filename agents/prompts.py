"""
Prompt Templates for Generator Agent

Migrated from: FuzzGen/prompts/generator_prompts.py
Simplified for basic Generator with 3 core tools.
"""

import json
import inspect
from typing import List, Dict, Any


class GeneratorPrompts:
    """Prompt templates for Generator Agent."""

    # ========================================================================
    # System Directive
    # ========================================================================

    CAMPAIGN_DIRECTIVE = """You are a PLC Test Generation Agent. Your goal is to generate test cases that achieve specific goals using available tools.

[CRITICAL RULES]
1. Tool Selection: Choose the most appropriate tool based on the goal and task characteristics
2. Argument Precision: Use exact parameter names and valid values
3. Output Format: Return valid JSON or structured data only
4. Termination: Stop when test cases are successfully generated

[AVAILABLE TOOLS]
- solve_with_z3: For arithmetic/logic constraints and precise boundary conditions
- whitebox_generate: For general structural understanding and state exploration
- random_fuzzing: For rapid coverage exploration and breaking through plateaus

Execute efficiently and generate diverse, valid test cases."""

    # ========================================================================
    # Initial Prompt Template
    # ========================================================================

    INITIAL_PROMPT_TEMPLATE = """You are a PLC Test Generation Agent.

[GOAL]
{goal}

[STRATEGY]
Recommended Strategy: {strategy}

[TARGET CODE]
ST Path: {st_path}

[INPUT SCHEMA]
{input_schema}

[FEEDBACK CONTEXT]
{context}

[AVAILABLE TOOLS]
{tool_definitions}

[RULES]
1. Select the most appropriate tool for the goal
2. Use feedback information to guide test generation (focus on uncovered areas)
3. Provide accurate parameters
4. Generate diverse test cases
5. Validate outputs before returning

Generate test cases now."""

    # ========================================================================
    # White Box Generation Prompt
    # ========================================================================

    WHITE_BOX_GENERATION_PROMPT = """You are an AGGRESSIVE PLC Fuzzer.
Your task is to generate diverse and edge-case inputs to thoroughly test the PLC code and achieve the specific goal.

Target Goal: {goal}

PLC Code Snippet:
{plc_code}

[CRITICAL] Allowed Input Schema (Use these keys ONLY):
{input_schema}

---
GENERATION RULES:
1. Strict Variable Alignment: ONLY use the keys defined in the Schema.
2. Multi-Cycle Timeline: Output a `sparse_timeline` dict mapping cycle numbers (0, 1, 2...) to input dicts. If the goal requires sequential steps (like filling a stack), you MUST generate multiple cycles.
3. Boundary Values: Try edge cases based on the logic.
4. NO VAR_IN_OUT: Only use exact VAR_INPUT variable names.
5. CRITICAL STRING FORMATTING: For any variable defined as (STRING) in the schema, you MUST wrap its value in explicit single quotes inside the JSON string (e.g., "'start'").
6. [CRITICAL] IEC TYPE LIMITS & FLOAT FORMATTING:
   - BOOL: 0 to 1
   - SINT: -128 to 127 | INT: -32768 to 32767 | DINT: -2147483648 to 2147483647
   - USINT: 0 to 255 | UINT: 0 to 65535 | UDINT: 0 to 4294967296
   - REAL/LREAL: Output STRICTLY standard JSON numbers (e.g., 3.4e38, -1.5). NEVER use 'NaN', 'Infinity', 'INF', or prefixes like 'REAL#'.

Example Output:
{{"sparse_timeline": {{"0": {{"push": true, "item": 101, "pop": false, "reset": false}}}}}}

Output ONLY valid JSON. Do not include markdown blocks."""

    # ========================================================================
    # Helper Methods
    # ========================================================================

    @staticmethod
    def _refine_schema(schema_dict: Any) -> str:
        """Refines the raw JSON schema into a concise list for LLM alignment."""
        if not isinstance(schema_dict, dict) or "columns" not in schema_dict:
            return "N/A (Use raw variables from PLC code)"

        cols = schema_dict.get("columns", [])
        meta = schema_dict.get("metadata", {})
        lines = []
        for c in cols:
            m = meta.get(c, {})
            line = f"- {c} ({m.get('iec_type', 'UNKNOWN')})"
            if 'st_binding' in m:
                line += f" [Directly maps to PLC variable: {m['st_binding']}]"
            lines.append(line)
        return "\n".join(lines)

    @classmethod
    def format_initial_prompt(
        cls,
        st_path: str,
        goal: str,
        strategy: str,
        context: Dict[str, Any],
        tool_definitions: str,
        input_schema: Any = None
    ) -> str:
        """Format the initial prompt for the agent.
        
        Context can contain feedback information:
        - current_coverage: Current coverage percentage (0.0-1.0)
        - uncovered_lines: List of uncovered line numbers
        - uncovered_branches: List of uncovered branch identifiers
        - iteration: Current iteration number
        """
        # Format context with focus on feedback information
        context_str = cls._format_context(context)

        return cls.INITIAL_PROMPT_TEMPLATE.format(
            st_path=st_path,
            goal=goal,
            strategy=strategy,
            input_schema=cls._refine_schema(input_schema),
            context=context_str,
            tool_definitions=tool_definitions
        )

    @staticmethod
    def _format_context(context: Dict[str, Any]) -> str:
        """Format context for LLM, emphasizing feedback information.
        
        Highlights coverage data and uncovered targets to guide generation.
        """
        if not context:
            return "{}"
        
        lines = ["{"]
        
        # Coverage information
        if "current_coverage" in context:
            cov = context["current_coverage"]
            cov_pct = cov * 100 if isinstance(cov, (int, float)) and cov <= 1 else cov
            lines.append(f'  "current_coverage": {cov_pct:.1f}%')
        
        # Uncovered targets
        if "uncovered_lines" in context and context["uncovered_lines"]:
            lines.append(f'  "uncovered_lines": {context["uncovered_lines"][:10]}...')  # Show first 10
        
        if "uncovered_branches" in context and context["uncovered_branches"]:
            lines.append(f'  "uncovered_branches": {context["uncovered_branches"][:5]}...')  # Show first 5
        
        # Violations found
        if "violations" in context and context["violations"]:
            lines.append(f'  "violations_found": {len(context["violations"])}')
        
        # Iteration
        if "iteration" in context:
            lines.append(f'  "iteration": {context["iteration"]}')
        
        # ── NEW: Causal feedback (RQ3 redesigned) ──
        if "causal_feedback" in context:
            cf = str(context["causal_feedback"])
            lines.append(f'  "causal_feedback": |')
            for cf_line in cf.split("\n"):
                lines.append(f'    {cf_line}')
        
        # ── Legacy trace feedback (deprecated, kept for old runs) ──
        if "keyframe_summary" in context:
            ks = str(context["keyframe_summary"])
            ks_lines = ks.split("\n")[:8]
            ks_truncated = "\n".join(ks_lines)
            if len(ks_lines) >= 8:
                ks_truncated += "\n  ... (truncated)"
            lines.append(f'  "trace_keyframes": |')
            for kl in ks_truncated.split("\n"):
                lines.append(f'    {kl}')
        elif "raw_trace" in context:
            rt = str(context["raw_trace"])[:200]
            lines.append(f'  "raw_execution_trace": {repr(rt)}...')
        
        # ── First round marker ──
        if "first_round" in context:
            lines.append(f'  "note": "First round, no prior feedback available"')
        
        # Other context (truncated)
        other_keys = [k for k in context.keys() if k not in 
                     ["current_coverage", "uncovered_lines", "uncovered_branches", 
                      "violations", "iteration", "schema_path",
                      "keyframe_summary", "raw_trace", "trace_summary",
                      "causal_feedback", "first_round"]]
        if other_keys:
            lines.append(f'  # Additional context: {len(other_keys)} items')
        
        lines.append("}")
        return "\n".join(lines)


__all__ = ["GeneratorPrompts"]
