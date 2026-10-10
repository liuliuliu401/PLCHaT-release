"""
LLM Semantic Slicer - ST to Z3 Constraint Translation

Responsible for Semantic Slicing: Translating ST logic into Z3 constraints.
Does NOT calculate values; only defines relationships.
"""

import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import from config.py explicitly, avoiding config/ package
import importlib.util
spec = importlib.util.spec_from_file_location("config_module", PROJECT_ROOT / "config.py")
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)

generator_model = config_module.generator_model
generator_api_key = config_module.generator_api_key
generator_base_url = config_module.generator_base_url


class LLMSemanticSlicer:
    """
    [Divide Module]
    Responsible for Semantic Slicing: Translating ST logic into Z3 constraints.

    Uses LLM to extract and translate Structured Text (ST) logic into
    Python Z3 solver scripts. Does NOT solve constraints, only defines them.
    """

    def __init__(self):
        """Initialize the LLM Semantic Slicer."""
        self.llm = ChatOpenAI(
            temperature=0.0,  # Zero temp for deterministic logic extraction
            model=generator_model,
            api_key=generator_api_key,
            base_url=generator_base_url,
        )

    def generate_z3_script(self, st_code: str, plan_context: Dict[str, Any]) -> Optional[str]:
        """
        Generates a Python Z3 script defining constraints based on dynamic plan context.

        Args:
            st_code: Structured Text source code
            plan_context: Dictionary containing:
                - goal: Description of verification goal
                - strategy: Solving strategy
                - target_type: Type of target ("code_snippet" or "functional")
                - target_details: Specific details about the target

        Returns:
            Python code string with Z3 constraints, or None on failure.
        """
        goal_desc = plan_context.get("goal", "Analyze logic")
        strategy = plan_context.get("strategy", "General")
        target_type = plan_context.get("target_type", "functional")
        target_details = plan_context.get("target_details", "")

        # Base System Prompt: The fundamental rules of Z3 generation
        base_system_prompt = """You are a Formal Verification Expert.
Your task is to translate Structured Text (ST) logic into a Python Z3 solver script to find valid inputs.

CRITICAL CONCEPT: PRE-STATE vs POST-STATE & SEPARATION OF INPUTS
- You must separate variables into `z3_states` (Internal State at START of cycle) and `z3_inputs` (Current cycle inputs to be solved).
- DO NOT put inputs in `z3_states`, and DO NOT put internal states in `z3_inputs`.
- You must find the constraints (Guard Conditions) that *enable* a transition or execution path.
- DO NOT assert the outcome! If the goal is to make `cappingStep := TRUE`, you must assert the IF-condition that guards it.

GENERAL RULES:
1. DICTIONARY FORMAT: `z3_states` and `z3_inputs` MUST be Python dictionaries mapping variable names directly to Z3 objects. DO NOT use lists!
   Correct: `z3_inputs = {{'enter_flag': Bool('enter_flag')}}`
   Wrong: `z3_inputs = [{{'name': 'enter_flag'}}]`
2. LOOP HANDLING: If the target is inside a loop, DO NOT use `s.add()` inside the python loop (which forces ALL iterations to be true simultaneously and causes UNSAT). Instead, collect the conditions in a list and use `s.add(Or(conditions))` so that AT LEAST ONE iteration reaches the target.
3. NO LIST COMPREHENSIONS: You must use standard `for` loops instead of list comprehensions when defining constraints.
4. Output ONLY the Python code block. No explanations.
5. Initialize `s = Solver()`. Do NOT call `s.check()`.
6. FLAT DATA STRUCTURES: For PLC Arrays or Structs, DO NOT create nested lists or dictionaries in Python. Flatten them into primitive Z3 variables using underscores. Example: For garage[i].Occupied, generate z3_states['garage_1_Occupied'] = Bool('garage_1_Occupied') using standard for loops.
"""

        # Dynamic Strategy Injection
        if target_type == "code_snippet":
            dynamic_instruction = f"""
            Task Type: REACH TARGET CODE
            You are provided with a specific 'Target Snippet' and its surrounding context.
            Action: Find the IF/ELSIF guard conditions wrapping this snippet. Translate ONLY those guard conditions into Z3 constraints.
            """
        elif target_type == "functional":
            dynamic_instruction = f"""
            Task Type: ACHIEVE FUNCTIONAL STATE
            You are provided with a 'Functional Description' of the target.
            Action: Read the full ST code, find the logic block that executes this function, and extract its preconditions (Guards) into Z3 constraints.
            """
        else:
            dynamic_instruction = "Task Type: GENERAL SOLVING. Extract constraints to satisfy the given goal."

        system_prompt = base_system_prompt + dynamic_instruction

        user_prompt = f"""
[Verification Goal]
{goal_desc} (Strategy: {strategy})

[Target Information ({target_type})]
{target_details}

[Full Source Code]
{st_code}

[Required Output]
Generate the Python `z3` script.
"""

        try:
            response = self.llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ])
            return self._clean_code_block(response.content)
        except Exception as e:
            print(f"[LLM Slicer Error] {e}")
            return None

    def _clean_code_block(self, text: str) -> str:
        """
        Extract Python code from LLM response.

        Handles both markdown code blocks and plain code output.
        """
        # Try to extract from ```python``` block
        match = re.search(r"```python(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: check if text contains Z3 code without blocks
        if "z3" in text and "Solver()" in text:
            return text.strip()

        return ""


__all__ = ["LLMSemanticSlicer"]
