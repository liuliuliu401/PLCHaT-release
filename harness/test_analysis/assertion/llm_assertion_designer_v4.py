"""
# LLM Assertion Designer v4 - Systemic Safety Invariant Version

Core improvement:
Systematic safety invariant design - Identify key constraints from a holistic perspective
2. Assertion priority system - P0(core design) > P1(edge safety)
3. Error code priority monitoring - Prioritize checking the program's predefined error codes
4. Relationship invariant design - If there is no error code, design relationship invariants
5. Phased verification - Security → Reliability → Other tests
6. Complete variable list - Extract all available variables from POUS.h to prevent LLM from fabricating

Design principles:
Prioritize monitoring core design, rather than edge security.
- Prefer using the program's predefined error codes
- If there is no error code, design relation invariant.
Extract safety constraints from a systemic perspective

Usage:
    from harness.test_analysis.assertion.llm_assertion_designer_v4 import LLMAssertionDesignerV4
    
    designer = LLMAssertionDesignerV4(log_file="assertion_generation.log")
    assertion = designer.design_assertions(st_path, pou_info, intent)
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import importlib.util
import re
import logging
from enum import Enum
from datetime import datetime

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.generator import POUInfo, VarDecl
from harness.test_analysis.intent.intent_provider import TestIntent


# Load LLM config
spec = importlib.util.spec_from_file_location("config", PROJECT_ROOT / "config.py")
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class AssertionPriority(Enum):
    """assert priority."""
    P0_CORE = "P0_CORE"  # Core design verification
    P0_SAFETY = "P0_SAFETY"  # Safety invariant
    P1_EDGE = "P1_EDGE"  # Edge security


@dataclass
class SafetyInvariant:
    """Security invariant."""
    name: str
    description: str
    condition: str  # Trigger condition
    invariant: str  # Invariant expression
    priority: AssertionPriority
    failure_message: str


@dataclass
class SystematicSafetyAnalysis:
    """Systematic security analysis result."""
    error_code_vars: List[str]  # Error code variable
    core_business_vars: List[Dict]  # Core business variables
    all_output_vars: List[Dict]  # All output variables
    relationship_invariants: List[SafetyInvariant]  # Relation invariant
    state_constraints: List[SafetyInvariant]  # State constraints
    edge_safety_checks: List[SafetyInvariant]  # Edge security check


@dataclass
class AssertionCodeV4:
    """Assertion code (v4 extension)"""
    c_code: str
    description: str
    target_variables: List[str] = field(default_factory=list)
    compilation_errors: List[str] = field(default_factory=list)
    is_valid: bool = False
    
    # v4 added field
    safety_analysis: SystematicSafetyAnalysis = None
    priority_distribution: Dict[str, int] = field(default_factory=dict)
    verification_stages: List[str] = field(default_factory=list)


# ============================================================================
# v4 prompt template - systematic safety invariant design
# ============================================================================

ASSERTION_DESIGN_PROMPT_V4 = """
You are an industrial control security expert generating C runtime safety assertions
for PLC programs compiled via MatIEC.

## Assertion Design Strategy

**Goal**: Generate assertions that ARE LIKELY TO TRIGGER during testing with random inputs.

**Key Principles**:
1. Check business logic invariants, not just error codes
2. Check relationships between output variables
3. Check state consistency after operations
4. Avoid overly conservative conditions that never trigger
5. Generate MULTIPLE independent anomaly checks (single-cycle AND temporal/cross-cycle),
   so a hidden bug in ANY state transition gets caught — do not stop at error-code checks

## Assertion Design Priority

**P0 - Core Design Verification** (must implement first):
1. **Business invariants**: Check relationships between OUTPUT/STATE variables that reflect
   the program's RESPONSE (e.g. error flag vs status code consistency, counter vs array contents)
2. **State consistency**: Check that state transitions make sense (e.g., can't be in multiple states at once)
3. **Boundary validation**: Check that ALL variables (including INPUT, TEMP) stay within their expected ranges — e.g., VAL_COUNTDOWN-like countdown displays must be bounded [0-9], integer counters should not go negative without an error flag, array indices should not exceed bounds. Pay special attention to countdown/counter variables whose domain is explicitly limited by the problem specification.
4. **Output validation**: Check that output values are within expected ranges

### CRITICAL: never assert over INPUTS alone
Inputs are controlled by the environment/operator and may be ANY combination (e.g. PUSH and POP
both TRUE, or out-of-range item). That is NOT a bug. A bug only exists if the program RESPONDS
incorrectly. Therefore EVERY assertion MUST reference at least one OUTPUT or internal STATE
variable (the program's response). Do NOT generate assertions whose condition uses only input
variables (e.g. `if (PUSH && POP) fail` is INVALID — the program is allowed to receive that;
instead check that the program handled it correctly, e.g. set an error flag or rejected it).

**P1 - Anomaly Detection** (REQUIRED — generate AT LEAST 2-3 of these):
5. **Operation-effect anomalies**: after an operation, the state MUST change as designed.
   Examples: after a successful PUSH the stack pointer/counter MUST increase by 1 (never
   reset or decrease); after a successful POP it MUST decrease by 1; a "set" must take effect.
6. **Monotonicity / temporal anomalies**: a counter that should only grow under operation X
   must NOT suddenly drop; an index must not jump backwards unexpectedly.
7. **Unexpected value combinations**: e.g. a value was written into an array slot but the
   pointer says that slot is empty/out of range.

### Temporal (cross-cycle) invariants — IMPORTANT
`check_assertions()` is called once PER scan cycle within a single test case, so you CAN and
SHOULD compare against the PREVIOUS cycle using `static` local variables to catch anomalies
that only appear over time (e.g. a hidden state-transition override that corrupts a counter):

```c
static int prev_top = -1;            // remembers last cycle's value
int t = (int)inst->TOP.value;
/* After a normal, non-overflow push, top must increase by exactly 1 (never reset). */
if (inst->PUSH.value && !inst->POP.value && !inst->RESET.value && prev_top < 3) {{
    if (t != prev_top + 1) {{
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: top did not advance after push (prev=%d now=%d)\\n", prev_top, t);
        fflush(stderr); prev_top = t; return 8;
    }}
}}
prev_top = t;                        // update for next cycle
```

## Program Information

**Program name**: {pou_name}
**Program type**: {pou_kind}
**Primary functionality**: {functionality}

## Available Output Variables (MANDATORY - COMPLETE LIST)

**CRITICAL**: You can ONLY use the variables listed below in your assertions.
DO NOT invent variable names. If a variable is not in this list, you CANNOT use it.

{all_output_vars_list}

## CRITICAL: Variable Access Rules — READ THIS FIRST

Your assertions will be inserted into main() AFTER POU_body__(&instance).
In main(), `instance` is declared as `POU_NAME instance;` — it is a struct VALUE, NOT a pointer.

**MANDATORY C access patterns** (use these EXACT patterns, or assertions WILL NOT COMPILE):
- Scalar: `inst->VAR_NAME.value` — e.g. `inst->TOP.value`, `inst->ERROR.value`
- Array element: `inst->ARRAY_NAME.value.table[index]` — e.g. `inst->STACK.value.table[i]`
- NEVER use bare ST variable names (push, top, stack) — they don't exist in C
- Loop index variables MUST be declared: `for (int i = 0; i < SIZE; i++)`

## C Code Access Patterns (from compiled POUS.c — shows EXACT variable names)

{pous_code_summary}

{harness_examples}

## Original ST Source Code (understand the program logic to identify invariants)

```pascal
{st_code}
```

**Error code variables** (monitor first):
{error_code_vars}

**Core business variables**:
{core_business_vars}

## Safety Analysis

**Identified constraints**:
{identified_constraints}

**Suggested relationship invariants**:
{suggested_invariants}

## Test Intent

{intent}

## Code Structure

## Code Structure

You MUST output a standalone `check_assertions()` function that takes a pointer parameter:

```c
int check_assertions(POU_NAME* inst) {{
    // P0 checks here
    // P1 checks here
    return 0; // 0 = no assertion failed
}}
```

In this function, `inst` IS a pointer, so use arrow notation: `inst->VAR.value`.

## Code Examples (MUST follow this pattern exactly)

```c
int check_assertions(POU_NAME* inst) {{
    /* P0: Error code monitoring */
    if (inst->ERROR_CODE.value != 0) {{
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: ERROR_CODE=%u\\n",
                (unsigned)inst->ERROR_CODE.value);
        fflush(stderr);
        return 1;
    }}

    /* P0: Relationship invariant */
    if (inst->HILIM.value <= inst->LOLIM.value) {{
        fprintf(stderr, "SECURITY_ASSERTION_FAILED: HILIM=%ld <= LOLIM=%ld\\n",
                (long)inst->HILIM.value, (long)inst->LOLIM.value);
        fflush(stderr);
        return 2;
    }}

    /* P1: Array boundary check */
    #define ARRAY_SIZE 10
    for (int idx = 0; idx < ARRAY_SIZE; idx++) {{
        if (inst->ARRAY.value.table[idx] > MAX_LIMIT) {{
            fprintf(stderr, "SECURITY_ASSERTION_FAILED: ARRAY[%d]=%ld exceeds max\\n",
                    idx, (long)inst->ARRAY.value.table[idx]);
            fflush(stderr);
            return 3;
        }}
    }}

    return 0;
}}
```

## Output Rules

1. Output ONLY a `check_assertions()` function — no main(), no includes
2. Use `inst->VAR.value` for scalars, `inst->ARRAY.value.table[i] for arrays
3. fprintf format strings MUST be on a single line — NEVER split across lines
4. Always call `fflush(stderr)` after `fprintf`
5. Return non-zero to indicate which assertion failed
6. Use descriptive business-semantic error messages

Output ONLY the C code snippet with priority comments:
"""


RELATIONSHIP_INVARIANT_DESIGN_PROMPT = """
Please design relational invariants for the following program.

## Program analysis

**Program**: {pou_name}
**Main functionality**: {functionality}

**Core variables**
{core_vars}

**Variable relationship**:
{variable_relationships}

## Task

Design 3-5 relational invariants, each invariant contains:

1. **Name**: Brief description
2. **Business Semantics**: What does this invariant protect?
3. **Trigger Condition**: When is this invariant checked?
4. **Constraint expression**: What relationship must be maintained?
5. **Failure message**: How to report when violated?

## Example

**Invariant name**: boundary_order_constraint
**Business semantics**: When the channel is enabled, the upper limit must be greater than the lower limit.
**Trigger condition**: channel enabled (ENABLE[ch] == 1)
**Constraint Expression**: HILIM[ch] > LOLIM[ch]
**Failure message**: "Channel {ch} boundary constraint violated: HILIM={hilim} <= LOLIM={lolim}"

## Output

Please output the relation invariant design, each invariant includes the above 5 parts.
"""


class LLMAssertionDesignerV4:
    """LLM Assertion Designer v4 - Systematic Safety Invariant Version"""
    
    def __init__(self, logger: logging.Logger = None, log_file: str = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Set dedicated log file
        if log_file:
            self._setup_dedicated_logger(log_file)
        else:
            self._setup_dedicated_logger(f"assertion_gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        self._log_info("=== LLM Assertion Designer v4 Initialized ===")
        
        from langchain_openai import ChatOpenAI
        self.llm = ChatOpenAI(
            temperature=0.3,
            model=config_module.generator_model,
            api_key=config_module.generator_api_key,
            base_url=config_module.generator_base_url,
        )
        
        self.max_retries = 3
        
    def _setup_dedicated_logger(self, log_file: str):
        """Set up a dedicated logger"""
        # Ensure the log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file handler
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        
        # Dedicated logger
        self.dedicated_logger = logging.getLogger(f"assertion_gen_{id(self)}")
        self.dedicated_logger.setLevel(logging.INFO)
        self.dedicated_logger.addHandler(file_handler)
        self.dedicated_logger.propagate = False  # Do not propagate to parent logger
        
    def _log_info(self, msg: str):
        """Write to dedicated log file"""
        self.dedicated_logger.info(msg)
        self.logger.info(msg)
    
    def design_assertions(
        self,
        st_path: Path,
        pou_info: POUInfo,
        intent: TestIntent,
        existing_harness_path: Optional[Path] = None,
        pous_c_path: Optional[Path] = None
    ) -> AssertionCodeV4:
        """LLM generated assertion code (v4: systematic safety invariant)"""

        self._log_info("=" * 60)
        self._log_info(f"Starting assertion design: {pou_info.pou_name_upper}")
        self._log_info(f"ST file: {st_path}")
        self._log_info(f"Test intent: {intent.description}")
        self._log_info("=" * 60)

        # Step 0: Extract variable access examples from existing harness.c
        harness_examples = self._extract_harness_examples(existing_harness_path, pou_info) if existing_harness_path else ""

        # Step 0.5: Extract call logic summary from POUS.c (test functionality)
        pous_summary = self._extract_pous_summary(pous_c_path) if pous_c_path else ""
        if pous_summary:
            self._log_info("Injected POUS.c call logic summary")

        # Step 1: Systematic Safety Analysis
        self._log_info("\n--- Step 1: Systematic Safety Analysis ---")
        safety_analysis = self._analyze_systematic_safety(pou_info)
        self._log_info(f"Analysis completed:")
        self._log_info(f"  - Error code variables: {len(safety_analysis.error_code_vars)} items")
        self._log_info(f"  - Core business variables: {len(safety_analysis.core_business_vars)} items")
        self._log_info(f"  - All output variables: {len(safety_analysis.all_output_vars)} items")
        self._log_info(f"  - Relationship invariants: {len(safety_analysis.relationship_invariants)} items")
        
        # Log all available variables to the log
        self._log_info("\n--- All available output variables extracted from POUS.h ---")
        for i, var in enumerate(safety_analysis.all_output_vars, 1):
            array_info = f"[Array: {var['array_size']}]" if var['is_array'] else ""
            self._log_info(f"  {i}. {var['name']} ({var['type']}){array_info}")

        # Step 2: Prepare context
        error_code_vars = self._format_error_code_vars(safety_analysis.error_code_vars)
        core_business_vars = self._format_core_vars(safety_analysis.core_business_vars)
        all_output_vars_list = self._format_all_output_vars(safety_analysis.all_output_vars)
        identified_constraints = self._identify_constraints(pou_info, safety_analysis)
        suggested_invariants = self._suggest_invariants(safety_analysis)

        self._log_info("\n--- Step 2: Preparing LLM Prompt ---")
        self._log_info(f"Error code variables: {len(safety_analysis.error_code_vars)} items")
        self._log_info(f"Core business variables: {len(safety_analysis.core_business_vars)} items")
        self._log_info(f"Complete variable list length: {len(all_output_vars_list)} characters")
        
        # Step 3: Generate assertions
        c_code = None
        compilation_errors = []
        
        for attempt in range(self.max_retries):
            self._log_info(f"\n--- Step 3: LLM Generation Attempt {attempt + 1}/{self.max_retries} ---")

            # Read ST source code
            st_code = ""
            try:
                if st_path.exists():
                    st_code = st_path.read_text(encoding='utf-8')
                    # Limit length to avoid exceeding context
                    if len(st_code) > 4000:
                        st_code = st_code[:4000] + "\n... (truncated)"
            except Exception:
                pass

            # Prepare prompt
            prompt = ASSERTION_DESIGN_PROMPT_V4.format(
                pou_name=pou_info.pou_name_upper,
                pou_kind=pou_info.kind,
                functionality=self._identify_functionality(pou_info),
                st_code=st_code,
                error_code_vars=error_code_vars,
                core_business_vars=core_business_vars,
                all_output_vars_list=all_output_vars_list,
                identified_constraints=identified_constraints,
                suggested_invariants=suggested_invariants,
                intent=intent.description,
                harness_examples=harness_examples,
                pous_code_summary=pous_summary
            )

            # Call LLM
            try:
                self._log_info("Calling LLM...")
                # Record the complete input
                self._log_info("\n===== LLM INPUT =====")
                self._log_info(prompt)
                self._log_info("===== END INPUT =====\n")

                response = self.llm.invoke(prompt)
                c_code = response.content.strip()
                self._log_info(f"LLM returned code length: {len(c_code)} characters")
                # Record complete output
                self._log_info("\n===== LLM OUTPUT =====")
                self._log_info(c_code)
                self._log_info("===== END OUTPUT =====\n")

                # Verify code
                is_valid, errors = self._validate_code(c_code, pou_info)
                if is_valid:
                    self._log_info("OK - Assertion code verification passed")
                    break
                else:
                    compilation_errors = errors
                    self._log_info(f"FAILED - Validation failed:")
                    for err in errors:
                        self._log_info(f"  - {err}")
            except Exception as e:
                self._log_info(f"ERROR - LLM call failed: {e}")
                compilation_errors.append(str(e))
        
        # Step 4: Calculate priority distribution
        priority_distribution = self._analyze_priority_distribution(c_code or "")

        # Step 5: Determine the verification stage
        verification_stages = self._determine_verification_stages(safety_analysis)

        self._log_info("\n--- Assertion Generation Completed ---")
        self._log_info(f"Priority distribution: P0={priority_distribution.get('P0', 0)}, P1={priority_distribution.get('P1', 0)}")
        self._log_info("=" * 60)

        return AssertionCodeV4(
            c_code=c_code or "",
            description=f"Systematic safety invariant assertions ({priority_distribution.get('P0', 0)} P0, {priority_distribution.get('P1', 0)} P1)",
            target_variables=self._extract_target_variables(pou_info),
            compilation_errors=compilation_errors,
            is_valid=len(compilation_errors) == 0,
            safety_analysis=safety_analysis,
            priority_distribution=priority_distribution,
            verification_stages=verification_stages
        )
    
    def _analyze_systematic_safety(self, pou_info: POUInfo) -> SystematicSafetyAnalysis:
        """# Systematic security analysis - extract all variable information"""
        error_code_vars = []
        core_business_vars = []
        all_output_vars = []  # New: complete variable list
        relationship_invariants = []
        state_constraints = []
        edge_safety_checks = []

        self._log_info("=== Extracting variable information from POUS.h/POUInfo ===")
        self._log_info(f"POU name: {pou_info.pou_name_upper}")

        # Record all variable classifications
        self._log_info(f"Input variables (VAR_INPUT): {len(pou_info.inputs)} items")
        for var in pou_info.inputs:
            var_name = (var.pou_name if hasattr(var, 'pou_name') else var.name).upper()
            array_info = f"[Array: {var.array_size}]" if var.is_array else ""
            self._log_info(f"  - {var_name} ({var.iec_type}){array_info}")
            all_output_vars.append({"name": var_name, "type": var.iec_type, "is_array": var.is_array, "array_size": var.array_size if var.is_array else None, "category": "INPUT"})

        self._log_info(f"Output variables (VAR_OUTPUT): {len(pou_info.outputs)} items")
        for var in pou_info.outputs:
            var_name = (var.pou_name if hasattr(var, 'pou_name') else var.name).upper()
            array_info = f"[Array: {var.array_size}]" if var.is_array else ""

            # Build complete variable information
            var_info = {
                "name": var_name,
                "type": var.iec_type,
                "is_array": var.is_array,
                "array_size": var.array_size if var.is_array else None
            }
            all_output_vars.append(var_info)
            self._log_info(f"  - {var_name} ({var.iec_type}){array_info}")

            # Identify error code variable
            if any(keyword in var_name for keyword in ["RETVAL", "ERROR", "FAULT", "STATUS"]):
                error_code_vars.append(var_name)

            # All business variables are core business variables
            core_business_vars.append(var_info)

            # Design relational invariants (based on variable name inference)
            invariants = self._infer_invariants_from_var(var)
            relationship_invariants.extend(invariants)

        self._log_info(f"Input-output variables (VAR_IN_OUT): {len(pou_info.in_outs)} items")
        for var in pou_info.in_outs:
            var_name = (var.pou_name if hasattr(var, 'pou_name') else var.name).upper()
            array_info = f"[Array: {var.array_size}]" if var.is_array else ""
            self._log_info(f"  - {var_name} ({var.iec_type}){array_info}")
            all_output_vars.append({"name": var_name, "type": var.iec_type, "is_array": var.is_array, "array_size": var.array_size if var.is_array else None, "category": "IN_OUT"})

        self._log_info(f"Temporary variables (VAR_TEMP): {len(pou_info.temps)} items")
        for var in pou_info.temps:
            var_name = (var.pou_name if hasattr(var, 'pou_name') else var.name).upper()
            array_info = f"[Array: {var.array_size}]" if var.is_array else ""
            self._log_info(f"  - {var_name} ({var.iec_type}){array_info}")
            all_output_vars.append({"name": var_name, "type": var.iec_type, "is_array": var.is_array, "array_size": var.array_size if var.is_array else None, "category": "TEMP"})

        self._log_info(f"Local variables (VAR): {len(pou_info.locals)} items")
        for var in pou_info.locals:
            var_name = (var.pou_name if hasattr(var, 'pou_name') else var.name).upper()
            array_info = f"[Array: {var.array_size}]" if var.is_array else ""
            self._log_info(f"  - {var_name} ({var.iec_type}){array_info}")
            all_output_vars.append({"name": var_name, "type": var.iec_type, "is_array": var.is_array, "array_size": var.array_size if var.is_array else None, "category": "VAR"})

        return SystematicSafetyAnalysis(
            error_code_vars=error_code_vars,
            core_business_vars=core_business_vars,
            all_output_vars=all_output_vars,
            relationship_invariants=relationship_invariants,
            state_constraints=state_constraints,
            edge_safety_checks=edge_safety_checks
        )
    
    def _format_all_output_vars(self, all_vars: List[Dict]) -> str:
        """Format the complete variable list for LLM — including all types (INPUT/OUTPUT/IN_OUT/TEMP)"""
        lines = ["**ALL Available Variables (from POUS.h)** — Use ONLY these for assertions:"]
        for var in all_vars:
            cat = var.get('category', 'OUTPUT')
            array_info = f"  - Array[{var['array_size']}] OF" if var.get('is_array') else "  - Scalar"
            lines.append(f"{array_info} [{cat}] {var['name']} ({var.get('type','?')})")
        return "\n".join(lines)
    
    def _infer_invariants_from_var(self, var) -> List[SafetyInvariant]:
        """Infer relational invariants from variables."""
        invariants = []
        var_name = var.pou_name.upper()
        
        # Channel control related
        if "CHANNEL" in var_name or "CH" in var_name:
            if "ENABLE" in var_name:
                invariants.append(SafetyInvariant(
                    name=f"{var_name}_constraint",
                    description=f"{var_name} related constraint",
                    condition=f"{var_name}[ch] == 1",
                    invariant="Related constraint check",
                    priority=AssertionPriority.P0_SAFETY,
                    failure_message=f"{var_name} constraint violated"
                ))

        # Boundary value related
        if "HILIM" in var_name or "LOLIM" in var_name or "LIMIT" in var_name:
            invariants.append(SafetyInvariant(
                name=f"boundary_order_{var_name}",
                description="Boundary order constraint",
                condition="channel_enabled",
                invariant="HILIM > LOLIM",
                priority=AssertionPriority.P0_SAFETY,
                failure_message=f"Boundary order violated: HILIM <= LOLIM"
            ))

        return invariants
    
    def _format_error_code_vars(self, error_vars: List[str]) -> str:
        """Format error code variable information."""
        if not error_vars:
            return "No predefined error code variables detected, will design relationship invariants"
        return "\n".join(f"  - {var}" for var in error_vars)

    def _format_core_vars(self, core_vars: List[Dict]) -> str:
        """Format core variable information."""
        lines = []
        for var in core_vars:
            array_info = f"[Array: {var['array_size']}]" if var['is_array'] else ""
            lines.append(f"  - {var['name']} ({var['type']}){array_info}")
        return "\n".join(lines) if lines else "None"

    def _extract_pous_summary(self, pous_c_path: Optional[Path]) -> str:
        """Extract call logic summary from POUS.c (extract variable access patterns)"""
        if not pous_c_path or not pous_c_path.exists():
            self._log_info("POUS.c path does not exist, skipping extraction")
            return ""

        try:
            content = pous_c_path.read_text()

            self._log_info("\n=== Extracting POUS.c call logic ===")

            # Extract variable access pattern
            var_access_patterns = []
            struct_access_pattern = re.compile(r'__GET_VAR\(data__->([A-Z_][A-Z0-9_]*)')
            array_access_pattern = re.compile(r'__GET_VAR\(data__->([A-Z_][A-Z0-9_]*)\.table\[')
            set_var_pattern = re.compile(r'__SET_VAR\(data__->([A-Z_][A-Z0-9_]*)')

            for line in content.split('\n'):
                line = line.strip()

                # Extract variable read mode
                for match in struct_access_pattern.finditer(line):
                    var_name = match.group(1)
                    if var_name not in ['EN', 'ENO'] and f"data__->{var_name} (read)" not in var_access_patterns:
                        var_access_patterns.append(f"data__->{var_name} (read)")

                # Extract array access pattern
                for match in array_access_pattern.finditer(line):
                    var_name = match.group(1)
                    pattern = f"data__->{var_name}.table[index]"
                    if pattern not in var_access_patterns:
                        var_access_patterns.append(pattern)

                # Extract variable write mode
                for match in set_var_pattern.finditer(line):
                    var_name = match.group(1)
                    if var_name not in ['EN', 'ENO']:
                        write_pattern = f"data__->{var_name} (write)"
                        if write_pattern not in var_access_patterns:
                            var_access_patterns.append(write_pattern)

            # Extract function definition
            func_defs = []
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('void ') and ('__body__' in line or '__init__' in line):
                    func_name = line.split('(')[0].replace('void ', '').strip()
                    func_defs.append(func_name)

            self._log_info(f"Extracted {len(func_defs)} function definitions")
            self._log_info(f"Extracted {len(var_access_patterns)} variable access patterns")

            if var_access_patterns or func_defs:
                summary = "\n## POUS.c Internal Variable Access Patterns\n\n"
                summary += "// Variable access patterns (in __body__ function):\n"
                for pattern in var_access_patterns[:20]:  # Limit quantity
                    summary += f"//   {pattern}\n"

                if func_defs:
                    summary += "\n// Generated functions:\n"
                    for func in func_defs[:5]:
                        summary += f"//   {func}\n"

                summary += "\n// Note: Use inst->VAR.value in assertions instead of data__->VAR\n"
                return summary

            return ""

        except Exception as e:
            self._log_info(f"Failed to extract POUS.c summary: {e}")
            import traceback
            traceback.print_exc()
            return ""
    

    def _identify_constraints(self, pou_info: POUInfo, analysis: SystematicSafetyAnalysis) -> str:
        """Identify constraint relationships."""
        constraints = []

        # Infer constraints based on variable names
        var_names = [v.pou_name.upper() for v in pou_info.outputs]

        # Check if there is a paired HILIM/LOLIM
        has_hilim = any("HILIM" in n for n in var_names)
        has_lolim = any("LOLIM" in n for n in var_names)
        if has_hilim and has_lolim:
            constraints.append("Boundary constraint: HILIM > LOLIM")

        # Check if there is ENABLE variable
        has_enable = any("ENABLE" in n for n in var_names)
        if has_enable:
            constraints.append("Enable constraint: boundaries must be valid when enabled")

        # Check countdown/counter variable (needs upper bound check, not just >= 0)
        has_countdown = any("COUNTDOWN" in n or "COUNTER" in n for n in var_names)
        if has_countdown:
            constraints.append("Boundary constraint: VAL_COUNTDOWN must be within valid range 0-9, cannot exceed upper bound 9")

        return "\n".join(constraints) if constraints else "No obvious constraint relationships"

    def _suggest_invariants(self, analysis: SystematicSafetyAnalysis) -> str:
        """Suggested relation invariant."""
        suggestions = []

        for inv in analysis.relationship_invariants:
            suggestions.append(f"- {inv.name}: {inv.description}")

        return "\n".join(suggestions) if suggestions else "None"

    def _identify_functionality(self, pou_info: POUInfo) -> str:
        """Identify program functionality."""
        var_names = " ".join(v.pou_name.upper() for v in pou_info.outputs)

        if "CHANNEL" in var_names:
            return "Multi-channel control"
        elif "LAMP" in var_names or "TRAFFIC" in var_names or "COUNTDOWN" in var_names:
            return "Traffic light control (countdown 0-9 upper bound)"
        elif "STATE" in var_names or "MODE" in var_names:
            return "State machine control"
        elif "BATCH" in var_names or "ARRAY" in var_names:
            return "Batch processing"
        else:
            return "Generic processing"
    
    def _validate_code(self, code: str, pou_info: POUInfo) -> Tuple[bool, List[str]]:
        """# Verify the generated assertion code
        
Enhanced validation logic:
1. Code is not empty
2. Include check_assertions function
3. Use inst-> arrow access
4. fprintf format string does not have line breaks
5. Loop variable already declared
6. **Key**: Only use variables that exist in the POU output.
        """
        errors = []
        
        if not code or code.strip() == "":
            return False, ["Generated code is empty"]
        
        # must have check_assertions function
        if "check_assertions" not in code:
            errors.append("Missing check_assertions() function")
        
        # Must have fprintf output
        if "fprintf" not in code or "stderr" not in code:
            errors.append("Missing fprintf(stderr, ...) output")
        
        # Check bracket balance
        open_braces = code.count('{')
        close_braces = code.count('}')
        if open_braces != close_braces:
            errors.append(f"Brace mismatch: {{ {open_braces} vs }} {close_braces}")
        
        # Check that fprintf format string does not break lines
        fprintf_lines = []
        in_fprintf = False
        for line in code.split('\n'):
            if 'fprintf(' in line:
                in_fprintf = True
            if in_fprintf:
                fprintf_lines.append(line)
            if ');' in line and in_fprintf:
                in_fprintf = False
                if sum(l.count('"') for l in fprintf_lines) % 2 != 0:
                    errors.append(f"Format string split across lines: {' '.join(s.strip()[:40] for s in fprintf_lines)}")
                fprintf_lines = []

        # **Key**: Check that only existing variables are used
        # Extract variable names used in the code
        used_vars = set()
        code_no_strings = re.sub(r'"[^"]*"', '""', code)

        # Match inst->VAR_NAME.value pattern
        var_pattern = re.compile(r'inst->([A-Z_][A-Z0-9_]*)\.')
        for match in var_pattern.finditer(code_no_strings):
            used_var = match.group(1)
            # Skip common C keywords
            if used_var not in ('IF', 'FOR', 'WHILE', 'INT', 'BOOL', 'REAL', 'RETURN', 'VOID', 'SIZE'):
                used_vars.add(used_var)

        # Check if each used variable is in the complete variable list (including INPUT/OUTPUT/IN_OUT/TEMP)
        available_vars = {v.pou_name.upper() for v in pou_info.outputs}
        available_vars |= {v.pou_name.upper() for v in pou_info.inputs}
        available_vars |= {v.pou_name.upper() for v in pou_info.in_outs}
        available_vars |= {v.pou_name.upper() for v in pou_info.temps}
        available_vars |= {v.pou_name.upper() for v in pou_info.locals}

        # Record to log
        self._log_info(f"--- Variable Validation ---")
        self._log_info(f"Variables used in code: {', '.join(sorted(used_vars)) if used_vars else '(none)'}")
        self._log_info(f"Available variables: {', '.join(sorted(available_vars))}")

        for used_var in used_vars:
            if used_var not in available_vars:
                errors.append(f"Variable '{used_var}' used but NOT in available output variables. "
                            f"Available: {', '.join(sorted(available_vars))}")
                self._log_info(f"ERROR: Variable '{used_var}' does not exist")

        if not errors and used_vars:
            self._log_info(f"OK - Variable validation passed: used {len(used_vars)} variables, all exist in output list")

        return len(errors) == 0, errors

    def _analyze_priority_distribution(self, code: str) -> Dict[str, int]:
        """Analyze assertion priority distribution."""
        distribution = {"P0": 0, "P1": 0}

        # Count P0 markers
        distribution["P0"] += code.count("P0")
        distribution["P0"] += code.count("core_design")
        distribution["P0"] += code.count("error_code")
        distribution["P0"] += code.count("relationship_invariant")
        distribution["P0"] += code.count("state_consistency")

        # Count P1 markers
        distribution["P1"] += code.count("P1")
        distribution["P1"] += code.count("edge")
        distribution["P1"] += code.count("boundary_check")

        return distribution

    def _determine_verification_stages(self, analysis: SystematicSafetyAnalysis) -> List[str]:
        """Determine verification phase."""
        stages = ["safety_verification"]

        if analysis.error_code_vars:
            stages.append("reliability_verification")
        else:
            stages.append("business_logic_verification")

        stages.append("edge_safety_check")
        
        return stages
    
    def _extract_target_variables(self, pou_info: POUInfo) -> List[str]:
        """Extract the target variable."""
        return [v.pou_name for v in pou_info.outputs]
    
    def _extract_harness_examples(self, harness_path: Optional[Path], pou_info: POUInfo) -> str:
        """Extract variable access examples from existing harness.c."""
        if not harness_path or not harness_path.exists():
            return ""
        
        try:
            harness_code = harness_path.read_text()
            examples = []
            
            for var in pou_info.outputs:
                pou_name = var.pou_name.upper()
                patterns = [
                    f"instance->{pou_name}.value",
                    f"instance->{pou_name}.value.table[",
                ]
                for pattern in patterns:
                    if pattern in harness_code:
                        lines = harness_code.split('\n')
                        for lineno, line in enumerate(lines):
                            if pattern in line and '/*' not in line:
                                cleaned = line.strip()
                                if cleaned and not cleaned.startswith('//') and len(cleaned) > 10:
                                    examples.append(f"// harness.c line {lineno+1}: {cleaned}")
                                    break
                        if examples and pattern in examples[-1]:
                            break
            
            if examples:
                header = ("\n## Existing harness.c variable access examples\n"
                          "// These show the REAL variable names and access patterns.\n"
                          "// In main(), instance is a struct value (use dot: instance.VAR.value).\n"
                          "// In functions like read_inputs(), instance is a pointer (use arrow: instance->VAR.value).\n")
                return header + "\n".join(examples[:20])
            return ""

        except Exception as e:
            self._log_info(f"Failed to extract harness examples: {e}")
            return ""


__all__ = [
    "LLMAssertionDesignerV4",
    "AssertionCodeV4",
    "SystematicSafetyAnalysis",
    "SafetyInvariant",
    "AssertionPriority"
]
