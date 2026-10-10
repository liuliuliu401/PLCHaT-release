"""
Simple ST Parser for DSE

A lightweight IEC 61131-3 ST parser optimized for DSE transpilation.
Uses regex-based parsing to extract:
- Variable declarations (VAR_INPUT, VAR, VAR_TEMP)
- Control flow statements (IF, ELSIF, ELSE, CASE)
- Assignments
- Expressions

This avoids complex external dependencies while maintaining correctness
for common ST patterns used in PLC programs.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Union, Tuple
from enum import Enum


class TokenType(Enum):
    """Token types for ST lexical analysis."""
    # Keywords
    FUNCTION_BLOCK = "FUNCTION_BLOCK"
    FUNCTION = "FUNCTION"
    PROGRAM = "PROGRAM"
    END_FUNCTION_BLOCK = "END_FUNCTION_BLOCK"
    END_FUNCTION = "END_FUNCTION"
    END_PROGRAM = "END_PROGRAM"

    VAR_INPUT = "VAR_INPUT"
    VAR_OUTPUT = "VAR_OUTPUT"
    VAR_IN_OUT = "VAR_IN_OUT"
    VAR_TEMP = "VAR_TEMP"
    VAR = "VAR"
    VAR_CONSTANT = "VAR_CONSTANT"
    END_VAR = "END_VAR"

    IF = "IF"
    THEN = "THEN"
    ELSIF = "ELSIF"
    ELSE = "ELSE"
    END_IF = "END_IF"

    CASE = "CASE"
    OF = "OF"
    END_CASE = "END_CASE"

    FOR = "FOR"
    TO = "TO"
    BY = "BY"
    DO = "DO"
    END_FOR = "END_FOR"

    WHILE = "WHILE"
    END_WHILE = "END_WHILE"

    REPEAT = "REPEAT"
    UNTIL = "UNTIL"
    END_REPEAT = "END_REPEAT"

    # Operators
    ASSIGN = ":="
    AND = "AND"
    OR = "OR"
    XOR = "XOR"
    NOT = "NOT"
    EQ = "="
    NE = "<>"
    LT = "<"
    GT = ">"
    LE = "<="
    GE = ">="
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"
    MOD = "MOD"

    # Literals
    BOOL = "BOOL"
    INT = "INT"
    DINT = "DINT"
    REAL = "REAL"
    LREAL = "LREAL"
    STRING = "STRING"
    TIME = "TIME"
    TRUE = "TRUE"
    FALSE = "FALSE"

    # Other
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    STRING_LIT = "STRING"
    COLON = ":"
    SEMICOLON = ";"
    COMMA = ","
    DOT = "."
    LPAREN = "("
    RPAREN = ")"
    LBRACKET = "["
    RBRACKET = "]"
    ARRAY = "ARRAY"
    RANGE = ".."


# ========== AST Nodes ==========

@dataclass
class VarDecl:
    """Variable declaration."""
    name: str
    iec_type: str
    section: str  # VAR_INPUT, VAR_OUTPUT, VAR, VAR_TEMP, etc.
    init_value: Optional[str] = None
    is_array: bool = False
    array_lo: Optional[int] = None
    array_hi: Optional[int] = None


@dataclass
class Expr:
    """Base expression class."""
    pass


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class IntLit(Expr):
    value: int


@dataclass
class RealLit(Expr):
    value: float


@dataclass
class VarRef(Expr):
    name: str


@dataclass
class BinOp(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class UnOp(Expr):
    op: str
    expr: Expr


@dataclass
class Stmt:
    """Base statement class."""
    pass


@dataclass
class Assign(Stmt):
    target: str
    expr: Expr


@dataclass
class IfArm:
    """IF/ELSIF arm."""
    cond: Expr
    body: List[Stmt]


@dataclass
class IfStmt(Stmt):
    arms: List[IfArm]
    else_body: Optional[List[Stmt]]


@dataclass
class CaseArm:
    labels: List[Tuple[Union[int, str], Optional[Union[int, str]]]]
    body: List[Stmt]


@dataclass
class CaseStmt(Stmt):
    expr: Expr
    arms: List[CaseArm]
    else_body: Optional[List[Stmt]]


@dataclass
class POU:
    """Program Organization Unit."""
    kind: str  # FUNCTION_BLOCK, FUNCTION, PROGRAM
    name: str
    vars: List[VarDecl] = field(default_factory=list)
    body: List[Stmt] = field(default_factory=list)


# ========== Parser ==========

class SimpleSTParser:
    """
    Simple ST parser for DSE transpilation.

    Focuses on extracting information needed for symbolic execution:
    - Variable declarations (with types)
    - Control flow structure (IF, CASE)
    - Assignment statements

    Uses regex-based parsing for simplicity and robustness.
    """

    # Keywords regex (case-insensitive)
    KEYWORD_RE = re.compile(
        r'\b(FUNCTION_BLOCK|FUNCTION|PROGRAM|END_FUNCTION_BLOCK|END_FUNCTION|END_PROGRAM|'
        r'VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR|END_VAR|'
        r'IF|THEN|ELSIF|ELSE|END_IF|'
        r'CASE|OF|END_CASE|'
        r'FOR|TO|BY|DO|END_FOR|'
        r'WHILE|DO|END_WHILE|'
        r'REPEAT|UNTIL|END_REPEAT|'
        r'AND|OR|XOR|NOT|MOD|'
        r'TRUE|FALSE|'
        r'BOOL|INT|DINT|REAL|LREAL|STRING|TIME|ARRAY)\b',
        re.IGNORECASE
    )

    def __init__(self, debug: bool = False):
        self.debug = debug

    def parse(self, st_code: str) -> POU:
        """
        Parse ST code into POU AST.

        Args:
            st_code: ST source code

        Returns:
            POU AST node
        """
        # Preprocess: remove comments
        st_code = self._remove_comments(st_code)

        # Extract POU header
        pou_kind, pou_name = self._parse_pou_header(st_code)

        # Extract variable declarations
        var_decls = self._parse_var_declarations(st_code)

        # Extract statement body
        body = self._parse_statements(st_code)

        return POU(
            kind=pou_kind,
            name=pou_name,
            vars=var_decls,
            body=body
        )

    def _remove_comments(self, code: str) -> str:
        """Remove ST comments (* ... *) and // ..."""
        # Remove multi-line comments
        code = re.sub(r'\(\*.*?\*\)', '', code, flags=re.DOTALL)
        # Remove single-line comments
        code = re.sub(r'//.*', '', code)
        return code

    def _parse_pou_header(self, code: str) -> Tuple[str, str]:
        """Extract POU kind and name from header."""
        match = re.search(
            r'\b(FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+(\w+)',
            code,
            re.IGNORECASE
        )
        if match:
            return match.group(1).upper(), match.group(2)
        return "PROGRAM", "Unknown"

    def _parse_var_declarations(self, code: str) -> List[VarDecl]:
        """Parse variable declarations."""
        var_decls = []

        # Find VAR blocks
        var_blocks = re.finditer(
            r'(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR(?:\s+CONSTANT)?|VAR)\s*(.*?)\s*END_VAR',
            code,
            re.DOTALL | re.IGNORECASE
        )

        for match in var_blocks:
            section = match.group(1).upper().strip()
            if "CONSTANT" in section:
                section = "VAR_CONSTANT"

            block_content = match.group(2)

            # Parse variable declarations in this block
            for var_match in re.finditer(
                r'(\w+)\s*:\s*(?:ARRAY\s*\[(\d+)\.\.(\d+)\]\s*OF\s+)?(\w+)(?:\s*:=\s*([^;]+))?',
                block_content,
                re.IGNORECASE
            ):
                name = var_match.group(1)
                array_lo = var_match.group(2)
                array_hi = var_match.group(3)
                iec_type = var_match.group(4)
                init_value = var_match.group(5)

                var_decls.append(VarDecl(
                    name=name,
                    iec_type=iec_type.upper(),
                    section=section,
                    init_value=init_value.strip() if init_value else None,
                    is_array=array_lo is not None,
                    array_lo=int(array_lo) if array_lo else None,
                    array_hi=int(array_hi) if array_hi else None
                ))

        return var_decls

    def _parse_statements(self, code: str) -> List[Stmt]:
        """Parse statement body."""
        statements = []

        # Find statement body (after VAR blocks, before END_)
        # This is simplified - a real parser would use proper tokenization

        # Extract the body between last END_VAR and END_FUNCTION_BLOCK/PROGRAM
        body_match = re.search(
            r'(?:END_VAR.*?)(.*?)(?:END_FUNCTION_BLOCK|END_FUNCTION|END_PROGRAM)',
            code,
            re.DOTALL | re.IGNORECASE
        )

        if body_match:
            body_code = body_match.group(1)
            statements = self._parse_statement_list(body_code)

        return statements

    def _parse_statement_list(self, code: str) -> List[Stmt]:
        """Parse list of statements."""
        statements = []
        pos = 0
        code = code.strip()

        while pos < len(code):
            # Skip whitespace
            while pos < len(code) and code[pos].isspace():
                pos += 1

            if pos >= len(code):
                break

            # Try to parse IF statement
            if_match = re.match(r'\bIF\b', code[pos:], re.IGNORECASE)
            if if_match:
                stmt, new_pos = self._parse_if_stmt(code, pos)
                if stmt:
                    statements.append(stmt)
                    pos = new_pos
                    continue

            # Try to parse CASE statement
            case_match = re.match(r'\bCASE\b', code[pos:], re.IGNORECASE)
            if case_match:
                stmt, new_pos = self._parse_case_stmt(code, pos)
                if stmt:
                    statements.append(stmt)
                    pos = new_pos
                    continue

            # Try to parse assignment
            assign_match = re.match(
                r'(\w+)\s*:=\s*([^;]+);',
                code[pos:],
                re.IGNORECASE
            )
            if assign_match:
                target = assign_match.group(1)
                expr = self._parse_expr(assign_match.group(2))
                statements.append(Assign(target=target, expr=expr))
                pos += assign_match.end()
                continue

            # Try to skip END_IF
            endif_match = re.match(r'\bEND_IF\b\s*;', code[pos:], re.IGNORECASE)
            if endif_match:
                pos += endif_match.end()
                continue

            # Try to skip END_CASE
            endcase_match = re.match(r'\bEND_CASE\b\s*;', code[pos:], re.IGNORECASE)
            if endcase_match:
                pos += endcase_match.end()
                continue

            # If we can't parse, skip ahead
            pos += 1

        return statements

    def _parse_if_stmt(self, code: str, start_pos: int) -> Tuple[Optional[IfStmt], int]:
        """Parse IF statement including ELSIF and ELSE."""
        arms = []
        else_body = None
        pos = start_pos

        # Match entire IF statement from IF to END_IF
        # Pattern: IF cond THEN statements (ELSIF cond THEN statements)* (ELSE statements)? END_IF
        if_pattern = r'\bIF\b(.+?)\bTHEN\b(.*?)\bEND_IF\b\s*;?'
        if_match = re.search(if_pattern, code[pos:], re.IGNORECASE | re.DOTALL)

        if not if_match:
            return None, pos

        # Extract the IF body (everything between THEN and END_IF)
        if_body = if_match.group(2)
        pos += if_match.end()

        # First arm condition
        cond = self._parse_expr(if_match.group(1))

        # Now parse the IF body to find THEN block, ELSIF arms, and ELSE
        # Split by ELSIF to find parts
        elsif_parts = re.split(r'\bELSIF\b', if_body, flags=re.IGNORECASE)

        # First part contains THEN block (before first ELSIF or ELSE or END)
        first_part = elsif_parts[0]
        else_match = re.search(r'\bELSE\b(.*)', first_part, flags=re.IGNORECASE | re.DOTALL)
        if else_match:
            # No ELSIF, just IF-ELSE
            then_body_str = first_part[:else_match.start()]
            else_body_str = else_match.group(1)
            else_body = self._parse_statement_list(else_body_str) if else_body_str.strip() else None
        else:
            then_body_str = first_part
            else_body = None

        then_block = self._parse_statement_list(then_body_str)
        arms.append(IfArm(cond=cond, body=then_block))

        # Process ELSIF arms (if any)
        for i, elsif_part in enumerate(elsif_parts[1:], 1):
            # Split by ELSE to separate ELSIF body from potential ELSE
            else_split = re.split(r'\bELSE\b', elsif_part, maxsplit=1, flags=re.IGNORECASE)

            if len(else_split) == 2:
                elsif_body_str, remaining_else = else_split
                # This is the final ELSE
                if not else_body and remaining_else.strip():
                    else_body = self._parse_statement_list(remaining_else)
            else:
                elsif_body_str = else_split[0]

            # Parse ELSIF condition (everything before THEN)
            cond_then_match = re.match(r'(.+?)\bTHEN\b(.*)', elsif_body_str, re.IGNORECASE | re.DOTALL)
            if cond_then_match:
                elsif_cond = self._parse_expr(cond_then_match.group(1))
                elsif_then_str = cond_then_match.group(2)
                # Check if there's another ELSE in this ELSIF block
                inner_else = re.search(r'\bELSE\b(.*)', elsif_then_str, flags=re.IGNORECASE | re.DOTALL)
                if inner_else:
                    elsif_then_str = elsif_then_str[:inner_else.start()]
                    if not else_body and inner_else.group(1).strip():
                        else_body = self._parse_statement_list(inner_else.group(1))

                elsif_then_block = self._parse_statement_list(elsif_then_str)
                arms.append(IfArm(cond=elsif_cond, body=elsif_then_block))

        return IfStmt(arms=arms, else_body=else_body), pos

    def _parse_case_stmt(self, code: str, start_pos: int) -> Tuple[Optional[CaseStmt], int]:
        """Parse CASE statement."""
        arms = []
        else_body = None
        pos = start_pos

        # Match: CASE expr OF ... END_CASE
        case_match = re.match(
            r'\bCASE\b(.+?)\bOF\b(.*?)\bEND_CASE\b',
            code[pos:],
            re.IGNORECASE | re.DOTALL
        )

        if not case_match:
            return None, pos

        expr = self._parse_expr(case_match.group(1))
        body = case_match.group(2)

        # Parse case arms
        # Pattern: label1, label2, label3..5 : statements;
        arm_pattern = r'([^:]+?):(.*?)(?=\n\s*\w+\s*:|\n\s*ELSE\b|\n\s*END_CASE\b|$)'

        for arm_match in re.finditer(arm_pattern, body, re.DOTALL):
            labels_part = arm_match.group(1).strip()
            statements = self._parse_statement_list(arm_match.group(2))

            # Parse labels
            labels = []
            for label in re.split(r',', labels_part):
                label = label.strip()
                if not label:
                    continue

                # Check for range: lo..hi
                range_match = re.match(r'(\d+)\.\.(\d+)', label)
                if range_match:
                    lo = int(range_match.group(1))
                    hi = int(range_match.group(2))
                    labels.append((lo, hi))
                elif label.isdigit():
                    labels.append((int(label), None))
                else:
                    labels.append((label, None))

            if labels:
                arms.append(CaseArm(labels=labels, body=statements))

        # Parse ELSE
        else_match = re.search(r'\bELSE\b(.*?)$', body, re.IGNORECASE | re.DOTALL)
        if else_match:
            else_body = self._parse_statement_list(else_match.group(1))

        pos += case_match.end()
        return CaseStmt(expr=expr, arms=arms, else_body=else_body), pos

    def _parse_expr(self, expr_str: str) -> Expr:
        """Parse expression string into Expr AST."""
        expr_str = expr_str.strip()

        if not expr_str:
            return BoolLit(False)

        # Boolean literals
        if expr_str.upper() == "TRUE":
            return BoolLit(True)
        if expr_str.upper() == "FALSE":
            return BoolLit(False)

        # Integer literals
        if expr_str.isdigit() or (expr_str.startswith('-') and expr_str[1:].isdigit()):
            return IntLit(int(expr_str))

        # Float literals
        try:
            if '.' in expr_str or 'e' in expr_str.lower():
                return RealLit(float(expr_str))
        except ValueError:
            pass

        # Variable reference
        if re.match(r'^\w+$', expr_str):
            return VarRef(name=expr_str)

        # Binary operations (simplified)
        # Try to split by operators at correct precedence
        for op in ['AND', 'OR', 'XOR', '<>', '>=', '<=', '=', '<', '>', '+', '-', '*', '/', 'MOD']:
            pattern = r'\s+' + re.escape(op) + r'\s+'
            if re.search(pattern, expr_str, re.IGNORECASE):
                parts = re.split(pattern, expr_str, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) == 2:
                    left = self._parse_expr(parts[0])
                    right = self._parse_expr(parts[1])
                    return BinOp(op=op.upper(), left=left, right=right)

        # Parenthesized expression
        if expr_str.startswith('(') and expr_str.endswith(')'):
            return self._parse_expr(expr_str[1:-1])

        # Unary NOT
        if expr_str.upper().startswith('NOT '):
            expr = self._parse_expr(expr_str[4:].strip())
            return UnOp(op='NOT', expr=expr)

        # Default: treat as variable reference
        return VarRef(name=expr_str)


__all__ = [
    "SimpleSTParser",
    "POU",
    "VarDecl",
    "Expr",
    "Stmt",
    "IfStmt",
    "CaseStmt",
    "Assign",
    "IfArm",
    "CaseArm",
    "BoolLit",
    "IntLit",
    "RealLit",
    "VarRef",
    "BinOp",
    "UnOp",
]
