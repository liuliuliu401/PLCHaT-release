"""
LLM Assertion Designer v3 - Feature Point Specific Version

Improvement points:
1. Use assertion template library - provides feature-specific assertion templates
2. Function point identification - Automatically identify program function points
3. Assertion classification - safety/functional/tracking three types
4. Enhanced output information - include detailed context and variable values when assertion fails
5. Trace mode - Record key state even if assertions pass

Usage:
    from harness.test_analysis.assertion.llm_assertion_designer_v3 import LLMAssertionDesignerV3

    designer = LLMAssertionDesignerV3()
    assertion = designer.design_assertions(st_path, pou_info, intent)
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import importlib.util
import re
import logging

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.generator import POUInfo
from harness.test_analysis.intent.intent_provider import TestIntent
from harness.test_analysis.assertion.assertion_templates import (
    identify_functionality,
    get_safety_templates,
    get_tracking_templates,
    format_templates_for_prompt,
    AssertionTemplate
)

# Load LLM config
spec = importlib.util.spec_from_file_location("config", PROJECT_ROOT / "config.py")
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


@dataclass
class AssertionCode:
    """assertion code (v3 extension)"""
    c_code: str
    description: str
    target_variables: List[str] = field(default_factory=list)
    compilation_errors: List[str] = field(default_factory=list)
    is_valid: bool = False

    # v3 added fields
    functionality: str = ""                    # Identified function points
    assertion_categories: List[str] = field(default_factory=list)  # Assert classification
    tracking_assertions: List[str] = field(default_factory=list)  # Trace assertion
    safety_assertions: List[str] = field(default_factory=list)     # Safety assertion


# ============================================================================
# v3 prompt template
# ============================================================================

ASSERTION_DESIGN_PROMPT_V3 = """
You are an industrial control security expert. Please design runtime assertions for the following ST code.

【Program Information】
Program name: {pou_name}
Program type: {pou_kind}

【Function Point Identification】
Main functionality: {functionality}

【Output variable details】
{output_vars_detail}

【Variable usage context】
{variable_context}

Key Pattern Recognition
{key_patterns}

[Test Intention]
{intent}

【Task】
Generate C code assertions to check critical security points.

【Assertion Classification】
1. **Safety assertion** (safety): check dangerous state, exit(1) on failure
- Used to check conditions that may lead to danger.
- On failure, detailed context information (variable values, location, etc.) must be printed.
Format: fprintf(stderr, "AUDIT FAIL: <detailed description> <variable value>\\n", ...);

2. **Tracking assertion** (tracking): record critical state, do not exit
- Used for tracking program execution and variable state.
- Output key information even if all conditions are normal
- Format: fprintf(stderr, "AUDIT INFO: <status information>\\n", ...);

【Important Constraint】
1. **Must use correct variable access format**
- Assertions will be inserted into the main() function, instance is a struct value (not a pointer)
Use dot notation to access: instance.VARIABLE_NAME.value
- Variable names must use uppercase format (consistent with POU_NAME in harness.c)
// Arrow is used for pointer
// dot is used for value

{harness_examples}

2. Must follow the following syntax rules:
Array access must use index: instance.VARIABLE_NAME.value.table[index]
- Index variable must be declared first: for (int i = 0; i < SIZE; i++)
- fprintf format string must be completed within one line

3. Output information requirements:
-   When a safety assertion fails, it must include: which element, what value, and why it is wrong.
- Tracking assertion must include: the actual value of the key variable
- Use descriptive error messages (business semantics) rather than technical descriptions.

【Reference Template】
{templates}

Only output the C code snippet, do not include any explanation.
"""


ASSERTION_REFINEMENT_PROMPT = """
Please optimize the following assertion code to include more detailed context information.

Original assertion
{original_code}

【Optimization Requirements】
Include the actual value of the variable on failure.
2. Use descriptive business semantics
3. Add tracking output for key states

Optimized code:
"""


class LLMAssertionDesignerV3:
    """LLM Assertion Designer v3 - Feature-specific version"""

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)

        from langchain_openai import ChatOpenAI
        self.llm = ChatOpenAI(
            temperature=0.3,
            model=config_module.generator_model,
            api_key=config_module.generator_api_key,
            base_url=config_module.generator_base_url,
        )

        self.max_retries = 3

    def design_assertions(
        self,
        st_path: Path,
        pou_info: POUInfo,
        intent: TestIntent,
        existing_harness_path: Optional[Path] = None
    ) -> AssertionCode:
        """LLM-generated assertion code (v3: feature-specific, based on existing harness)"""
        self.logger.info(f"[v3] Designing assertions - Test intent: {intent.description}")

        # [New] Step 0: If existing harness is provided, read variable access examples
        harness_examples = self._extract_harness_examples(existing_harness_path, pou_info) if existing_harness_path else ""

        # Step 1: Identify function points
        functionality_list = identify_functionality([v.pou_name for v in pou_info.outputs])
        primary_functionality = functionality_list[0] if functionality_list else "general"
        self.logger.info(f"[v3] Identified functionality: {primary_functionality}")

        # Step 2: Prepare context
        output_vars_detail = self._format_output_vars(pou_info)
        variable_context = self._build_variable_context(pou_info)
        key_patterns = self._identify_key_patterns(pou_info)

        # Step 3: Get relevant templates
        safety_templates = get_safety_templates(primary_functionality)
        tracking_templates = get_tracking_templates(primary_functionality)

        self.logger.info(f"[v3] Safety templates: {len(safety_templates)}, Tracking templates: {len(tracking_templates)}")

        # Step 4: Generate assertion
        c_code = None
        compilation_errors = []

        for attempt in range(self.max_retries):
            self.logger.info(f"[v3] Generation attempt {attempt + 1}/{self.max_retries}")

            # Format template
            all_templates = safety_templates + tracking_templates
            templates_str = format_templates_for_prompt(all_templates)

            # Prepare prompt
            prompt = ASSERTION_DESIGN_PROMPT_V3.format(
                pou_name=pou_info.pou_name_upper,
                pou_kind=pou_info.kind,
                functionality=primary_functionality,
                output_vars_detail=output_vars_detail,
                variable_context=variable_context,
                key_patterns=key_patterns,
                intent=intent.description,
                templates=templates_str,
                harness_examples=harness_examples  # Add harness example
            )

            # If it is a retry, add error feedback
            if attempt > 0 and compilation_errors:
                prompt += f"\n\n[The previously generated code has compilation errors, please fix]\n"
                prompt += "\n".join(compilation_errors[:3])

            # Call LLM
            response = self.llm.invoke(prompt)
            c_code = self._extract_c_code(response.content)

            # Verify compilation
            is_valid, errors = self._verify_compilation(c_code, pou_info)
            compilation_errors = errors

            if is_valid:
                self.logger.info(f"[v3] OK - Assertion code verification passed")
                break
            else:
                self.logger.warning(f"[v3] FAILED - Compilation failed, retrying...")

        # Step 5: Analyze generated assertions
        safety_assertions, tracking_assertions = self._classify_assertions(c_code)

        # Step 6: Extract target variable
        target_vars = self._extract_target_variables(c_code, pou_info)

        return AssertionCode(
            c_code=c_code,
            description=f"Functionality-specific assertion: {primary_functionality}",
            target_variables=target_vars,
            compilation_errors=compilation_errors,
            is_valid=(len(compilation_errors) == 0),
            functionality=primary_functionality,
            assertion_categories=list(set([t.category for t in all_templates])),
            tracking_assertions=tracking_assertions,
            safety_assertions=safety_assertions
        )

    def _format_output_vars(self, pou_info: POUInfo) -> str:
        """Format and output variable details"""
        lines = []
        for var in pou_info.outputs:
            array_info = f"[Array: {var.array_size}]" if var.is_array else ""
            lines.append(f"  - {var.pou_name} ({var.iec_type}){array_info}")
        return "\n".join(lines) if lines else "  (No output variables)"

    def _build_variable_context(self, pou_info: POUInfo) -> str:
        """Build variable usage context"""
        contexts = []

        for var in pou_info.outputs:
            context = f"Variable: {var.pou_name}\n"
            context += f"  Type: {var.iec_type}\n"
            context += f"  Array: {'Yes, size=' + str(var.array_size) if var.is_array else 'No'}\n"
            context += f"  C Access: instance.{var.pou_name}.value"
            if var.is_array:
                context += f".table[index]  (requires for loop iteration)"
            contexts.append(context)

        return "\n\n".join(contexts) if contexts else "No context information"

    def _identify_key_patterns(self, pou_info: POUInfo) -> str:
        """Identify key patterns"""
        patterns = []

        # Detect array variable
        array_vars = [v for v in pou_info.outputs if v.is_array]
        if array_vars:
            patterns.append(f"Array variables: {', '.join([v.pou_name for v in array_vars])} (requires loop iteration)")

        # Check state machine variable
        state_vars = [v for v in pou_info.all_vars if any(k in v.name.lower() for k in ['mode', 'state'])]
        if state_vars:
            patterns.append(f"State machine variables: {', '.join([v.name for v in state_vars])} (check value range)")

        # Detect error indicator
        error_vars = [v for v in pou_info.all_vars if any(k in v.name.lower() for k in ['error', 'retval', 'status'])]
        if error_vars:
            patterns.append(f"Error indicators: {', '.join([v.name for v in error_vars])} (check non-zero values)")

        return "\n".join(patterns) if patterns else "No obvious patterns"

    def _classify_assertions(self, c_code: str) -> Tuple[List[str], List[str]]:
        """Classification assertions: safety and tracking"""
        safety = []
        tracking = []

        lines = c_code.split('\n')
        for i, line in enumerate(lines):
            if 'fprintf(stderr,' in line and 'AUDIT' in line:
                if 'AUDIT FAIL' in line or 'AUDIT ERROR' in line:
                    # Find the code block containing this fprintf
                    safety.append(line.strip())
                elif 'AUDIT INFO' in line:
                    tracking.append(line.strip())

        return safety, tracking

    def _verify_compilation(
        self,
        c_code: str,
        pou_info: POUInfo
    ) -> Tuple[bool, List[str]]:
        """Verify that the assertion code can be compiled"""
        if not c_code or not c_code.strip():
            return False, ["Empty code"]

        errors = []
        errors.extend(self._static_check(c_code, pou_info))
        errors.extend(self._check_basic_syntax(c_code))

        return (len(errors) == 0), errors

    def _check_basic_syntax(self, c_code: str) -> List[str]:
        """Basic syntax check"""
        errors = []

        # Check bracket matching
        if c_code.count('{') != c_code.count('}'):
            errors.append("Mismatched braces")

        return errors

    def _static_check(self, c_code: str, pou_info: POUInfo) -> List[str]:
        """Static syntax checking"""
        errors = []

        # Check undeclared variable references
        if 'ch' in c_code and 'for' not in c_code:
            errors.append("Using variable 'ch' without declaration (needs for (int ch = 0; ...))")

        # [Fix] Check if the correct variable access format is used
        # Assert inserted in main(), instance is a struct value, should use dot instead of arrow
        lines = c_code.split('\n')
        for i, line in enumerate(lines):
            # Skip comments and empty lines
            stripped = line.strip()
            if not stripped or stripped.startswith('//') or stripped.startswith('/*'):
                continue

            # 【Key check】Do not use instance-> (arrow), because in main() instance is a value not a pointer
            if 'instance->' in line:
                errors.append("Must use instance.VAR.value (dot) instead of instance->VAR.value (arrow), because assertion is in main() and instance is a struct value")

            # Check for bare variable references (without instance. prefix)
            for var in pou_info.outputs:
                var_name_lower = var.name.lower()
                var_name_upper = var.pou_name

                if var_name_lower in line.lower():
                    if f"instance.{var_name_upper}" not in line:
                        errors.append(f"Variable {var.name} must be accessed through instance.{var_name_upper}.value (use dot)")

        # Check if array access includes index
        for var in pou_info.outputs:
            if var.is_array:
                pattern = f"instance.{var.pou_name}.value.table[^[]"
                if re.search(pattern, c_code):
                    errors.append(f"Array variable {var.pou_name} access missing index")

        # Check fprintf format string - Improved version: looser check
        for i, line in enumerate(lines):
            if 'fprintf(' in line and 'stderr' in line:
                if 'AUDIT' not in line:
                    context = '\n'.join(lines[max(0,i-1):min(len(lines),i+2)])
                    if 'AUDIT' not in context:
                        errors.append(f"fprintf should use AUDIT prefix (line {i+1})")

        # Check if it contains detailed context information
        if 'fprintf' in c_code:
            if 'AUDIT' not in c_code:
                errors.append("fprintf should use AUDIT prefix (AUDIT FAIL or AUDIT INFO)")

            if 'AUDIT FAIL' in c_code:
                fail_prints = [l for l in c_code.split('\n') if 'AUDIT FAIL' in l and 'fprintf' in l]
                for fp in fail_prints:
                    if not any(spec in fp for spec in ['%d', '%f', '%u', '%x']):
                        errors.append("AUDIT FAIL assertions should include variable value output (use %d, %f, etc.)")

        return errors

    def _extract_c_code(self, response: str) -> str:
        """Extract C code"""
        if "```c" in response:
            start = response.find("```c") + 4
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()
        return response.strip()

    def _extract_target_variables(self, c_code: str, pou_info: POUInfo) -> List[str]:
        """Extract target variable"""
        target_vars = []
        for var in pou_info.outputs:
            if var.pou_name.upper() in c_code.upper():
                target_vars.append(var.name)
        return target_vars

    def _extract_harness_examples(self, harness_path: Path, pou_info: POUInfo) -> str:
        """Extract variable access examples from existing harness.c"""
        if not harness_path or not harness_path.exists():
            return ""

        try:
            harness_code = harness_path.read_text()
            examples = []

            # Extract variable access example - find instance->VAR.value pattern
            for var in pou_info.outputs:
                pou_name = var.pou_name  # UPPERCASE
                # Find the access pattern of this variable
                import re
                patterns = [
                    f"instance->{pou_name}.value",  # Scalar access
                    f"instance->{pou_name}.value.table[",  # Array access
                ]

                for pattern in patterns:
                    if pattern in harness_code:
                        # Extract the code line containing this access
                        lines = harness_code.split('\n')
                        for i, line in enumerate(lines):
                            if pattern in line and '/*' not in line:
                                # Clean up and format example
                                cleaned = line.strip()
                                if cleaned and not cleaned.startswith('//'):
                                    examples.append(f"// Access method for {var.name} (from harness.c):")
                                    examples.append(f"//   {cleaned}")
                                    break
                        if examples:
                            break

            if examples:
                header = "\n[Variable access examples from existing harness.c]\n"
                note = "// Note: These examples are from inside functions (like print_fb_state), where instance is a pointer parameter.\n"
                note += "// Your assertion will be inserted in main() function, where instance is a struct value, please use dot instead of arrow!\n"
                return header + note + "\n".join(examples[:10])  # Limit the number of examples
            return ""

        except Exception as e:
            self.logger.warning(f"Failed to read harness examples: {e}")
            return ""


__all__ = ["LLMAssertionDesignerV3", "AssertionCode"]
