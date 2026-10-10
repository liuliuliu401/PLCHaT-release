"""
Assertion Template Library - Function Point Specific Assertion Templates

Provide assertion templates for different functional points to guide LLMs in generating more targeted assertions.
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class AssertionTemplate:
    """assertion template"""
    name: str                              # template name
    functionality: str                     # Feature point
    category: str                          # safety | functional | tracking
    description: str                        # Description
    code_template: str                     # code template
    target_variables: List[str]            # Target variable type hint
    severity: str = "warning"              # critical | warning | info


# ============================================================================
# Function point specific assertion template
# ============================================================================

ASSERTION_TEMPLATES: Dict[str, List[AssertionTemplate]] = {
    "traffic_light_control": [
        # 【Specification 1: Interlock Safety】 The north-south and east-west green lights cannot be on simultaneously.
        AssertionTemplate(
            name="mutual_exclusion_green_check",
            functionality="traffic_light_control",
            category="safety",
            description="Interlock Safety: NS and EW green lights cannot be ON simultaneously (prevents collision accidents)",
            code_template="""
if (instance.LAMP_NS_GREEN.value && instance.LAMP_EW_GREEN.value) {{
    fprintf(stderr, "AUDIT FAIL: Mutual exclusion violated - NS and EW green both ON [cycle=%d]\\n", cycle);
    exit(1);
}}
""",
            target_variables=["lamp_ns_green", "lamp_ew_green"],
            severity="critical"
        ),
        # [Specification 2: State Consistency] Conflict of red and green lights on the same side
        AssertionTemplate(
            name="state_consistency_check",
            functionality="traffic_light_control",
            category="safety",
            description="State Consistency: Red and green lights on same side cannot be ON simultaneously",
            code_template="""
if ((instance.LAMP_NS_GREEN.value && instance.LAMP_NS_RED.value) ||
    (instance.LAMP_EW_GREEN.value && instance.LAMP_EW_RED.value)) {{
    fprintf(stderr, "AUDIT FAIL: State consistency violated - red and green on same side [NS: G=%d R=%d, EW: G=%d R=%d]\\n",
            instance.LAMP_NS_GREEN.value, instance.LAMP_NS_RED.value,
            instance.LAMP_EW_GREEN.value, instance.LAMP_EW_RED.value);
    exit(1);
}}
""",
            target_variables=["lamp_ns_green", "lamp_ns_red", "lamp_ew_green", "lamp_ew_red"],
            severity="critical"
        ),
        # [Rule 3: Numerical Boundary Protection] Countdown out-of-bounds check (0-9)
        AssertionTemplate(
            name="countdown_boundary_check",
            functionality="traffic_light_control",
            category="safety",
            description="Numerical Boundary Protection: Countdown must be within valid range (0-9)",
            code_template="""
if (instance.VAL_COUNTDOWN.value < 0 || instance.VAL_COUNTDOWN.value > 9) {{
    fprintf(stderr, "AUDIT FAIL: Countdown out of range [value=%ld, valid=0-9]\\n",
            (long)instance.VAL_COUNTDOWN.value);
    exit(1);
}}
""",
            target_variables=["val_countdown"],
            severity="critical"
        ),
        # [Protocol 4: Deadlock Detection] State machine complete deadlock dead zone check
        AssertionTemplate(
            name="deadlock_detection_check",
            functionality="traffic_light_control",
            category="safety",
            description="Deadlock Detection: All lights cannot be OFF simultaneously (detects S40 state bug)",
            code_template="""
if (!instance.LAMP_NS_GREEN.value && !instance.LAMP_NS_RED.value &&
    !instance.LAMP_EW_GREEN.value && !instance.LAMP_EW_RED.value) {{
    fprintf(stderr, "AUDIT FAIL: Deadlock detected - ALL LAMPS OFF [NS: G=%d R=%d, EW: G=%d R=%d]\\n",
            instance.LAMP_NS_GREEN.value, instance.LAMP_NS_RED.value,
            instance.LAMP_EW_GREEN.value, instance.LAMP_EW_RED.value);
    exit(1);
}}
""",
            target_variables=["lamp_ns_green", "lamp_ns_red", "lamp_ew_green", "lamp_ew_red"],
            severity="critical"
        ),
        # [Protocol 5: Buffer Phase Integrity] Red light safety gap check during buffer period
        AssertionTemplate(
            name="buffer_phase_integrity_check",
            functionality="traffic_light_control",
            category="safety",
            description="Buffer Phase Integrity: Red light safety gap must be maintained during buffer phase (countdown<3)",
            code_template="""
if (instance.VAL_COUNTDOWN.value >= 0 && instance.VAL_COUNTDOWN.value < 3) {{
    if (!instance.LAMP_NS_RED.value && !instance.LAMP_EW_RED.value) {{
        fprintf(stderr, "AUDIT FAIL: Buffer phase integrity violated - no red during buffer phase [countdown=%ld, NS_R=%d, EW_R=%d]\\n",
                (long)instance.VAL_COUNTDOWN.value,
                instance.LAMP_NS_RED.value, instance.LAMP_EW_RED.value);
        exit(1);
    }}
}}
""",
            target_variables=["val_countdown", "lamp_ns_red", "lamp_ew_red"],
            severity="critical"
        ),
        # Track assertion: record current traffic light state
        AssertionTemplate(
            name="traffic_light_state_tracking",
            functionality="traffic_light_control",
            category="tracking",
            description="Tracking Assertion: Record current traffic light state (for debugging and logging)",
            code_template="""
fprintf(stderr, "AUDIT INFO: TrafficLight state [cycle=%d] NS_G=%d NS_R=%d EW_G=%d EW_R=%d Countdown=%ld\\n",
        cycle,
        instance.LAMP_NS_GREEN.value, instance.LAMP_NS_RED.value,
        instance.LAMP_EW_GREEN.value, instance.LAMP_EW_RED.value,
        (long)instance.VAL_COUNTDOWN.value);
""",
            target_variables=["lamp_ns_green", "lamp_ns_red", "lamp_ew_green", "lamp_ew_red", "val_countdown"],
            severity="info"
        ),
    ],

    "channel_control": [
        AssertionTemplate(
            name="channel_error_check",
            functionality="channel_control",
            category="safety",
            description="Check channel error status, non-zero return value indicates error",
            code_template="""
for (int ch = 0; ch < {array_size}; ch++) {{
    if (instance.{retval_var}.value.table[ch] != 0) {{
        fprintf(stderr, "AUDIT FAIL: Channel %d error (retval=%d)\\n", ch+1, instance.{retval_var}.value.table[ch]);
        exit(1);
    }}
}}
""",
            target_variables=["retval"],
            severity="critical"
        ),
        AssertionTemplate(
            name="channel_boundary_fold_check",
            functionality="channel_control",
            category="safety",
            description="Check enabled channel boundary fold risk (HILIM == LOLIM)",
            code_template="""
for (int ch = 0; ch < {array_size}; ch++) {{
    if (instance.{enable_var}.value.table[ch] &&
        instance.{hilim_var}.value.table[ch] == instance.{lolim_var}.value.table[ch]) {{
        fprintf(stderr, "AUDIT FAIL: Channel %d boundary fold (HILIM==LOLIM=%.2f)\\n",
                ch+1, instance.{hilim_var}.value.table[ch]);
        exit(1);
    }}
}}
""",
            target_variables=["enable", "hilim", "lolim"],
            severity="critical"
        ),
        AssertionTemplate(
            name="channel_boundary_invert_check",
            functionality="channel_control",
            category="safety",
            description="Check boundary inversion risk (HILIM < LOLIM)",
            code_template="""
for (int ch = 0; ch < {array_size}; ch++) {{
    if (instance.{hilim_var}.value.table[ch] < instance.{lolim_var}.value.table[ch]) {{
        fprintf(stderr, "AUDIT FAIL: Channel %d boundary inverted (HILIM=%.2f < LOLIM=%.2f)\\n",
                ch+1, instance.{hilim_var}.value.table[ch], instance.{lolim_var}.value.table[ch]);
        exit(1);
    }}
}}
""",
            target_variables=["hilim", "lolim"],
            severity="critical"
        ),
        AssertionTemplate(
            name="channel_state_tracking",
            functionality="channel_control",
            category="tracking",
            description="Track channel state, record even when passed",
            code_template="""
int active_channels = 0;
for (int ch = 0; ch < {array_size}; ch++) {{
    if (instance.{enable_var}.value.table[ch]) {{
        active_channels++;
    }}
}}
fprintf(stderr, "AUDIT INFO: %d/%d channels active\\n", active_channels, {array_size});
""",
            target_variables=["enable"],
            severity="info"
        ),
    ],

    "state_machine": [
        AssertionTemplate(
            name="state_transition_check",
            functionality="state_machine",
            category="safety",
            description="Check validity of state transitions",
            code_template="""
if (instance.{state_var}.value < 0 || instance.{state_var}.value >= {max_state}) {{
    fprintf(stderr, "AUDIT FAIL: Invalid state %d (valid: 0-%d)\\n",
            instance.{state_var}.value, {max_state}-1);
    exit(1);
}}
""",
            target_variables=["state"],
            severity="critical"
        ),
        AssertionTemplate(
            name="state_transition_tracking",
            functionality="state_machine",
            category="tracking",
            description="Track state transitions",
            code_template="""
fprintf(stderr, "AUDIT INFO: Current state=%d, prev_state=%d\\n",
        instance.{state_var}.value, instance.{prev_state_var}.value);
""",
            target_variables=["state", "prev_state"],
            severity="info"
        ),
    ],

    "batch_processing": [
        AssertionTemplate(
            name="array_bounds_check",
            functionality="batch_processing",
            category="safety",
            description="Check array access bounds",
            code_template="""
if (instance.{index_var}.value < 0 || instance.{index_var}.value >= {array_size}) {{
    fprintf(stderr, "AUDIT FAIL: Array index out of bounds (index=%d, size=%d)\\n",
            instance.{index_var}.value, {array_size});
    exit(1);
}}
""",
            target_variables=["index"],
            severity="critical"
        ),
        AssertionTemplate(
            name="batch_consistency_check",
            functionality="batch_processing",
            category="functional",
            description="Check batch operation consistency",
            code_template="""
int valid_count = 0;
for (int i = 0; i < {array_size}; i++) {{
    if (instance.{valid_var}.value.table[i]) {{
        valid_count++;
    }}
}}
if (valid_count == 0) {{
    fprintf(stderr, "AUDIT FAIL: No valid items in batch (total=%d)\\n", {array_size});
    exit(1);
}}
""",
            target_variables=["valid"],
            severity="warning"
        ),
    ],

    "overflow_protection": [
        AssertionTemplate(
            name="overflow_check",
            functionality="overflow_protection",
            category="safety",
            description="Check numeric overflow",
            code_template="""
if (instance.{value_var}.value > {max_value}) {{
    fprintf(stderr, "AUDIT FAIL: Value overflow (value=%d, max=%d)\\n",
            instance.{value_var}.value, {max_value});
    exit(1);
}}
""",
            target_variables=["value"],
            severity="critical"
        ),
        AssertionTemplate(
            name="underflow_check",
            functionality="overflow_protection",
            category="safety",
            description="Check numeric underflow",
            code_template="""
if (instance.{value_var}.value < 0) {{
    fprintf(stderr, "AUDIT FAIL: Value underflow (value=%d)\\n",
            instance.{value_var}.value);
    exit(1);
}}
""",
            target_variables=["value"],
            severity="critical"
        ),
    ],

    "general": [
        AssertionTemplate(
            name="variable_range_check",
            functionality="general",
            category="functional",
            description="Generic variable range check",
            code_template="""
if (instance.{var}.value < {min_val} || instance.{var}.value > {max_val}) {{
    fprintf(stderr, "AUDIT FAIL: {var} out of range (value=%d, range=[{min_val},{max_val}])\\n",
            instance.{var}.value);
    exit(1);
}}
""",
            target_variables=["any"],
            severity="warning"
        ),
    ],
}


# ============================================================================
# Function point identification rules
# ============================================================================

FUNCTIONALITY_PATTERNS = {
    "traffic_light_control": [
        ("lamp", "LAMP"),
        ("traffic", "TRAFFIC"),
        ("light", "LIGHT"),
        ("green", "GREEN"),
        ("red", "RED"),
    ],
    "channel_control": [
        ("channel", "CHANNEL"),
        ("enable", "ENABLE"),
        ("limit", "LIM"),
        ("boundary", "BOUNDARY"),
    ],
    "state_machine": [
        ("state", "STATE"),
        ("mode", "MODE"),
        ("phase", "PHASE"),
    ],
    "batch_processing": [
        ("batch", "BATCH"),
        ("array", "ARRAY"),
        ("loop", "LOOP"),
    ],
    "overflow_protection": [
        ("overflow", "OVERFLOW"),
        ("underflow", "UNDERFLOW"),
        ("limit", "LIMIT"),
    ],
}


def identify_functionality(var_names: List[str]) -> List[str]:
    """Identify function points based on variable names"""
    functionalities = []
    var_names_str = " ".join(var_names).upper()

    for func, patterns in FUNCTIONALITY_PATTERNS.items():
        for pattern, _ in patterns:
            if pattern.upper() in var_names_str:
                if func not in functionalities:
                    functionalities.append(func)
                break

    return functionalities if functionalities else ["general"]


def get_templates_for_functionality(functionality: str) -> List[AssertionTemplate]:
    """Get assertion template for specified feature point"""
    return ASSERTION_TEMPLATES.get(functionality, ASSERTION_TEMPLATES["general"])


def get_safety_templates(functionality: str) -> List[AssertionTemplate]:
    """# Get the safety type assertion template for the specified function point."""
    templates = get_templates_for_functionality(functionality)
    return [t for t in templates if t.category == "safety"]


def get_tracking_templates(functionality: str) -> List[AssertionTemplate]:
    """Get the tracking type assertion template for the specified function point"""
    templates = get_templates_for_functionality(functionality)
    return [t for t in templates if t.category == "tracking"]


def format_templates_for_prompt(templates: List[AssertionTemplate]) -> str:
    """Format the template into a prompt format."""
    if not templates:
        return "No available templates"

    lines = []
    for template in templates[:5]:  # Limit quantity
        lines.append(f"Template: {template.name}")
        lines.append(f"  Functionality: {template.functionality}")
        lines.append(f"  Type: {template.category} ({template.severity})")
        lines.append(f"  Description: {template.description}")
        lines.append(f"```c")
        lines.append(template.code_template.strip())
        lines.append(f"```")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "AssertionTemplate",
    "ASSERTION_TEMPLATES",
    "identify_functionality",
    "get_templates_for_functionality",
    "get_safety_templates",
    "get_tracking_templates",
    "format_templates_for_prompt",
]
