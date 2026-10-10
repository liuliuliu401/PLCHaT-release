"""
AST to Z3 Logic Transpiler

Converts IEC 61131-3 ST AST to Python Z3 execution logic for DSEEngine.

Replaces LLM-based transpiler with deterministic AST-based generation.
Follows IEC 61131-3 standard and ensures correct control flow handling.

Design:
- Parse ST using legacy parser (lang/parser.py)
- Convert AST to Z3 Python code
- Ensure correct branch handling with engine.fork_if
"""

import sys
from pathlib import Path
from typing import List, Optional, Dict, Any, Set, Tuple
from dataclasses import dataclass, field

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import from st_parser_lark
from tools.fuzzers.dse.st_parser_lark.parser import parse_program, ParserConfig
from tools.fuzzers.dse.st_parser_lark import st_ast
import tools.fuzzers.dse.st_parser_lark as lark

# Alias Lark AST types for local use
POU = lark.ast.POU
VarDecl = lark.ast.VarDecl
Expr = lark.ast.Expr
Stmt = lark.ast.Stmt

# Statement types
IfStmt = lark.ast.IfStmt
CaseStmt = lark.ast.CaseStmt
ForStmt = lark.ast.ForStmt
WhileStmt = lark.ast.WhileStmt
RepeatStmt = lark.ast.RepeatStmt
Assign = lark.ast.Assign
CallStmt = lark.ast.CallStmt
ExitStmt = lark.ast.ExitStmt
ContinueStmt = lark.ast.ContinueStmt
ReturnStmt = lark.ast.ReturnStmt

# Expression types
BoolLit = lark.ast.BoolLit
IntLit = lark.ast.IntLit
RealLit = lark.ast.RealLit
StringLit = lark.ast.StringLit
TimeLit = lark.ast.TimeLit
TypedHexLit = lark.ast.TypedHexLit
VarRef = lark.ast.VarRef
ArrayAccess = lark.ast.ArrayAccess
MemberAccess = lark.ast.MemberAccess
BinOp = lark.ast.BinOp
UnOp = lark.ast.UnOp
CallExpr = lark.ast.CallExpr

# Case statement types
CaseArm = lark.ast.CaseArm


@dataclass
class VarInfo:
    """Variable information for code generation."""
    name: str
    iec_type: str
    is_input: bool = False
    is_internal: bool = False
    is_array: bool = False
    init_value: Optional[str] = None
    # Array bounds: (lower, upper) for ARRAY[lower..upper] OF type
    array_bounds: Optional[Tuple[int, int]] = None


@dataclass
class Z3GenContext:
    """Context for Z3 code generation."""
    pou: POU
    input_vars: List[VarInfo] = field(default_factory=list)
    internal_vars: List[VarInfo] = field(default_factory=list)
    branch_counter: int = 0
    temp_counter: int = 0
    # Track if current scope has RETURN (affects control flow)
    has_return: bool = False
    # Map variable name to its array bounds (if any) for loop inference
    array_bounds_map: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    # Map variable name to its constant value for bound inference (constant propagation)
    const_value_map: Dict[str, int] = field(default_factory=dict)

    def next_branch_id(self, prefix: str = "B") -> str:
        """Generate unique branch ID."""
        self.branch_counter += 1
        return f"{prefix}_{self.branch_counter}"

    def next_temp(self) -> str:
        """Generate unique temporary variable name."""
        self.temp_counter += 1
        return f"_tmp{self.temp_counter}"


class ASTToZ3Transpiler:
    """
    Transpiler from IEC 61131-3 ST AST to Z3 Python logic.

    Converts parsed ST AST into executable Python code that:
    - Follows DSEEngine's execute_st_logic(engine, state) interface
    - Correctly handles IF/ELSIF/ELSE with engine.fork_if
    - Manages state.internal_mem and state.input_mem
    """

    def __init__(self, debug: bool = False, max_unwind: int = 10):
        self.debug = debug
        # Unified bounded unrolling for both FOR and WHILE loops
        self.max_unwind = max_unwind

    def transpile_from_st(self, st_code: str) -> str:
        """
        Transpile ST source code to Z3 Python logic.

        Args:
            st_code: ST source code as string

        Returns:
            Python code as string
        """
        cfg = ParserConfig(debug_print_parse_tree=self.debug)
        pous = parse_program(st_code, cfg)
        if not pous:
            raise ValueError("No POU found in ST code")
        # Handle multiple POUs - for now use the first one
        pou = pous[0]
        return self.transpile(pou)

    def transpile(self, pou: POU) -> str:
        """
        Transpile a POU to Z3 Python logic.

        Args:
            pou: POU AST node from parser

        Returns:
            Python code as string
        """
        ctx = Z3GenContext(pou)

        # Analyze variable declarations
        self._analyze_variables(ctx)

        # Generate code
        code_lines = [
            "import z3",
            "",
            "def execute_st_logic(engine, state):",
            '    """Generated Z3 logic for DSEEngine"""',
            ""
        ]

        # Generate variable initialization
        code_lines.extend(self._gen_initialization(ctx))

        # Generate input symbol registration
        code_lines.extend(self._gen_input_registration(ctx))

        # Generate statement bodies
        if ctx.pou.body:
            code_lines.append("    # === Statement Execution ===")
            stmt_code = self._gen_stmts(ctx.pou.body, ctx, indent="    ")
            code_lines.extend(stmt_code)

        return "\n".join(code_lines)

    def _analyze_variables(self, ctx: Z3GenContext):
        """Analyze variable declarations and categorize them."""
        # LarkParser returns POU with decls: List[VarSection]
        # Each VarSection has kind and decls (List[VarDecl])
        for var_section in ctx.pou.decls:
            section_kind = var_section.kind  # "VAR_INPUT", "VAR", etc.
            # DEBUG: print section kind
            if self.debug:
                import sys
                print(f"[DEBUG] Section kind: {repr(section_kind)}", file=sys.stderr)

            for var_decl in var_section.decls:
                if self.debug:
                    import sys
                    print(f"[DEBUG] var_decl type: {type(var_decl)}, isinstance VarDecl: {isinstance(var_decl, lark.ast.VarDecl)}", file=sys.stderr)
                if not isinstance(var_decl, lark.ast.VarDecl):
                    # Skip AtOverlayDecl and other types
                    continue

                var_name = var_decl.name
                var_type = var_decl.typ
                init_expr = var_decl.init

                # Get IEC type name from TypeSpec
                if self.debug:
                    import sys
                    print(f"[DEBUG] var_type: {var_type}, type: {type(var_type).__name__}", file=sys.stderr)
                iec_type = self._type_spec_to_string(var_type)

                # Check if this is an array and extract bounds
                array_bounds = None
                is_array = False
                if isinstance(var_type, lark.ast.TypeName) and var_type.array is not None:
                    is_array = True
                    lo, hi, _ = var_type.array  # (lower, upper, elem_type)
                    array_bounds = (lo, hi)
                    # Store in context for loop inference
                    ctx.array_bounds_map[var_name] = array_bounds

                # Convert init expression to string
                init_value = None
                if init_expr is not None:
                    init_value = self._expr_to_string(init_expr)
                    # Constant propagation: extract constant initial values
                    const_val = self._static_eval_int(init_expr)
                    if const_val is not None:
                        ctx.const_value_map[var_name] = const_val

                # Categorize variable
                if section_kind == "VAR_INPUT":
                    if self.debug:
                        import sys
                        print(f"[DEBUG] Adding input var: {var_name}, type: {iec_type}", file=sys.stderr)
                    ctx.input_vars.append(VarInfo(
                        name=var_name,
                        iec_type=iec_type,
                        is_input=True,
                        is_array=is_array,
                        init_value=init_value,
                        array_bounds=array_bounds
                    ))
                elif section_kind in ["VAR", "VAR_TEMP", "VAR_IN_OUT", "VAR_OUTPUT"]:
                    ctx.internal_vars.append(VarInfo(
                        name=var_name,
                        iec_type=iec_type,
                        is_internal=True,
                        is_array=is_array,
                        init_value=init_value,
                        array_bounds=array_bounds
                    ))

    def _type_spec_to_string(self, typ) -> str:
        """Convert TypeSpec to IEC type string."""
        if self.debug:
            import sys
            print(f"[DEBUG _type_spec_to_string] typ: {typ}, type: {type(typ).__name__}", file=sys.stderr)
            print(f"[DEBUG _type_spec_to_string] isinstance TypeName: {isinstance(typ, lark.ast.TypeName)}", file=sys.stderr)
        if isinstance(typ, lark.ast.TypeName):
            return typ.name.upper()
        elif isinstance(typ, lark.ast.EnumType):
            return "ENUM"
        elif isinstance(typ, lark.ast.FBInstanceType):
            return typ.fb_type
        else:
            return "ANY"

    def _get_type_name(self, typ) -> str:
        """Get type name from TypeSpec."""
        if isinstance(typ, lark.ast.TypeName):
            return typ.name.upper()
        elif isinstance(typ, lark.ast.EnumType):
            return "ENUM"
        else:
            return "ANY"

    def _expr_to_string(self, expr: Optional[Expr]) -> Optional[str]:
        """Convert expression to string representation."""
        if expr is None:
            return None

        if isinstance(expr, BoolLit):
            return "True" if expr.value else "False"
        elif isinstance(expr, IntLit):
            return str(expr.value)
        elif isinstance(expr, RealLit):
            return str(expr.value)
        elif isinstance(expr, StringLit):
            return expr.value
        elif isinstance(expr, TimeLit):
            return expr.value
        elif isinstance(expr, VarRef):
            return expr.name
        elif isinstance(expr, ArrayAccess):
            # Return string representation for array access
            index_str = self._expr_to_string(expr.index)
            return f"{expr.name}[{index_str}]"
        elif isinstance(expr, MemberAccess):
            # Return string representation for member access
            return ".".join(expr.parts)
        else:
            return None

    def _gen_initialization(self, ctx: Z3GenContext) -> List[str]:
        """Generate internal variable initialization code."""
        lines = []

        # Collect variables that need initialization
        init_vars = []
        for var in ctx.internal_vars:
            z3_init = self._z3_value(var.iec_type, var.init_value)
            if z3_init:
                init_vars.append((var.name, z3_init))

        # Only generate if block if there are variables to initialize
        if init_vars:
            lines.append("    # === Initialize Internal State (Cycle 1 only) ===")
            lines.append("    if state.cycle == 1:")
            for var_name, z3_init in init_vars:
                lines.append(f"        state.internal_mem['{var_name}'] = {z3_init}")
            lines.append("")

        return lines

    def _gen_input_registration(self, ctx: Z3GenContext) -> List[str]:
        """Generate input symbol registration code."""
        lines = [
            "    # === Register Current Cycle Inputs ===",
        ]

        for var in ctx.input_vars:
            z3_type = self._z3_type(var.iec_type)
            if z3_type:
                lines.append(f"    {var.name}_sym = {z3_type}(f'{var.name}_c{{state.cycle}}')")
                lines.append(f"    state.add_input_symbol('{var.name}', {var.name}_sym)")

        lines.append("")
        return lines

    def _gen_stmts(self, stmts: List[Stmt], ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for statement list.

        Args:
            stmts: List of statements to generate
            ctx: Generation context
            indent: Indentation string
            terminate_var: Optional variable name to track if execution should terminate (RETURN)
        """
        lines = []

        for i, stmt in enumerate(stmts):
            stmt_lines = self._gen_stmt(stmt, ctx, indent, terminate_var=terminate_var)
            lines.extend(stmt_lines)

        return lines

    def _gen_stmt(self, stmt: Stmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for single statement.

        Args:
            stmt: Statement to generate
            ctx: Generation context
            indent: Indentation string
            terminate_var: Optional variable to track execution termination
        """
        if isinstance(stmt, IfStmt):
            return self._gen_if(stmt, ctx, indent, terminate_var=terminate_var)
        elif isinstance(stmt, Assign):
            return self._gen_assign(stmt, ctx, indent, terminate_var=terminate_var)
        elif isinstance(stmt, CaseStmt):
            return self._gen_case(stmt, ctx, indent, terminate_var=terminate_var)
        elif isinstance(stmt, ForStmt):
            return self._gen_for(stmt, ctx, indent, terminate_var=terminate_var)
        elif isinstance(stmt, WhileStmt):
            return self._gen_while(stmt, ctx, indent, terminate_var=terminate_var)
        elif isinstance(stmt, RepeatStmt):
            return self._gen_repeat(stmt, ctx, indent)
        elif isinstance(stmt, CallStmt):
            return self._gen_call(stmt, ctx, indent, terminate_var=terminate_var)
        elif isinstance(stmt, ExitStmt):
            return [f"{indent}# EXIT - handled by loop generator", f"{indent}pass"]
        elif isinstance(stmt, ContinueStmt):
            return [f"{indent}# CONTINUE - skip to next iteration", f"{indent}pass"]
        elif isinstance(stmt, ReturnStmt):
            # RETURN should terminate execution - set terminate flag and skip rest
            lines = []
            if terminate_var:
                lines.append(f"{indent}# RETURN - terminate execution path")
                lines.append(f"{indent}{terminate_var} = z3.BoolVal(True)")
                lines.append(f"{indent}# Skip remaining statements in this scope")
            else:
                # Top-level RETURN - just mark
                lines.append(f"{indent}# RETURN - terminate execution")
                lines.append(f"{indent}pass")
            return lines
        else:
            # Unknown statement type - return comment only
            return [f"{indent}# Skipped unknown stmt: {type(stmt).__name__}"]

    def _gen_if(self, stmt: IfStmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for IF statement with proper RETURN handling.

        Args:
            stmt: IF statement to generate
            ctx: Generation context
            indent: Indentation string
            terminate_var: Optional variable to track if execution terminated in this IF
        """
        lines = []

        # Check if any arm contains RETURN
        has_return_in_first = self._contains_return(first_body) if (first_body := stmt.arms[0][1]) else False
        has_return_in_else = self._contains_return(stmt.else_block) if stmt.else_block else False

        # Generate condition expression for first arm
        first_cond, first_body = stmt.arms[0]
        cond_expr = self._gen_expr(first_cond, ctx)

        # Get branch IDs
        true_id = ctx.next_branch_id("IF")
        false_id = ctx.next_branch_id("ELSE")

        # Create termination flags for this IF if needed
        local_terminate = None
        if has_return_in_first or has_return_in_else:
            local_terminate = f"terminated_{true_id}"
            lines.append(f"{indent}# IF with potential RETURN")
            lines.append(f"{indent}{local_terminate} = z3.BoolVal(False)")

        lines.append(f"{indent}# IF {self._expr_string(first_cond)}")
        lines.append(f"{indent}cond_{true_id} = {cond_expr}")
        lines.append(f"{indent}s_{true_id}, s_{false_id} = engine.fork_if(")
        lines.append(f"{indent}    state, cond_{true_id}, '{true_id}', '{false_id}'")
        lines.append(f"{indent})")

        # Handle THEN block
        lines.append(f"{indent}if s_{true_id}:")
        lines.append(f"{indent}    # THEN block")
        then_stmts = self._gen_stmts(first_body, ctx, indent + "    ", terminate_var=local_terminate)
        lines.extend(then_stmts)

        # Check if there are more statements or ELSIF/ELSE
        has_more = len(stmt.arms) > 1 or stmt.else_block

        if has_more:
            # Process ELSIF arms
            current_state_var = f"s_{false_id}"  # Start with false branch of first IF

            for i, (cond, body) in enumerate(stmt.arms[1:], 1):
                elsif_id = ctx.next_branch_id("ELSIF")
                cond_expr = self._gen_expr(cond, ctx)

                # Check if this ELSIF body has RETURN
                has_return = self._contains_return(body)
                local_terminate_elsif = None
                if has_return:
                    local_terminate_elsif = f"terminated_{elsif_id}"
                    lines.append(f"{indent}if {current_state_var}:")
                    lines.append(f"{indent}    {local_terminate_elsif} = z3.BoolVal(False)")

                lines.append(f"{indent}if {current_state_var}:")
                lines.append(f"{indent}    # ELSIF {self._expr_string(cond)}")
                lines.extend([
                    f"{indent}    s_{elsif_id}_T, s_{elsif_id}_F = engine.fork_if(",
                    f"{indent}        {current_state_var}, {cond_expr}, '{elsif_id}_T', '{elsif_id}_F'",
                    f"{indent}    )",
                ])

                lines.append(f"{indent}    if s_{elsif_id}_T:")
                lines.append(f"{indent}        # ELSIF THEN block")

                elsif_indent = indent + "        "
                elsif_stmts = self._gen_stmts(body, ctx, elsif_indent, terminate_var=local_terminate_elsif)
                for line in elsif_stmts:
                    lines.append(f"{indent}    {line}")

                # Update current state to false branch for next iteration
                current_state_var = f"s_{elsif_id}_F"

            # Handle ELSE after all ELSIF arms
            if stmt.else_block:
                else_id = ctx.next_branch_id("ELSE")
                lines.append(f"{indent}if {current_state_var}:")
                lines.append(f"{indent}    # ELSE block")

                else_indent = indent + "    "
                else_stmts = self._gen_stmts(stmt.else_block, ctx, else_indent, terminate_var=local_terminate)
                for line in else_stmts:
                    lines.append(f"{indent}    {line}")

        # If parent needs to know about termination, combine all branch terminations
        if terminate_var and local_terminate:
            lines.append(f"{indent}# Combine termination status from all branches")
            lines.append(f"{indent}{terminate_var} = {local_terminate}")

        lines.append("")
        return lines

    def _contains_return(self, stmts: List[Stmt]) -> bool:
        """Check if statement list contains RETURN."""
        for stmt in stmts:
            if isinstance(stmt, ReturnStmt):
                return True
            if isinstance(stmt, IfStmt):
                for _, body in stmt.arms:
                    if self._contains_return(body):
                        return True
                if stmt.else_block and self._contains_return(stmt.else_block):
                    return True
        return False

    def _gen_case(self, stmt: CaseStmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for CASE statement.

        Lark CaseStmt: selector, arms: List[CaseArm], else_block

        Args:
            stmt: CASE statement to generate
            ctx: Generation context
            indent: Indentation string
            terminate_var: Optional variable to track execution termination
        """
        lines = []
        selector_expr = self._gen_expr(stmt.selector, ctx)
        case_id = ctx.next_branch_id("CASE")

        lines.append(f"{indent}# CASE {self._expr_string(stmt.selector)}")
        lines.append(f"{indent}selector = {selector_expr}")

        # Track the "unmatched" state that accumulates false branches
        # Start with None, will be set after first fork
        unmatched_state = None

        for i, arm in enumerate(stmt.arms):
            arm_id = ctx.next_branch_id("CASE_ARM")
            arm_states = []

            for j, (lo, hi) in enumerate(arm.labels):
                label_id = f"{arm_id}_L{j}"
                false_label = f"s_{label_id}_F"
                false_temp = f"s_{label_id}_F_tmp"

                # Determine the input state for this label
                if i == 0 and j == 0:
                    input_state = "state"
                    is_first_label = True
                else:
                    input_state = unmatched_state
                    is_first_label = False

                if hi is None:
                    # Single value: selector == value
                    value_str = self._case_value_to_string(lo)
                    lines.extend([
                        f"{indent}# Case {value_str}",
                    ])

                    if not is_first_label:
                        lines.append(f"{indent}if {input_state} is not None:")
                        extra_indent = "    "
                    else:
                        extra_indent = ""

                    lines.extend([
                        f"{indent}{extra_indent}s_{label_id}, {false_label} = engine.fork_if(",
                        f"{indent}{extra_indent}    {input_state}, selector == {value_str}, '{label_id}', '{false_label}'",
                        f"{indent}{extra_indent})",
                        f"{indent}{extra_indent}{false_temp} = {false_label}",
                    ])

                    if not is_first_label:
                        lines.extend([
                            f"{indent}else:",
                            f"{indent}    s_{label_id}, {false_label} = None, None",
                            f"{indent}    {false_temp} = None",
                        ])

                    arm_states.append(f"s_{label_id}")
                    unmatched_state = false_temp
                else:
                    # Range: lo..hi (two-step fork)
                    lo_str = self._case_value_to_string(lo)
                    hi_str = self._case_value_to_string(hi)
                    lo_false_label = f"s_{label_id}_LO_F"
                    hi_false_label = f"s_{label_id}_HI_F"
                    lo_false_temp = f"s_{label_id}_LO_F_tmp"
                    hi_false_temp = f"s_{label_id}_HI_F_tmp"

                    lines.extend([
                        f"{indent}# Case range {lo_str}..{hi_str}",
                    ])

                    if not is_first_label:
                        lines.append(f"{indent}if {input_state} is not None:")
                        extra_indent = "    "
                    else:
                        extra_indent = ""

                    lines.extend([
                        f"{indent}{extra_indent}s_{label_id}_LO, {lo_false_label} = engine.fork_if(",
                        f"{indent}{extra_indent}    {input_state}, selector >= {lo_str}, '{label_id}_LO', '{lo_false_label}'",
                        f"{indent}{extra_indent})",
                        f"{indent}{extra_indent}{lo_false_temp} = {lo_false_label}",
                    ])

                    if not is_first_label:
                        lines.extend([
                            f"{indent}else:",
                            f"{indent}    s_{label_id}_LO, {lo_false_label} = None, None",
                            f"{indent}    {lo_false_temp} = None",
                        ])

                    # Second fork for upper bound - check lo_false_temp
                    lines.append(f"{indent}if {lo_false_temp} is not None:")
                    lines.extend([
                        f"{indent}    s_{label_id}, {hi_false_label} = engine.fork_if(",
                        f"{indent}        {lo_false_temp}, selector <= {hi_str}, '{label_id}', '{hi_false_label}'",
                        f"{indent}    )",
                        f"{indent}    {hi_false_temp} = {hi_false_label}",
                    ])
                    lines.extend([
                        f"{indent}else:",
                        f"{indent}    s_{label_id}, {hi_false_label} = None, None",
                        f"{indent}    {hi_false_temp} = None",
                    ])

                    arm_states.append(f"s_{label_id}")
                    unmatched_state = hi_false_temp

            # Generate body for this arm (executed if ANY label matches)
            if arm_states:
                # If multiple labels, we need to combine their states
                if len(arm_states) == 1:
                    combined_state = arm_states[0]
                else:
                    # Combine with OR: state = s1 OR s2 OR s3
                    combined_state = f"s_{arm_id}_combined"
                    lines.append(f"{indent}# Combine states for arm {i}")
                    lines.append(f"{indent}{combined_state} = z3.Or({', '.join(arm_states)})")

                lines.append(f"{indent}# Arm {i} body")
                lines.append(f"{indent}if {combined_state}:")
                for body_stmt in arm.body:
                    body_lines = self._gen_stmt(body_stmt, ctx, indent + "    ", terminate_var=terminate_var)
                    lines.extend(body_lines)
                lines.append(f"{indent}    engine.end_cycle({combined_state})")

        # Handle ELSE clause
        if stmt.else_block and unmatched_state is not None:
            else_id = ctx.next_branch_id("CASE_ELSE")
            lines.append(f"{indent}# CASE ELSE")
            lines.append(f"{indent}if {unmatched_state}:")
            for body_stmt in stmt.else_block:
                body_lines = self._gen_stmt(body_stmt, ctx, indent + "    ", terminate_var=terminate_var)
                lines.extend(body_lines)
            lines.append(f"{indent}    engine.end_cycle({unmatched_state})")

        lines.append("")
        return lines

    def _gen_assign(self, stmt: Assign, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for assignment statement.

        Lark Assign.target is a string from lvalue parsing:
        - "variable"
        - "arr[i]"
        - "obj.field"
        - "arr[i].field"

        Args:
            stmt: Assignment statement
            ctx: Generation context
            indent: Indentation string
            terminate_var: Optional variable tracking if execution should terminate (unused - DSE paths are independent)
        """
        lines = []

        target = stmt.target
        expr_str = self._gen_expr(stmt.expr, ctx)

        # Note: terminate_var is ignored because in symbolic execution with forking,
        # each path is independent. RETURN in one branch doesn't affect other branches.

        # Parse the target to determine if it's array access, member access, or simple variable
        if "[" in target and "]" in target:
            # Array access: arr[i] or arr[i,j] or arr[i].field
            base_name = target.split("[")[0]
            # Extract index expression from target (e.g., "i" or "i, j" or "i, j]")
            index_part = target.split("[")[1].split("]")[0]

            lines.append(f"{indent}# Assignment: {target} := {self._expr_string(stmt.expr)}")
            lines.append(f"{indent}state.internal_mem['{base_name}'] = state.internal_mem.get('{base_name}', {{}})")

            # Handle multi-dimensional array indices (e.g., arr[i,j] or arr[i, j])
            if "," in index_part:
                # Multi-dimensional array: arr[i,j] or arr[i, j]
                indices = [idx.strip() for idx in index_part.split(",")]
                index_exprs = []
                for idx in indices:
                    if " " not in idx and idx.isidentifier():
                        # Simple variable name
                        if any(v.name == idx for v in ctx.internal_vars):
                            index_exprs.append(f"state.internal_mem['{idx}']")
                        elif any(v.name == idx for v in ctx.input_vars):
                            index_exprs.append(f"state.input_mem['{idx}']")
                        else:
                            index_exprs.append(f"state.internal_mem.get('{idx}', 0)")
                    else:
                        # Complex expression - convert ST operators and use
                        index_exprs.append(self._convert_st_operators_in_string(idx))
                index_str = ", ".join(index_exprs)
                lines.append(f"{indent}state.internal_mem['{base_name}'][{index_str}] = {expr_str}")
            elif " " not in index_part and index_part.isidentifier():
                # Single-dimensional array with simple variable
                # Check if it's an internal variable
                if any(v.name == index_part for v in ctx.internal_vars):
                    lines.append(f"{indent}state.internal_mem['{base_name}'][state.internal_mem['{index_part}']] = {expr_str}")
                elif any(v.name == index_part for v in ctx.input_vars):
                    lines.append(f"{indent}state.internal_mem['{base_name}'][state.input_mem['{index_part}']] = {expr_str}")
                else:
                    # Unknown variable, treat as internal
                    lines.append(f"{indent}state.internal_mem['{base_name}'][state.internal_mem.get('{index_part}', 0)] = {expr_str}")
            else:
                # Complex expression - convert ST operators and use
                converted_index = self._convert_st_operators_in_string(index_part)
                lines.append(f"{indent}# Complex array index, converted ST operators")
                lines.append(f"{indent}state.internal_mem['{base_name}'][{converted_index}] = {expr_str}")
        elif "." in target:
            # Member access: obj.field or arr[i].field or arr[i,j].field
            # Check if it's array+member access like garage[i,j].Occupied
            if "[" in target:
                # Parse array+member: garage[i,j].Occupied
                before_bracket = target.split("[")[0]
                after_bracket = target.split("]")[0]
                member_part = target.split("]")[1].split(".", 1)[1] if "." in target.split("]")[1] else None

                if member_part:
                    # Array access with member: garage[i,j].Occupied
                    index_part = after_bracket
                    base_name = before_bracket

                    lines.append(f"{indent}# Assignment: {target} := {self._expr_string(stmt.expr)}")
                    lines.append(f"{indent}state.internal_mem['{base_name}'] = state.internal_mem.get('{base_name}', {{}})")

                    # Handle multi-dimensional indices
                    if "," in index_part:
                        indices = [idx.strip() for idx in index_part.split(",")]
                        index_exprs = []
                        for idx in indices:
                            if " " not in idx and idx.isidentifier():
                                if any(v.name == idx for v in ctx.internal_vars):
                                    index_exprs.append(f"state.internal_mem['{idx}']")
                                elif any(v.name == idx for v in ctx.input_vars):
                                    index_exprs.append(f"state.input_mem['{idx}']")
                                else:
                                    index_exprs.append(f"state.internal_mem.get('{idx}', 0)")
                            else:
                                index_exprs.append(self._convert_st_operators_in_string(idx))

                        # Build nested dict access for assignment
                        # For garage[i,j].Occupied := value, we need:
                        # state.internal_mem['garage'][i][j]['Occupied'] = value
                        current_access = f"state.internal_mem['{base_name}']"
                        for k, idx_expr in enumerate(index_exprs):
                            if k < len(index_exprs) - 1:
                                lines.append(f"{indent}{current_access} = {current_access}.get({idx_expr}, {{}})")
                            else:
                                # Last index - this gives us the inner dict for the member
                                lines.append(f"{indent}if {current_access}.get({idx_expr}) is None:")
                                lines.append(f"{indent}    {current_access}[{idx_expr}] = {{}}")
                                lines.append(f"{indent}{current_access}[{idx_expr}]['{member_part}'] = {expr_str}")
                    else:
                        # Single dimension: arr[i].member
                        if " " not in index_part and index_part.isidentifier():
                            if any(v.name == index_part for v in ctx.internal_vars):
                                index_expr = f"state.internal_mem['{index_part}']"
                            elif any(v.name == index_part for v in ctx.input_vars):
                                index_expr = f"state.input_mem['{index_part}']"
                            else:
                                index_expr = f"state.internal_mem.get('{index_part}', 0)"
                        else:
                            index_expr = index_part

                        lines.append(f"{indent}# Single-dim array+member assignment")
                        lines.append(f"{indent}if {current_access}.get({index_expr}) is None:")
                        lines.append(f"{indent}    {current_access}[{index_expr}] = {{}}")
                        lines.append(f"{indent}{current_access}[{index_expr}]['{member_part}'] = {expr_str}")
                else:
                    # Just array access without member - shouldn't reach here
                    pass
            else:
                # Simple member access: obj.field
                parts = target.split(".")
                if len(parts) == 2:
                    obj, member = parts
                    lines.append(f"{indent}# Assignment: {target} := {self._expr_string(stmt.expr)}")
                    lines.append(f"{indent}state.internal_mem['{obj}_{member}'] = {expr_str}")
                else:
                    # Complex member access
                    compound = "_".join(parts)
                    lines.append(f"{indent}# Assignment: {target} := {self._expr_string(stmt.expr)}")
                    lines.append(f"{indent}state.internal_mem['{compound}'] = {expr_str}")
        else:
            # Simple variable assignment
            is_internal = any(v.name == target for v in ctx.internal_vars)
            is_input = any(v.name == target for v in ctx.input_vars)

            if is_internal:
                lines.append(f"{indent}# Assignment: {target} := {self._expr_string(stmt.expr)}")
                lines.append(f"{indent}state.internal_mem['{target}'] = {expr_str}")
            elif is_input:
                lines.append(f"{indent}# Assignment to input (readonly): {target} := {self._expr_string(stmt.expr)}")
                lines.append(f"{indent}# Input variables are read-only, skipping assignment")
            else:
                # Unknown variable - treat as internal
                lines.append(f"{indent}# Assignment: {target} := {self._expr_string(stmt.expr)}")
                lines.append(f"{indent}state.internal_mem['{target}'] = {expr_str}")

        return lines

    def _gen_for(self, stmt: ForStmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for FOR statement with loop unrolling and EXIT handling.

        Lark ForStmt: var, start, end, step (optional), body

        DSE approach: Unroll FOR loop into static paths.
        FOR i := 1 TO 3 DO ... END_FOR generates:
        - Path 1: i=1, execute body
        - Path 2: i=2, execute body
        - Path 3: i=3, execute body

        EXIT handling: When EXIT is encountered, set exit_flag and skip remaining iterations.
        """
        lines = []
        for_id = ctx.next_branch_id("FOR")

        lines.append(f"{indent}# FOR loop: {stmt.var} := {self._expr_string(stmt.start)} TO {self._expr_string(stmt.end)}")

        # Get step (default 1)
        step_expr = stmt.step if stmt.step else IntLit(1)
        step_str = self._expr_string(step_expr)

        if stmt.step:
            lines.append(f"{indent}# BY step: {step_str}")

        # Try to evaluate loop bounds statically with constant propagation
        start_val = self._static_eval_int_with_ctx(stmt.start, ctx)
        end_val = self._static_eval_int_with_ctx(stmt.end, ctx)
        step_val = self._static_eval_int_with_ctx(step_expr, ctx)

        # Create exit flag for this loop (use Python bool for control flow)
        exit_flag = f"exited_{for_id}"
        lines.append(f"{indent}{exit_flag} = False")

        if start_val is not None and end_val is not None and step_val is not None:
            # Static bounds - unroll completely
            # FOR loops have fixed bounds, so we can safely unroll all iterations
            lines.append(f"{indent}# Static loop unrolling: {start_val} TO {end_val} BY {step_val}")

            if step_val > 0:
                iteration_count = max(0, (end_val - start_val) // step_val + 1)
            elif step_val < 0:
                iteration_count = max(0, (start_val - end_val) // (-step_val) + 1)
            else:
                lines.append(f"{indent}# ERROR: step cannot be 0")
                return lines

            lines.append(f"{indent}# Fixed loop with {iteration_count} iterations - fully unrolling")

            # Generate path for each iteration
            for i in range(iteration_count):
                iter_val = start_val + i * step_val
                iter_id = ctx.next_branch_id(f"FOR_ITER")

                lines.append(f"{indent}# FOR iteration {i}: {stmt.var} = {iter_val}")

                # Only execute this iteration if we haven't exited yet
                if i == 0:
                    lines.append(f"{indent}state.internal_mem['{stmt.var}'] = z3.IntVal({iter_val})")
                else:
                    lines.append(f"{indent}if not {exit_flag}:")
                    lines.append(f"{indent}    state.internal_mem['{stmt.var}'] = z3.IntVal({iter_val})")

                # Generate loop body with EXIT tracking
                for body_stmt in stmt.body:
                    if isinstance(body_stmt, lark.ast.ExitStmt):
                        lines.append(f"{indent}# EXIT - setting exit flag")
                        lines.append(f"{indent}{exit_flag} = True")
                    else:
                        # Generate statement with exit checking
                        body_lines = self._gen_stmt(body_stmt, ctx, indent, terminate_var=None)
                        lines.extend(body_lines)

        else:
            # Dynamic bounds - try to infer bounds from array constraints
            # Get symbolic expressions for bounds
            start_expr = self._gen_expr(stmt.start, ctx)
            end_expr = self._gen_expr(stmt.end, ctx)
            step_expr_symbolic = self._gen_expr(step_expr, ctx) if step_expr else "z3.IntVal(1)"

            # Try to infer upper bound from array access patterns
            inferred_max = None
            end_var_name = None

            # Check if end expression is a simple variable reference
            if isinstance(stmt.end, VarRef):
                end_var_name = stmt.end.name

            # If end variable exists, check if it relates to any array bounds
            if end_var_name and end_var_name in ctx.array_bounds_map:
                # Direct case: FOR i := 1 TO array_var WHERE array_var has bounds
                array_lo, array_hi = ctx.array_bounds_map[end_var_name]
                inferred_max = array_hi
            else:
                # Check if loop body accesses arrays and infer bounds from them
                for var_info in ctx.internal_vars + ctx.input_vars:
                    if var_info.array_bounds and self._has_array_access_for_var(stmt.body, var_info.name):
                        array_lo, array_hi = var_info.array_bounds
                        # Use array upper bound as limit
                        if inferred_max is None or array_hi > inferred_max:
                            inferred_max = array_hi

            # Use inferred bound if available, otherwise use default max
            max_iterations = inferred_max + 1 if inferred_max is not None else self.max_unwind

            if inferred_max is not None:
                lines.append(f"{indent}# Inferred max iterations from array bounds: {max_iterations}")
            else:
                lines.append(f"{indent}# Using bounded unrolling: {max_iterations} iterations")

            # Determine step direction
            step_is_positive = (step_val is None or step_val > 0)
            step_is_negative = (step_val is not None and step_val < 0)

            if step_is_negative:
                # Reverse loop (BY negative step): FOR i := 3 TO 1 BY -1
                lines.append(f"{indent}# Reverse loop with dynamic bounds - symbolic execution with condition checks")
                lines.append(f"{indent}# Start: {start_expr}, End: {end_expr}, Step: {step_expr_symbolic}")

                for i in range(self.max_unwind):
                    iter_id = ctx.next_branch_id(f"FOR_ITER")
                    lines.append(f"{indent}# Iteration {i}")

                    # Check if we should continue this iteration
                    if i == 0:
                        # First iteration: always assign start value
                        lines.append(f"{indent}state.internal_mem['{stmt.var}'] = {start_expr}")
                    else:
                        # Subsequent iterations: check loop condition first
                        # For reverse loop: continue if loop_var >= end
                        loop_var_ref = f"state.internal_mem['{stmt.var}']"
                        cond_check = f"({loop_var_ref} >= {end_expr})"

                        check_cond = f"z3.And(z3.Not({exit_flag}), {cond_check})"
                        if terminate_var:
                            check_cond = f"z3.And({check_cond}, z3.Not({terminate_var}))"

                        lines.append(f"{indent}if {check_cond}:")
                        lines.append(f"{indent}    # Decrement loop variable by step")
                        lines.append(f"{indent}    state.internal_mem['{stmt.var}'] = ({loop_var_ref} - {step_expr_symbolic})")

                    # Execute loop body
                    for body_stmt in stmt.body:
                        if isinstance(body_stmt, lark.ast.ExitStmt):
                            lines.append(f"{indent}# EXIT - setting exit flag")
                            lines.append(f"{indent}{exit_flag} = z3.BoolVal(True)")
                        else:
                            body_lines = self._gen_stmt(body_stmt, ctx, indent, terminate_var=exit_flag)
                            lines.extend(body_lines)

            else:
                # Forward loop with dynamic bounds
                lines.append(f"{indent}# Forward loop with dynamic bounds - symbolic execution with condition checks")
                lines.append(f"{indent}# Start: {start_expr}, End: {end_expr}, Step: {step_expr_symbolic}")

                for i in range(self.max_unwind):
                    iter_id = ctx.next_branch_id(f"FOR_ITER")
                    lines.append(f"{indent}# Iteration {i}")

                    if i == 0:
                        # First iteration: assign start value
                        lines.append(f"{indent}state.internal_mem['{stmt.var}'] = {start_expr}")
                    else:
                        # Increment loop variable by step (without condition check)
                        loop_var_ref = f"state.internal_mem['{stmt.var}']"
                        lines.append(f"{indent}state.internal_mem['{stmt.var}'] = ({loop_var_ref} + {step_expr_symbolic})")

                    # Execute loop body
                    for body_stmt in stmt.body:
                        if isinstance(body_stmt, lark.ast.ExitStmt):
                            lines.append(f"{indent}# EXIT - setting exit flag")
                            lines.append(f"{indent}{exit_flag} = z3.BoolVal(True)")
                        else:
                            body_lines = self._gen_stmt(body_stmt, ctx, indent, terminate_var=exit_flag)
                            lines.extend(body_lines)

        lines.append("")
        return lines

    def _static_eval_int(self, expr: Expr) -> Optional[int]:
        """Try to evaluate an expression to an integer at compile time."""
        if isinstance(expr, IntLit):
            return expr.value
        elif isinstance(expr, BoolLit):
            return 1 if expr.value else 0
        elif isinstance(expr, UnOp):
            # Handle unary minus for negative step values: -1, -2, etc.
            x = self._static_eval_int(expr.x)
            if x is not None and expr.op == "-":
                return -x
        elif isinstance(expr, BinOp):
            a = self._static_eval_int(expr.a)
            b = self._static_eval_int(expr.b)
            if a is not None and b is not None:
                op = expr.op
                if op == "+":
                    return a + b
                elif op == "-":
                    return a - b
                elif op == "*":
                    return a * b
                elif op == "/":
                    return a // b if b != 0 else None
                elif op == "MOD":
                    return a % b if b != 0 else None
        return None

    def _static_eval_int_with_ctx(self, expr: Expr, ctx: Z3GenContext) -> Optional[int]:
        """Try to evaluate an expression to an integer at compile time with constant propagation."""
        if isinstance(expr, IntLit):
            return expr.value
        elif isinstance(expr, BoolLit):
            return 1 if expr.value else 0
        elif isinstance(expr, VarRef):
            # Check if this is a known constant from variable initialization
            return ctx.const_value_map.get(expr.name)
        elif isinstance(expr, UnOp):
            # Handle unary minus for negative step values: -1, -2, etc.
            x = self._static_eval_int_with_ctx(expr.x, ctx)
            if x is not None and expr.op == "-":
                return -x
        elif isinstance(expr, BinOp):
            a = self._static_eval_int_with_ctx(expr.a, ctx)
            b = self._static_eval_int_with_ctx(expr.b, ctx)
            if a is not None and b is not None:
                op = expr.op
                if op == "+":
                    return a + b
                elif op == "-":
                    return a - b
                elif op == "*":
                    return a * b
                elif op == "/":
                    return a // b if b != 0 else None
                elif op == "MOD":
                    return a % b if b != 0 else None
        return None

    def _try_eval_while_bound(self, cond: Expr, ctx: Z3GenContext) -> Optional[int]:
        """
        Try to statically evaluate WHILE loop bound.

        Examples:
        - WHILE bitCounter < 64 DO -> returns 64
        - WHILE runCount < 3 DO -> returns 3
        - WHILE gap >= 1 DO -> returns None (dynamic)
        """
        if isinstance(cond, BinOp):
            op = cond.op
            # Handle comparisons: <, <=, >, >=
            if op in ("<", "<=", ">", ">="):
                left = self._static_eval_int(cond.a)
                right = self._static_eval_int(cond.b)

                # WHILE counter < N
                if op == "<" and isinstance(cond.a, VarRef) and right is not None:
                    return right
                # WHILE counter <= N
                if op == "<=" and isinstance(cond.a, VarRef) and right is not None:
                    return right + 1
                # WHILE counter > N
                if op == ">" and isinstance(cond.a, VarRef) and right is not None:
                    return None  # Cannot determine upper bound
                # WHILE counter >= N
                if op == ">=" and isinstance(cond.a, VarRef) and right is not None:
                    return None  # Cannot determine upper bound

        return None  # Cannot determine statically

    def _gen_while(self, stmt: WhileStmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """
        Generate code for WHILE statement with bounded unrolling.

        WHILE loops need bounded unrolling because the condition may never become false.
        This is different from FOR loops which have fixed bounds.

        Args:
            stmt: WHILE statement
            ctx: Generation context
            indent: Indentation string
            terminate_var: Optional variable to track if execution should terminate
        """
        lines = []
        while_id = ctx.next_branch_id("WHILE")

        cond_expr = self._gen_expr(stmt.cond, ctx)

        # Try to statically evaluate the loop bound
        unwind = self._try_eval_while_bound(stmt.cond, ctx)
        if unwind is None:
            unwind = self.max_unwind

        lines.append(f"{indent}# WHILE loop: {self._expr_string(stmt.cond)}")
        lines.append(f"{indent}# Bounded unrolling: {unwind} iterations (potential infinite loop)")

        # Unroll the loop with conditional checks
        for i in range(unwind):
            iter_id = ctx.next_branch_id("WHILE_ITER")
            lines.append(f"{indent}# Iteration {i}")

            # Check loop condition with fork_if
            lines.append(f"{indent}cond_{iter_id} = {cond_expr}")
            lines.append(f"{indent}s_{iter_id}, s_exit_{iter_id} = engine.fork_if(")
            lines.append(f"{indent}    state, cond_{iter_id}, 'WHILE_{iter_id}_T', 'WHILE_{iter_id}_F'")
            lines.append(f"{indent})")

            # True branch: execute loop body
            lines.append(f"{indent}if s_{iter_id}:")
            for body_stmt in stmt.body:
                body_lines = self._gen_stmt(body_stmt, ctx, indent + "    ", terminate_var=terminate_var)
                lines.extend(body_lines)

            # False branch: exit loop (do nothing more in this iteration)

        lines.append("")
        return lines

    def _gen_repeat(self, stmt: RepeatStmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for REPEAT statement with bounded unrolling."""
        lines = []
        repeat_id = ctx.next_branch_id("REPEAT")

        lines.append(f"{indent}# REPEAT loop: UNTIL {self._expr_string(stmt.until)}")
        lines.append(f"{indent}# REPEAT unrolled once (body always executes at least once)")

        # REPEAT executes body at least once, then checks UNTIL condition
        # For bounded unrolling, we execute body default_unwind times
        for i in range(self.default_unwind):
            iter_id = ctx.next_branch_id("REPEAT_ITER")
            lines.append(f"{indent}# Iteration {i}")
            lines.append(f"{indent}if z3.Not({terminate_var}) if terminate_var else True:")

            for body_stmt in stmt.body:
                body_lines = self._gen_stmt(body_stmt, ctx, indent + "    ", terminate_var=terminate_var)
                lines.extend(body_lines)

            # Check UNTIL condition after each iteration (except last)
            if i < self.default_unwind - 1:
                until_expr = self._gen_expr(stmt.until, ctx)
                lines.append(f"{indent}# Check UNTIL condition: {until_expr}")
                lines.append(f"{indent}# If UNTIL is true, exit the loop")

        lines.append("")
        return lines

    def _gen_call(self, stmt: CallStmt, ctx: Z3GenContext, indent: str, terminate_var: Optional[str] = None) -> List[str]:
        """Generate code for function/FB call statement.

        For function calls that return values, they should be part of expressions.
        For FB calls, we need to handle the FB instance and its outputs.
        """
        lines = []
        call = stmt.call

        # Generate the call expression
        call_expr = self._gen_call_expr(call, ctx)

        lines.append(f"{indent}# Call: {call.name}")
        lines.append(f"{indent}# Function call result: {call_expr}")
        # Add pass to avoid empty block syntax error
        lines.append(f"{indent}pass")

        return lines

    def _hex_to_int(self, hex_str: str) -> int:
        """Convert IEC hex string (16#8A04) to integer."""
        hex_str = hex_str.strip().upper()
        if '#' in hex_str:
            # Format: 16#8A04 or 2#101 or 8#777
            base_part, value_part = hex_str.split('#')
            base_map = {'16': 16, '2': 2, '8': 8}
            base = base_map.get(base_part, 10)
            return int(value_part, base)
        return int(hex_str, 16) if hex_str.startswith('0X') else int(hex_str)

    def _convert_st_operators_in_string(self, expr_str: str) -> str:
        """Convert ST operators to Python/Z3 operators in a string expression.

        Used for array index expressions that come as strings from the parser.
        """
        # Replace ST operators with Python equivalents
        replacements = [
            (' MOD ', ' % '),
            (' DIV ', ' // '),
        ]
        result = expr_str
        for st_op, py_op in replacements:
            result = result.replace(st_op, py_op)
        return result

    def _gen_expr(self, expr: Expr, ctx: Z3GenContext) -> str:
        """Generate Z3 expression code."""
        if isinstance(expr, BoolLit):
            return "z3.BoolVal(" + ("True" if expr.value else "False") + ")"
        elif isinstance(expr, IntLit):
            return f"z3.IntVal({expr.value})"
        elif isinstance(expr, TypedHexLit):
            # Convert hex string (16#8A04) to integer value
            return f"z3.IntVal({self._hex_to_int(expr.value)})"
        elif isinstance(expr, RealLit):
            return f"z3.RealVal('{expr.value}')"
        elif isinstance(expr, VarRef):
            # Check if it's input or internal
            if any(v.name == expr.name for v in ctx.input_vars):
                return f"state.input_mem['{expr.name}']"
            else:
                return f"state.internal_mem['{expr.name}']"
        elif isinstance(expr, ArrayAccess):
            # Handle array access: arr[i] or arr[i,j]
            # indices is a list of expressions
            indices_str = ", ".join(self._gen_expr(idx, ctx) for idx in expr.indices)
            # Check if array is input or internal
            if any(v.name == expr.name for v in ctx.input_vars):
                # Use .get() to handle missing keys with default value
                return f"state.input_mem.get('{expr.name}', {{}}).get({indices_str}, z3.IntVal(0))"
            else:
                # Use .get() to handle missing keys with default value
                return f"state.internal_mem.get('{expr.name}', {{}}).get({indices_str}, z3.IntVal(0))"
        elif isinstance(expr, MemberAccess):
            # Handle member access: obj.field, timer.Q, arr[i].field
            parts = expr.parts
            if len(parts) == 2:
                obj_expr, member = parts[0], parts[1]
                # Check if obj_expr is an array access (contains '[')
                if "[" in obj_expr and "]" in obj_expr:
                    # Array access + member: garage[i,j].Occupied
                    # Parse array access: base_name[i,j]
                    base_name = obj_expr.split("[")[0]
                    index_part = obj_expr.split("[")[1].split("]")[0]
                    # Handle multi-dimensional indices
                    if "," in index_part:
                        indices = [idx.strip() for idx in index_part.split(",")]
                        index_exprs = []
                        for idx in indices:
                            if " " not in idx and idx.isidentifier():
                                if any(v.name == idx for v in ctx.internal_vars):
                                    index_exprs.append(f"state.internal_mem['{idx}']")
                                elif any(v.name == idx for v in ctx.input_vars):
                                    index_exprs.append(f"state.input_mem['{idx}']")
                                else:
                                    index_exprs.append(f"state.internal_mem.get('{idx}', 0)")
                            else:
                                index_exprs.append(self._convert_st_operators_in_string(idx))
                        index_str = ", ".join(index_exprs)
                        # For array+member access, use nested dict: arr[i][j].member
                        return f"state.internal_mem.get('{base_name}').get({index_str}, {{}}).get('{member}', z3.IntVal(0))"
                    else:
                        # Single dimension
                        if " " not in index_part and index_part.isidentifier():
                            if any(v.name == index_part for v in ctx.internal_vars):
                                index_expr = f"state.internal_mem['{index_part}']"
                            elif any(v.name == index_part for v in ctx.input_vars):
                                index_expr = f"state.input_mem['{index_part}']"
                            else:
                                index_expr = f"state.internal_mem.get('{index_part}', 0)"
                        else:
                            index_expr = index_part
                        return f"state.internal_mem.get('{base_name}').get({index_expr}, {{}}).get('{member}', z3.IntVal(0))"
                # Special handling for TON/TOF FB members
                elif member in ("Q", "IN", "PT", "ET"):
                    # TON timer members
                    return f"state.internal_mem.get('{obj_expr}_{member}', z3.BoolVal(False))"
                # General struct member access
                else:
                    return f"state.internal_mem.get('{obj_expr}_{member}', z3.IntVal(0))"
            else:
                # Nested member access
                compound = "_".join(parts)
                return f"state.internal_mem.get('{compound}', z3.IntVal(0))"
        elif isinstance(expr, BinOp):
            # Lark BinOp uses 'a' and 'b' fields
            a_str = self._gen_expr(expr.a, ctx)
            b_str = self._gen_expr(expr.b, ctx)
            op_str = self._z3_binop(expr.op)
            op = expr.op.upper()

            # Logical operators need function call syntax: z3.And(a, b)
            if op in ("AND", "OR", "XOR"):
                return f"{op_str}({a_str}, {b_str})"
            # Comparison and arithmetic operators can use infix syntax
            else:
                return f"({a_str} {op_str} {b_str})"
        elif isinstance(expr, UnOp):
            # Lark UnOp uses 'x' field
            x_str = self._gen_expr(expr.x, ctx)
            if expr.op == "NOT":
                return f"z3.Not({x_str})"
            elif expr.op == "-":
                return f"(-{x_str})"
            else:
                return f"({x_str})"
        elif isinstance(expr, CallExpr):
            # Handle standard function calls
            return self._gen_call_expr(expr, ctx)
        else:
            # Unknown expression type - return default int value to avoid syntax errors
            # No inline comment - it would cause syntax errors in complex expressions
            return f"z3.IntVal(0)"

    def _gen_call_expr(self, expr: CallExpr, ctx: Z3GenContext) -> str:
        """Generate Z3 expression for function call.

        Handles standard IEC 61131-3 functions:
        - SHR(IN, n): shift right by n bits
        - SHL(IN, n): shift left by n bits
        - ROR(IN, n): rotate right by n bits
        - ROL(IN, n): rotate left by n bits
        - ABS(IN): absolute value
        - SQRT(IN): square root
        - etc.
        """
        func_name = expr.name.upper()

        # Handle function parameters
        # ST uses named parameters: SHR(IN := value, n := 1)
        # expr.args is a list of (name, expr) tuples, name is None for positional args
        args = []
        for arg_tuple in expr.args:
            if isinstance(arg_tuple, tuple):
                # Unpack (name, expr) tuple
                _, arg_expr = arg_tuple
                args.append(self._gen_expr(arg_expr, ctx))
            else:
                # Direct expression (fallback)
                args.append(self._gen_expr(arg_tuple, ctx))

        if func_name == "SHR":
            # Shift right: SHR(IN, n) -> IN >> n
            if len(args) >= 2:
                return f"({args[0]} >> {args[1]})"
            elif len(args) == 1:
                return f"({args[0]} >> 1)"  # Default shift by 1
        elif func_name == "SHL":
            # Shift left: SHL(IN, n) -> IN << n
            if len(args) >= 2:
                return f"({args[0]} << {args[1]})"
            elif len(args) == 1:
                return f"({args[0]} << 1)"
        elif func_name == "ROR":
            # Rotate right - for Z3, we need to handle this specially
            # ROR(IN, n) = (IN >> n) | (IN << (32 - n)) for 32-bit values
            if len(args) >= 2:
                return f"(({args[0]} >> {args[1]}) | ({args[0]} << (32 - {args[1]})))"
        elif func_name == "ROL":
            # Rotate left
            if len(args) >= 2:
                return f"(({args[0]} << {args[1]}) | ({args[0]} >> (32 - {args[1]})))"
        elif func_name == "ABS":
            if len(args) >= 1:
                return f"z3.If({args[0]} >= 0, {args[0]}, -{args[0]})"
        elif func_name == "SQRT":
            # Z3 doesn't have sqrt for integers - return approximate value or input
            if len(args) >= 1:
                return f"{args[0]}"
        elif func_name in ("SIN", "COS", "TAN", "LN", "LOG", "EXP"):
            # Math functions - return first argument as approximation
            if args:
                return f"{args[0]}"
            else:
                return f"z3.IntVal(0)"
        elif func_name == "SEL":
            # SEL(G, IN0, IN1, ...): select based on G
            # Simplified: return first arg or default
            if len(args) >= 2:
                return f"z3.If({args[0]} >= 1, {args[1]}, {args[2] if len(args) > 2 else args[1]})"
            else:
                return f"z3.IntVal(0)"
        elif func_name == "MUX":
            # MUX(K, IN0, IN1, ...): multiplexer
            # Simplified: return based on K
            if len(args) >= 2:
                # Generate nested if for MUX
                result = args[1]  # Default to IN0
                for i in range(2, min(len(args), 10)):  # Limit to 10 inputs
                    result = f"z3.If({args[0]} == {i-1}, {args[i]}, {result})"
                return f"{result}"
            else:
                return f"z3.IntVal(0)"
        elif func_name in ("LIMIT", "MIN", "MAX"):
            # LIMIT(MN, IN, MX): clamp IN between MN and MX
            if func_name == "LIMIT" and len(args) >= 3:
                return f"z3.If({args[1]} < {args[0]}, {args[0]}, z3.If({args[1]} > {args[2]}, {args[2]}, {args[1]}))"
            elif func_name == "MIN" and len(args) >= 2:
                return f"z3.If({args[0]} < {args[1]}, {args[0]}, {args[1]})"
            elif func_name == "MAX" and len(args) >= 2:
                return f"z3.If({args[0]} > {args[1]}, {args[0]}, {args[1]})"
        elif func_name == "LEN":
            # LEN(string): returns length of string
            # Return a default max length (80 for IEC strings)
            if len(args) >= 1:
                return f"z3.IntVal(80)"
        elif func_name == "MID":
            # MID(string, start, length): extract substring
            if len(args) >= 2:
                return f"z3.IntVal(0)"
        elif func_name == "LEFT":
            # LEFT(string, length): extract leftmost characters
            if len(args) >= 2:
                return f"z3.IntVal(0)"
        elif func_name == "RIGHT":
            # RIGHT(string, length): extract rightmost characters
            if len(args) >= 2:
                return f"z3.IntVal(0)"
        elif func_name == "CONCAT":
            # CONCAT(str1, str2, ...): concatenate strings
            return f"z3.IntVal(0)"
        elif func_name == "FIND":
            # FIND(substring, string): find position of substring
            if len(args) >= 2:
                return f"z3.IntVal(0)"
        elif func_name == "DELETE":
            # DELETE(string, start, length): delete characters
            if len(args) >= 3:
                return f"z3.IntVal(0)"
        elif func_name == "INSERT":
            # INSERT(string, index, substring): insert substring
            if len(args) >= 3:
                return f"z3.IntVal(0)"
        elif func_name == "REPLACE":
            # REPLACE(string, old, new): replace occurrences
            if len(args) >= 3:
                return f"z3.IntVal(0)"

        # Type conversion functions
        elif func_name in ("BYTE_TO_INT", "INT_TO_DINT", "SINT_TO_INT", "USINT_TO_INT", "UINT_TO_DINT"):
            # Conversions to larger integer types - direct pass-through
            if args:
                return args[0]
            else:
                return f"z3.IntVal(0)"
        elif func_name in ("INT_TO_BYTE", "DINT_TO_INT", "INT_TO_SINT", "DINT_TO_UINT", "INT_TO_USINT"):
            # Conversions to smaller integer types - need truncation/masking
            if args:
                # Mask to lower 8 bits for BYTE, 16 bits for INT, etc.
                if "BYTE" in func_name or "SINT" in func_name or "USINT" in func_name:
                    return f"({args[0]} & 0xFF)"
                else:  # INT, UINT, etc.
                    return f"({args[0]} & 0xFFFF)"
            else:
                return f"z3.IntVal(0)"
        elif func_name in ("INT_TO_REAL", "DINT_TO_REAL", "SINT_TO_REAL"):
            # Integer to Real conversion
            if args:
                return f"z3.ToReal({args[0]})"
            else:
                return f"z3.RealVal('0.0')"
        elif func_name in ("REAL_TO_INT", "REAL_TO_DINT", "REAL_TO_SINT"):
            # Real to Integer conversion - truncate
            if args:
                return f"z3.ToInt({args[0]})"
            else:
                return f"z3.IntVal(0)"
        elif func_name in ("BOOL_TO_INT", "BOOL_TO_DINT"):
            # BOOL to Integer conversion
            if args:
                return f"z3.If({args[0]}, z3.IntVal(1), z3.IntVal(0))"
            else:
                return f"z3.IntVal(0)"
        elif func_name in ("INT_TO_BOOL", "DINT_TO_BOOL", "SINT_TO_BOOL"):
            # Integer to BOOL conversion - non-zero is TRUE
            if args:
                return f"({args[0]} != z3.IntVal(0))"
            else:
                return f"z3.BoolVal(False)"
        elif func_name in ("STRING_TO_INT", "STRING_TO_DINT"):
            # String to Integer - simplified, return 0
            if args:
                return f"z3.IntVal(0)"
            else:
                return f"z3.IntVal(0)"
        elif func_name in ("INT_TO_STRING", "DINT_TO_STRING", "REAL_TO_STRING"):
            # Integer/Real to String - simplified, return empty string representation
            if args:
                return f"z3.StringVal('')"
            else:
                return f"z3.StringVal('')"
        elif func_name in ("STRING_TO_BYTE", "BYTE_TO_STRING"):
            # String/BYTE conversion - simplified
            if args:
                return f"z3.IntVal(0)"
            else:
                return f"z3.IntVal(0)"
        elif func_name == "TRUNC":
            # TRUNC(real): truncate to integer
            if args:
                return f"z3.ToInt({args[0]})"
            else:
                return f"z3.IntVal(0)"
        elif func_name == "ROUND":
            # ROUND(real): round to nearest integer
            if args:
                # Simplified: use truncation for now
                return f"z3.ToInt({args[0]})"
            else:
                return f"z3.IntVal(0)"

        # Default: unknown function - return first arg or default
        if args:
            return f"{args[0]}"
        else:
            return f"z3.IntVal(0)"

    def _z3_binop(self, op: str) -> str:
        """Convert ST operator to Z3 operator.

        For logical operators, use z3.And/z3.Or instead of Python and/or
        because Z3 expressions cannot be evaluated in Python boolean context.
        """
        # Logical operators need special handling
        if op == "AND":
            return "z3.And"
        elif op == "OR":
            return "z3.Or"
        elif op == "XOR":
            return "^"  # XOR for Booleans, or implement as z3.Xor

        op_map = {
            "=": "==",
            "<>": "!=",
            "<": "<",
            ">": ">",
            "<=": "<=",
            ">=": ">=",
            "+": "+",
            "-": "-",
            "*": "*",
            "/": "/",
            "MOD": "%",
            ">>": ">>",
            "<<": "<<",
        }
        return op_map.get(op, op)

    def _has_array_access_for_var(self, stmts: List[Stmt], var_name: str) -> bool:
        """Check if an array variable is accessed in the given statements."""
        for stmt in stmts:
            if isinstance(stmt, Assign):
                # Check if lhs or rhs contains array access to var_name
                if self._contains_array_access(stmt.target, var_name):
                    return True
                if stmt.expr and self._contains_array_access(stmt.expr, var_name):
                    return True
            elif isinstance(stmt, IfStmt):
                # Check condition and both branches
                if self._contains_array_access(stmt.condition, var_name):
                    return True
                if self._has_array_access_for_var(stmt.then_body, var_name):
                    return True
                if self._has_array_access_for_var(stmt.else_body, var_name):
                    return True
                for elsif in stmt.elsif_blocks:
                    if self._contains_array_access(elsif.condition, var_name):
                        return True
                    if self._has_array_access_for_var(elsif.body, var_name):
                        return True
            elif isinstance(stmt, (ForStmt, WhileStmt, RepeatStmt)):
                if self._has_array_access_for_var(stmt.body, var_name):
                    return True
        return False

    def _contains_array_access(self, expr: Expr, var_name: str) -> bool:
        """Check if expression contains array access to var_name."""
        if isinstance(expr, ArrayAccess):
            return expr.name == var_name
        elif isinstance(expr, BinOp):
            return (self._contains_array_access(expr.a, var_name) or
                    self._contains_array_access(expr.b, var_name))
        elif isinstance(expr, UnOp):
            return self._contains_array_access(expr.x, var_name)
        return False

    def _z3_type(self, iec_type: str) -> Optional[str]:
        """Get Z3 type constructor for IEC type."""
        type_map = {
            "BOOL": "z3.Bool",
            "INT": "z3.Int",
            "DINT": "z3.Int",
            "SINT": "z3.Int",
            "UINT": "z3.Int",
            "UDINT": "z3.Int",
            "USINT": "z3.Int",
            "REAL": "z3.Real",
            "LREAL": "z3.Real",
            "STRING": "z3.String",
            "TIME": "z3.Int",  # Simplified
        }
        return type_map.get(iec_type.upper())

    def _z3_value(self, iec_type: str, value: Optional[str]) -> Optional[str]:
        """Get Z3 value constructor."""
        if value is None:
            # Default values per type
            default_map = {
                "BOOL": "z3.BoolVal(False)",
                "INT": "z3.IntVal(0)",
                "DINT": "z3.IntVal(0)",
                "REAL": "z3.RealVal('0.0')",
            }
            return default_map.get(iec_type.upper())

        z3_type = self._z3_type(iec_type)
        if z3_type:
            if iec_type.upper() == "BOOL":
                bool_val = "True" if value.lower() == "true" else "False"
                return f"z3.BoolVal({bool_val})"
            elif "INT" in iec_type.upper():
                return f"z3.IntVal({value})"
            elif "REAL" in iec_type.upper():
                return f"z3.RealVal('{value}')"
        return None

    def _expr_string(self, expr: Expr) -> str:
        """Get string representation of expression for comments."""
        if isinstance(expr, BoolLit):
            return "TRUE" if expr.value else "FALSE"
        elif isinstance(expr, IntLit):
            return str(expr.value)
        elif isinstance(expr, RealLit):
            return str(expr.value)
        elif isinstance(expr, VarRef):
            return expr.name
        elif isinstance(expr, ArrayAccess):
            indices_str = ", ".join(self._expr_string(idx) for idx in expr.indices)
            return f"{expr.name}[{indices_str}]"
        elif isinstance(expr, MemberAccess):
            return ".".join(expr.parts)
        elif isinstance(expr, BinOp):
            # Lark BinOp uses 'a' and 'b'
            a_str = self._expr_string(expr.a)
            b_str = self._expr_string(expr.b)
            return f"({a_str} {expr.op} {b_str})"
        elif isinstance(expr, UnOp):
            # Lark UnOp uses 'x'
            x_str = self._expr_string(expr.x)
            return f"{expr.op} {x_str}"
        else:
            return f"<{type(expr).__name__}>"

    def _case_value_to_string(self, value) -> str:
        """Convert CASE value to string."""
        if isinstance(value, int):
            return str(value)
        elif isinstance(value, str):
            return f'"{value}"'
        else:
            return str(value)


def transpile_st_file(
    st_path: Path,
    debug: bool = False,
    output_path: Optional[Path] = None
) -> str:
    """
    Transpile ST file to Z3 Python logic.

    Args:
        st_path: Path to ST source file
        debug: Enable debug output
        output_path: Optional path to save generated Z3 code

    Returns:
        Generated Python code as string
    """
    st_code = st_path.read_text(encoding="utf-8")

    # Use transpile_from_st directly
    transpiler = ASTToZ3Transpiler(debug=debug)
    result = transpiler.transpile_from_st(st_code)

    # Save to file if output_path specified
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result, encoding="utf-8")
        print(f"Z3 code saved to: {output_path}")

    return result


__all__ = [
    "ASTToZ3Transpiler",
    "transpile_st_file",
    "Z3GenContext",
    "VarInfo",
]
