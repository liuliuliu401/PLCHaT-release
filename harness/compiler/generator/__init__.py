"""
PLCHaT Harness Generator Module

Automatically generate a complete Harness test suite from ST source code:
- harness.c (C test driver)
- input_schema_v2.json (Data Contract)
- input.txt (initial seed)

Process:
ST source code → [Preprocessing] → [MatIEC Compilation] → POUS.h → [Parsing] → VariableInfo
                                       ↑                     ↓
[Lark ST Parser]        [Jinja2 Template] → harness.c
                                                          → schema.json
                                                          → input.txt

Module structure:
- st_parser: ST source code parser (based on Lark)
- pou_parser: POUS.h parser (MatIEC output)
type_mapper: IEC 61131-3 type to C type mapping
- harness_gen: harness.c generator (Jinja2 template)
- schema_gen: input_schema_v2.json generator
seed_gen: input.txt seed generator
- llm_fallback: LLM fallback strategy
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


__all__ = [
    "VariableInfo",
    "VarDecl",
    "HarnessGenerator",
]


@dataclass
class VarDecl:
    """variable declaration"""
    name: str                  # Variable name (original name in ST, lowercase)
    pou_name: str              # Name in POU structure (uppercase, MatIEC format)
    iec_type: str              # IEC types (BOOL, INT, DINT, REAL, etc.)
    direction: str             # VAR_INPUT | VAR_OUTPUT | VAR_IN_OUT | VAR_TEMP | VAR
    is_array: bool             # Whether array
    array_size: int = None     # array size
    array_lo: int = None       # Array lower bound (in ST, e.g., 1)
    array_hi: int = None       # Array upper bound (in ST, such as 10)

    @property
    def c_type(self) -> str:
        """Corresponding C type (for temp variable declaration)

Based on the definition of MatIEC iec_types.h.
For MatIEC generated types not in the mapping table (such as __ARRAY_OF_T_*, T_*_INFO, IEC_*),
Directly use iec_type as a C type —— MatIEC has generated the corresponding typedef.
        """
        t = (self.iec_type or "").upper()
        type_map = {
            # 8-bit types (use int for scanf compatibility)
            "BOOL": "int", "SINT": "int", "USINT": "int", "BYTE": "int",
            # 16-bit types
            "INT": "int", "UINT": "int", "WORD": "int",
            # 32-bit types
            "DINT": "long", "UDINT": "unsigned long", "DWORD": "unsigned long",
            # 64-bit types
            "LINT": "long long", "ULINT": "unsigned long long", "LWORD": "unsigned long long",
            # Floating point
            "REAL": "float", "LREAL": "double",
            # Time/Date types (MatIEC structs: IEC_TIME, IEC_DATE, etc.)
            "TIME": "IEC_TIME", "DATE": "IEC_DATE", "TOD": "IEC_TOD", "DT": "IEC_DT",
            # String (MatIEC: IEC_STRING struct, C-level: char* for scanf)
            "STRING": "char*",
        }
        if t in type_map:
            return type_map[t]
        # MatIEC-generated types: use the iec_type directly as the C typedef name
        # e.g. __ARRAY_OF_T_GARAGE_SLOT_3_5, T_TRUCK_INFO, IEC_BOOL, etc.
        if t.startswith("__") or t.startswith("T_") or t.startswith("IEC_"):
            return self.iec_type
        return "int"

    @property
    def scanf_format(self) -> str:
        """scanf format string, corresponding to c_type. Complex types (struct/array) do not apply to scanf."""
        t = (self.iec_type or "").upper()
        format_map = {
            "REAL": "%f", "LREAL": "%lf",
            "LINT": "%lld", "ULINT": "%llu", "LWORD": "%llu",
            "DINT": "%ld", "UDINT": "%lu", "DWORD": "%lu",
            "STRING": "%s",
        }
        if t in format_map:
            return format_map[t]
        if t in ("TIME", "DATE", "TOD", "DT", "BOOL"):
            return "%d"
        # MatIEC-generated types (structs, arrays): can't scanf directly
        if t.startswith("__") or t.startswith("T_") or t.startswith("IEC_"):
            return "%d"  # scanf won't work but keeps template compatible
        return "%d"

    @property
    def printf_format(self) -> str:
        """printf format string (for numeric output)

Note: BOOL needs special handling (string output), not within the scope of this attribute
        """
        iec = self.iec_type.upper()

        # Floating point - use %f for both REAL and LREAL (with double cast)
        if iec in ("REAL", "LREAL"):
            return "%f"

        # 64-bit types
        if iec == "LINT":
            return "%lld"
        if iec in ("ULINT", "LWORD"):
            return "%llu"

        # 32-bit types
        if iec == "DINT":
            return "%ld"
        if iec in ("UDINT", "DWORD"):
            return "%lu"

        # 8/16-bit types
        return "%d"

    @property
    def printf_cast(self) -> str:
        """Type conversion when printf outputs

Returns the C type string to convert to, such as "(long)", "(double)", "" (no conversion)
        """
        iec = self.iec_type.upper()

        # Floating point - always cast to double for printf
        if iec in ("REAL", "LREAL"):
            return "(double)"

        # 64-bit types
        if iec == "LINT":
            return "(long long)"
        if iec in ("ULINT", "LWORD"):
            return "(unsigned long long)"

        # 32-bit types
        if iec == "DINT":
            return "(long)"
        if iec in ("UDINT", "DWORD"):
            return "(unsigned long)"

        # 8/16-bit types and BOOL - cast to int is sufficient
        return "(int)"

    @property
    def is_struct(self) -> bool:
        """Whether this type is a MatIEC struct/array (can't use scanf)."""
        t = (self.iec_type or "").upper()
        # Known struct types
        if t in ("TIME", "DATE", "TOD", "DT", "STRING"):
            return True
        # MatIEC-generated struct/array types
        if t.startswith("__") or t.startswith("T_") or t.startswith("IEC_"):
            return True
        return False

    @property
    def matiec_type(self) -> str:
        """MatIEC C type name"""
        return self.iec_type.upper()


@dataclass
class POUInfo:
    """# POU (Program Organization Unit) information"""
    kind: str                  # FUNCTION_BLOCK | FUNCTION | PROGRAM
    name: str                  # POU name (original name in ST)
    pou_name_upper: str        # Uppercase name generated by MatIEC

    # Variable classification
    inputs: List[VarDecl] = field(default_factory=list)
    outputs: List[VarDecl] = field(default_factory=list)
    in_outs: List[VarDecl] = field(default_factory=list)
    temps: List[VarDecl] = field(default_factory=list)
    locals: List[VarDecl] = field(default_factory=list)

    @property
    def all_vars(self) -> List[VarDecl]:
        return self.inputs + self.outputs + self.in_outs + self.temps + self.locals

    @property
    def input_vars(self) -> List[VarDecl]:
        """Variables that need to be input via stdin (INPUT + IN_OUT)"""
        return self.inputs + self.in_outs


@dataclass
class GenerationResult:
    """Generate result"""
    success: bool
    pou_info: Optional[POUInfo] = None
    harness_path: Optional[Path] = None
    schema_path: Optional[Path] = None
    seed_path: Optional[Path] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    fallback_used: bool = False
