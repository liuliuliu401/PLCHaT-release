"""
PLCHaT IR Types
Intermediate Representation for ST program structures.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from core.data_types.base_types import BaseType


# ---------------------- ST Program Structure IR ----------------------

@dataclass
class STVariableDecl(BaseType):
    """Represents a single variable declaration (e.g., i : INT := 0;)."""
    name: str
    st_type: str        # e.g., 'INT', 'BOOL', 'ARRAY[1..5] OF INT'
    scope: str  # "VAR_INPUT", "VAR_OUTPUT", "VAR", "VAR_IN_OUT", "VAR_GLOBAL"

    # --- 1-Base / 0-Base Alignment Fields (Key: used for padding method) ---
    # The default value in the *Python* environment (for initialization)
    py_default_value: Any

    # Actual size in Python (N+1 for 1-based index arrays, 1 for scalar)
    py_size: int = 1

    # Store the parsed ST array bounds, e.g., (1, 5) for ARRAY[1..5] OF...
    st_array_bounds: Optional[tuple] = None


@dataclass
class STPOUIR(BaseType):
    """The main IR for a POU in Structured Text, e.g, FUNCTION_BLOCK or PROGRAM."""

    name: str

    # All variable declarations parsed from the header
    declarations: List[STVariableDecl] = field(default_factory=list)

    # Categorized variables for easier code generation
    inputs: List[STVariableDecl] = field(default_factory=list)
    outputs: List[STVariableDecl] = field(default_factory=list)
    internals: List[STVariableDecl] = field(default_factory=list)

    # The translated Python code lines for the body logic.
    # The AST Visitor will populate this list of strings (or more complex StatementIR).
    py_logic_code: List[str] = field(default_factory=list)
