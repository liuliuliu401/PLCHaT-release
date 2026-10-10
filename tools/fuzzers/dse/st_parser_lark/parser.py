"""
Lark-based ST Parser for DSE

Copied and adapted from st_parser_legacy/lang/parser.py
Changes:
- Removed dependency on external Config class
- Added local ParserConfig
- Made module self-contained for DSE integration

Origin: st_parser_legacy/lang/parser.py
Date: 2026-06-03
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from lark import Lark, Tree, Token

from .grammar import GRAMMAR
from . import st_ast as ast


# ============ Local Configuration (replaces external Config) ============

@dataclass
class ParserConfig:
    """Parser configuration options"""
    debug_print_parse_tree: bool = False


# ============ Lark Parser Instance ============

# Use earley parser for better handling of CASE statement ambiguities
_parser = Lark(GRAMMAR, start="start", parser="earley")


# ============ Public API ============

def parse_program(text: str, cfg: Optional[ParserConfig] = None) -> List[ast.POU]:
    """
    Parse IEC 61131-3 Structured Text source code into AST.

    Args:
        text: ST source code to parse
        cfg: Optional ParserConfig for debug options

    Returns:
        List of POU (Program Organization Unit) nodes

    Original docstring from st_parser_legacy:
# Parse a piece of IEC 61131-3 Structured Text source code into an AST (list of POUs) according to the rules in grammar.py.
When the debug option is enabled, the source code with line numbers and the Lark syntax tree are printed simultaneously to facilitate locating syntax issues.
    """
    tree = _parser.parse(text)

    if cfg is not None and getattr(cfg, "debug_print_parse_tree", False):
        # Pretty-print source with line numbers
        print("--- Source (with line numbers) ---")
        for i, line in enumerate(text.splitlines(), start=1):
            print(f"{i:4}: {line}")
        print("--- End Source ---\n")

        # Pretty-print parse tree
        print("--- Lark parse tree (pretty) ---")
        try:
            print(tree.pretty())
        except Exception:
            print(tree)
        print("--- End parse tree ---\n")

    return _to_pous(tree)


# ============ Internal Conversion Functions ============

def _to_pous(tree: Tree) -> List[ast.POU]:
    """Convert start node to list of POUs"""
    assert tree.data == "start"
    pous: List[ast.POU] = []
    for child in tree.children:
        # Skip non-POU nodes like type_def, global_var_def
        if isinstance(child, Tree) and child.data in {"type_def", "global_var_def"}:
            continue
        # pou rule is inlined, but be defensive
        if isinstance(child, Tree) and child.data == "pou" and child.children:
            child = child.children[0]
        pous.append(_to_pou(child))
    return pous


def _to_pou(t: Tree) -> ast.POU:
    """Convert tree node to POU"""
    # Defensive: unwrap "pou" container if present
    if isinstance(t, Tree) and t.data == "pou" and t.children:
        t = t.children[0]

    if t.data == "function_block":
        kind = "FUNCTION_BLOCK"
        name = _tok(t.children[0])
        rest = t.children[1:]
        decls, body = _split_decls_body(rest)
        return ast.POU(kind=kind, name=name, decls=decls, body=body)

    if t.data == "function":
        kind = "FUNCTION"
        name = _tok(t.children[0])
        rtype = _to_type(t.children[1])
        rest = t.children[2:]
        decls, body = _split_decls_body(rest)
        return ast.POU(kind=kind, name=name, return_type=rtype, decls=decls, body=body)

    if t.data == "program":
        kind = "PROGRAM"
        name = _tok(t.children[0])
        rest = t.children[1:]
        decls, body = _split_decls_body(rest)
        return ast.POU(kind=kind, name=name, decls=decls, body=body)

    raise ValueError(f"Unexpected POU node: {t.data}")


def _split_decls_body(nodes) -> Tuple[List[ast.VarSection], List[ast.Stmt]]:
    """Split POU children into declarations and statements"""
    decls: List[ast.VarSection] = []
    body: List[ast.Stmt] = []
    for n in nodes:
        if isinstance(n, Tree) and n.data in {
            "var_input", "var_output", "var_inout", "var_temp", "var_plain", "var_constant"
        }:
            decls.append(_to_var_section(n))
        else:
            body.append(_to_stmt(n))
    return decls, body


def _to_var_section(t: Tree) -> ast.VarSection:
    """Convert var section tree to VarSection"""
    mapping = {
        "var_input": "VAR_INPUT",
        "var_output": "VAR_OUTPUT",
        "var_inout": "VAR_IN_OUT",
        "var_temp": "VAR_TEMP",
        "var_plain": "VAR",
        "var_constant": "VAR_CONSTANT",
    }
    kind = mapping[t.data]
    sec = ast.VarSection(kind=kind)

    for ch in t.children:
        if isinstance(ch, Tree) and ch.data == "var_decl":
            result = _to_var_decl(ch)
            if isinstance(result, list):
                sec.decls.extend(result)
            else:
                sec.decls.append(result)
        elif isinstance(ch, Tree) and ch.data == "at_overlay_decl":
            sec.decls.append(_to_at_overlay_decl(ch))
        else:
            # ignore END_VAR token not present in tree; lark doesn't include literals
            pass
    return sec


def _to_var_decl(t: Tree) -> Union[ast.VarDecl, List[ast.VarDecl]]:
    """Convert var_decl tree to VarDecl(s). Handles multi-variable declarations."""
    # Handle name_list: NAME ("," NAME)*
    name_list_node = t.children[0]
    typ = _to_type_spec(t.children[1])
    init = None
    if len(t.children) == 3:
        init = _to_expr(t.children[2])

    # Extract names from name_list
    if isinstance(name_list_node, Token):
        # Single name
        return ast.VarDecl(name=_tok(name_list_node), typ=typ, init=init)
    elif isinstance(name_list_node, Tree) and name_list_node.data == "name_list":
        # Multiple names: create separate VarDecl for each
        names = [_tok(ch) for ch in name_list_node.children]
        if len(names) == 1:
            return ast.VarDecl(name=names[0], typ=typ, init=init)
        # First variable gets the init, others get None
        return [ast.VarDecl(name=names[0], typ=typ, init=init)] + \
               [ast.VarDecl(name=n, typ=typ, init=None) for n in names[1:]]
    else:
        # Fallback: treat as single name
        name = _tok(name_list_node)
        return ast.VarDecl(name=name, typ=typ, init=init)


def _to_at_overlay_decl(t: Tree) -> ast.AtOverlayDecl:
    """Convert at_overlay_decl tree to AtOverlayDecl"""
    name = _tok(t.children[0])
    typ = _to_type_spec(t.children[1])
    target_node = t.children[2]
    if isinstance(target_node, Tree) and target_node.data == "overlay_target":
        parts = []
        for c in target_node.children:
            if isinstance(c, Token):
                parts.append(str(c))
            elif isinstance(c, int):
                parts.append(str(c))
            else:
                parts.append(str(c))
        target = ".".join(parts) if len(parts) > 1 else parts[0]
    else:
        target = _tok(target_node)
    return ast.AtOverlayDecl(name=name, typ=typ, target=target)


def _to_type_spec(t: Tree) -> ast.TypeSpec:
    """
    Parse type specification (named type, enum type, array type, or FB instance).

    Handles:
    - Named types (BOOL, INT, etc.)
    - Inline enum types: (A, B, C)
    - Array types: ARRAY [lo..hi] OF type
    - IEC FB instance types (TON, TOF, etc.)
    """
    if t.data == "type_named":
        return _to_type(t)
    elif t.data in {"enum_type", "type_enum_inline"}:
        values = [_tok(ch) for ch in t.children]
        return ast.EnumType(values=values)
    elif t.data == "array_type":
        # grammar: ARRAY [array_range (, array_range)*] OF type_spec
        ranges: List[Tuple[int, int]] = []
        elem_type: Optional[ast.TypeSpec] = None

        for ch in t.children:
            if isinstance(ch, Tree) and ch.data == "array_range":
                lo_node = ch.children[0]
                hi_node = ch.children[1]
                lo_expr = _to_expr(lo_node)
                hi_expr = _to_expr(hi_node)
                if not isinstance(lo_expr, ast.IntLit) or not isinstance(hi_expr, ast.IntLit):
                    raise ValueError("Array range bounds must be integer literals")
                ranges.append((lo_expr.value, hi_expr.value))
            elif isinstance(ch, Tree):
                # final child is the element type spec
                elem_type = _to_type_spec(ch)

        if elem_type is None:
            raise ValueError(f"array_type missing element type: {t}")

        # Fold multidimensional arrays from inside out.
        typ: ast.TypeSpec = elem_type
        for lo, hi in reversed(ranges):
            typ = ast.TypeName(name="ARRAY", array=(lo, hi, typ))
        return typ
    else:
        raise ValueError(f"Unexpected type spec node: {t.data}")


def _to_type(t: Tree) -> ast.TypeSpec:
    """
    Parse named type, auto-detecting IEC standard FB types.

    Recognizes IEC FB types (TON, TOF, TP, SR, RS, R_TRIG, F_TRIG, CTU, CTD, CTUD)
    and returns FBInstanceType instead of TypeName.
    """
    assert t.data == "type_named"
    base = _tok(t.children[0])

    # Check for IEC standard FB types
    if base.upper() in ast.IEC_FB_TYPES and len(t.children) == 1:
        return ast.FBInstanceType(fb_type=base.upper())

    if len(t.children) == 1:
        return ast.TypeName(name=base)
    # array_suffix
    suf = t.children[1]
    assert isinstance(suf, Tree) and suf.data == "array_suffix"
    lo = int(_tok(suf.children[0]))
    hi = int(_tok(suf.children[1]))
    elem = _to_type_spec(suf.children[2])
    return ast.TypeName(name=base, array=(lo, hi, elem))


def _to_stmt(t: Tree) -> ast.Stmt:
    """Convert statement tree to Stmt node"""
    if isinstance(t, Tree):
        if t.data == "stmt_assign":
            a = t.children[0]
            assert isinstance(a, Tree) and a.data == "assign"
            return _to_assign(a)
        if t.data == "stmt_call":
            c = t.children[0]
            assert isinstance(c, Tree) and c.data == "call"
            return ast.CallStmt(call=_to_call_expr(c))
        if t.data == "if_stmt":
            return _to_if(t)
        if t.data == "case_stmt":
            return _to_case(t)
        if t.data == "for_stmt":
            return _to_for(t)
        if t.data == "while_stmt":
            return _to_while(t)
        if t.data == "repeat_stmt":
            return _to_repeat(t)
        if t.data == "stmt_exit":
            return ast.ExitStmt()
        if t.data == "stmt_continue":
            return ast.ContinueStmt()
        if t.data == "stmt_return":
            return ast.ReturnStmt()

    raise ValueError(f"Unexpected stmt node: {t}")


def _to_assign(t: Tree) -> ast.Assign:
    """Convert assign tree to Assign"""
    target = _to_lvalue(t.children[0])
    expr = _to_expr(t.children[1])
    return ast.Assign(target=target, expr=expr)


def _to_lvalue(t: Tree) -> str:
    """
    Convert lvalue tree to string representation.

    Handles:
    - Simple variables: name
    - Array access: arr[index]
    - Member access: obj.field
    - Complex combinations: arr[i].field
    """
    assert t.data == "lvalue"

    def render_index(ix_tree: Tree) -> str:
        # ix_tree: index_suffix: "[" expr ("," expr)* "]"
        assert ix_tree.data == "index_suffix"
        indices = [_to_expr(ch) for ch in ix_tree.children]
        return "[" + ", ".join(_expr_to_text(ix) for ix in indices) + "]"

    def render_segment(seg_children) -> str:
        # segment starts with NAME then zero+ index_suffix
        name = _tok(seg_children[0])
        s = name
        for ch in seg_children[1:]:
            if isinstance(ch, Tree) and ch.data == "index_suffix":
                s += render_index(ch)
            else:
                # ignore
                pass
        return s

    # lvalue children pattern from grammar:
    # NAME index_suffix* ("." (NAME|INT) index_suffix*)*
    # Lark flattens: NAME, index_suffix*, NAME|INT, index_suffix*, ... without DOT tokens.
    # We split whenever we see a Token NAME after having started a segment.

    segments = []
    cur = [t.children[0]]
    for ch in t.children[1:]:
        if isinstance(ch, Token) and ch.type in {"NAME", "INT"}:
            segments.append(render_segment(cur))
            cur = [ch]
        else:
            cur.append(ch)
    segments.append(render_segment(cur))

    return ".".join(segments)


def _expr_to_text(e: ast.Expr) -> str:
    """
    Minimal expression printer for use in lvalue indexes.
    Returns string representation of expression.
    """
    if isinstance(e, ast.IntLit):
        return str(e.value)
    if isinstance(e, ast.RealLit):
        return str(e.value)
    if isinstance(e, ast.VarRef):
        return e.name
    if isinstance(e, ast.AbsRef):
        return e.value
    if isinstance(e, ast.MemberAccess):
        return ".".join(e.parts)
    if isinstance(e, ast.ArrayAccess):
        indices = ", ".join(_expr_to_text(ix) for ix in e.indices)
        result = f"{e.name}[{indices}]"
        if e.member:
            result += f".{e.member}"
        return result
    if isinstance(e, ast.StringLit):
        return e.value
    if isinstance(e, ast.BoolLit):
        return "TRUE" if e.value else "FALSE"
    if isinstance(e, ast.TimeLit):
        return e.value
    if isinstance(e, ast.TypedHexLit):
        return e.value
    if isinstance(e, ast.BinOp):
        return f"({_expr_to_text(e.a)} {e.op} {_expr_to_text(e.b)})"
    if isinstance(e, ast.UnOp):
        return f"{e.op}({_expr_to_text(e.x)})"
    if isinstance(e, ast.CallExpr):
        parts = []
        for k, v in e.args:
            parts.append(_expr_to_text(v) if k is None else f"{k} := {_expr_to_text(v)}")
        return f"{e.name}({', '.join(parts)})"
    return str(e)


def _to_call_expr(t: Tree) -> ast.CallExpr:
    """Convert call tree to CallExpr"""
    assert t.data == "call"
    name = _tok(t.children[0])
    args: List[Tuple[Optional[str], ast.Expr]] = []
    if len(t.children) >= 2:
        arg_list = t.children[1]
        if isinstance(arg_list, Tree) and arg_list.data == "arg_list":
            for arg in arg_list.children:
                args.append(_to_arg(arg))
    return ast.CallExpr(name=name, args=args)


def _to_arg(t: Tree) -> Tuple[Optional[str], ast.Expr]:
    """Convert arg tree to (keyword, expr) tuple"""
    assert t.data in {"arg_named", "arg_pos"}
    if t.data == "arg_named":
        kw = _tok(t.children[0])
        ex = _to_expr(t.children[1])
        return (kw, ex)
    ex = _to_expr(t.children[0])
    return (None, ex)


def _to_if(t: Tree) -> ast.IfStmt:
    """
    Convert if_stmt tree to IfStmt.

    Grammar shape (explicit arm nodes):
    IF expr THEN stmt* if_elsif_arm* if_else_arm? END_IF ;
    """
    assert len(t.children) >= 1

    cond0 = _to_expr(t.children[0])
    then_block: List[ast.Stmt] = []
    arms: List[Tuple[ast.Expr, List[ast.Stmt]]] = []
    else_block: Optional[List[ast.Stmt]] = None

    idx = 1
    while idx < len(t.children):
        ch = t.children[idx]
        if isinstance(ch, Tree) and ch.data in {"if_elsif_arm", "if_else_arm"}:
            break
        then_block.append(_to_stmt(ch))
        idx += 1

    arms.append((cond0, then_block))

    while idx < len(t.children):
        ch = t.children[idx]
        if isinstance(ch, Tree) and ch.data == "if_elsif_arm":
            cond = _to_expr(ch.children[0])
            blk = [_to_stmt(s) for s in ch.children[1:]]
            arms.append((cond, blk))
        elif isinstance(ch, Tree) and ch.data == "if_else_arm":
            blk = [_to_stmt(s) for s in ch.children]
            else_block = blk if blk else None
        else:
            raise ValueError(f"Unexpected child in if_stmt: {ch}")
        idx += 1

    return ast.IfStmt(arms=arms, else_block=else_block)


def _to_case(t: Tree) -> ast.CaseStmt:
    """
    Convert case_stmt tree to CaseStmt.

    Handles both:
    - CASE expr OF case_arm+ END_CASE
    - CASE expr OF case_arm+ ELSE stmt* END_CASE
    """
    selector = _to_expr(t.children[0])
    arms: List[ast.CaseArm] = []
    else_block: Optional[List[ast.Stmt]] = None

    # Remaining children include case_arm trees and possibly ELSE stmts as plain stmt nodes.
    for ch in t.children[1:]:
        if isinstance(ch, Tree) and ch.data == "case_arm":
            arms.append(_to_case_arm(ch))
        elif ch.data in {"stmt_assign","stmt_call","if_stmt","case_stmt","for_stmt","while_stmt","repeat_stmt","stmt_exit","stmt_continue","stmt_return"}:
            # else stmt (flattened by grammar)
            else_block = else_block or []
            else_block.append(_to_stmt(ch))
    return ast.CaseStmt(selector=selector, arms=arms, else_block=else_block)


def _to_case_value(t: Tree):
    """
    Parse case_value: either INT or NAME (enum value).

    Attempts to parse as integer, falls back to string for enum values.
    """
    assert t.data == "case_value"
    tok = t.children[0]
    tok_str = _tok(tok)
    # Try to parse as integer, fail -> enum name
    try:
        return int(tok_str)
    except ValueError:
        return tok_str


def _to_case_arm(t: Tree) -> ast.CaseArm:
    """
    Convert case_arm tree to CaseArm.

    Handles:
    - Single values: 1, 2, 3
    - Ranges: 2..5
    - Enum values: RED, GREEN, BLUE
    """
    labels_node = t.children[0]
    assert isinstance(labels_node, Tree) and labels_node.data == "case_labels"
    labels = []
    for cl in labels_node.children:
        assert isinstance(cl, Tree) and cl.data == "case_label"
        lo = _to_case_value(cl.children[0])
        hi = _to_case_value(cl.children[1]) if len(cl.children) == 2 else None
        labels.append((lo, hi))
    body: List[ast.Stmt] = []
    for ch in t.children[1:]:
        body.append(_to_stmt(ch))
    return ast.CaseArm(labels=labels, body=body)


def _to_for(t: Tree) -> ast.ForStmt:
    """
    Convert for_stmt tree to ForStmt.

    Grammar supports:
    - FOR var := start TO end DO stmt* END_FOR
    - FOR var := start TO end BY step DO stmt* END_FOR
    """
    var = _tok(t.children[0])
    start = _to_expr(t.children[1])
    end = _to_expr(t.children[2])
    idx = 3
    step = None
    # Detect BY clause
    if idx < len(t.children) and isinstance(t.children[idx], Tree) and t.children[idx].data not in {"stmt_assign","stmt_call","if_stmt","case_stmt","for_stmt","while_stmt","repeat_stmt","stmt_exit","stmt_continue","stmt_return"}:
        step = _to_expr(t.children[idx])
        idx += 1
    body = [_to_stmt(ch) for ch in t.children[idx:]]
    return ast.ForStmt(var=var, start=start, end=end, step=step, body=body)


def _to_while(t: Tree) -> ast.WhileStmt:
    """Convert while_stmt tree to WhileStmt"""
    cond = _to_expr(t.children[0])
    body = [_to_stmt(ch) for ch in t.children[1:]]
    return ast.WhileStmt(cond=cond, body=body)


def _to_repeat(t: Tree) -> ast.RepeatStmt:
    """
    Convert repeat_stmt tree to RepeatStmt.

    Grammar: REPEAT stmt* UNTIL expr END_REPEAT
    """
    until = _to_expr(t.children[-1])
    body = [_to_stmt(ch) for ch in t.children[:-1]]
    return ast.RepeatStmt(body=body, until=until)


def _to_expr(t) -> ast.Expr:
    """
    Convert expression tree to Expr node.

    Handles all expression types:
    - Literals: int, real, bool, string, time
    - Variables: var_ref
    - Arrays: array_access
    - Members: member_access
    - Unary: NOT, -
    - Binary: all operators
    - Calls: call_expr
    """
    if isinstance(t, Token):
        # Handle bare tokens - usually variable names or literals
        tok_str = str(t)
        tok_type = t.type if hasattr(t, 'type') else None

        # Check for boolean literals
        if tok_str.upper() in ("TRUE", "FALSE"):
            return ast.BoolLit(tok_str.upper() == "TRUE")

        # Check for integers
        if tok_type == "INT" or tok_str.isdigit():
            return ast.IntLit(int(tok_str))

        # Check for reals
        if tok_type == "REAL":
            return ast.RealLit(float(tok_str))

        # Check for time literals
        if tok_type == "TIME_LIT" or tok_str.upper().startswith("T#"):
            return ast.TimeLit(tok_str)

        # Default to variable reference
        return ast.VarRef(tok_str)

    if isinstance(t, Tree):
        d = t.data
        # literals
        if d == "int_lit":
            return ast.IntLit(int(_tok(t.children[0])))
        if d == "real_lit":
            return ast.RealLit(float(_tok(t.children[0])))
        if d == "bool_lit":
            return ast.BoolLit(_tok(t.children[0]).upper() == "TRUE")
        if d == "string_lit":
            return ast.StringLit(_tok(t.children[0]))
        if d == "time_lit":
            return ast.TimeLit(_tok(t.children[0]))
        if d == "typed_hex_lit":
            return ast.TypedHexLit(_tok(t.children[0]))
        if d == "array_init":
            # Array initialization like [31, 28, 31]
            values = [_to_expr(ch) for ch in t.children]
            return ast.ArrayInit(values=values)
        if d == "abs_ref":
            tok = _tok(t.children[0])
            kind = "db" if tok.startswith("DB") else "io"
            return ast.AbsRef(value=tok, kind=kind)
        if d == "var_ref":
            return ast.VarRef(_tok(t.children[0]))
        if d == "absname_ref":
            # treat as AbsRef in expr context
            v = _tok(t.children[0])
            return ast.AbsRef(value=v, kind="io")
        if d == "member_access":
            # Member access like HeartbeatTimer.Q
            parts = [_tok(ch) for ch in t.children]
            return ast.MemberAccess(parts=parts)
        if d == "array_access":
            # Array access like arr[i] or arr[i,j] or arr[i,j].Occupied
            name = _tok(t.children[0])

            # Collect index expression until encountering a dot or end
            indices = []
            member = None
            i = 1
            while i < len(t.children):
                ch = t.children[i]
                if isinstance(ch, Token) and ch.type == "DOT":
                    # member name after the dot
                    if i + 1 < len(t.children):
                        member = _tok(t.children[i + 1])
                    break
                elif isinstance(ch, Token) and ch.type in {"NAME", "INT"}:
                    # This could be member access (without DOT marker)
                    member = _tok(ch)
                    break
                else:
                    # expression (index)
                    indices.append(_to_expr(ch))
                    i += 1

            return ast.ArrayAccess(name=name, indices=indices, member=member)
        if d == "call_expr":
            return _to_call_expr(t.children[0])

        # unary
        if d == "unary" and len(t.children) == 2:
            op = _tok(t.children[0]).upper()
            return ast.UnOp(op=op, x=_to_expr(t.children[1]))

        # generic left-associative binary folding
        if d in {"or_expr","and_expr","rel_expr","add_expr","mul_expr"}:
            return _fold_binops(t.children, d)

        # parenthesized expr collapses naturally
        if len(t.children) == 1:
            return _to_expr(t.children[0])

    raise ValueError(f"Unhandled expr node: {t}")


def _fold_binops(children, expr_type: str = "") -> ast.Expr:
    """
    Fold a list of children into a left-associative binary expression.

    Handles both:
    - With explicit operators: term, op, term, op, term
    - Without operators (inlined): term, term, term (infer from expr_type)
    """
    # Map expression type to default operator
    default_ops = {
        "and_expr": "AND",
        "or_expr": "OR",
        "add_expr": "+",
        "mul_expr": "*",
        "rel_expr": "=",
    }
    default_op = default_ops.get(expr_type, "AND")

    if len(children) == 0:
        raise ValueError("Empty children list in _fold_binops")

    if len(children) == 1:
        return _to_expr(children[0])

    # Check if operators are present
    if len(children) % 2 == 0:
        # Operators missing - all children are operands
        expr = _to_expr(children[0])
        for i in range(1, len(children)):
            child = children[i]
            if isinstance(child, Tree):
                rhs = _to_expr(child)
                expr = ast.BinOp(op=default_op, a=expr, b=rhs)
            elif isinstance(child, Token):
                rhs = _to_expr(child)
                expr = ast.BinOp(op=default_op, a=expr, b=rhs)
            else:
                rhs = _to_expr(child)
                expr = ast.BinOp(op=default_op, a=expr, b=rhs)
        return expr

    # Odd length: operators present
    expr = _to_expr(children[0])
    i = 1
    while i < len(children):
        op_node = children[i]
        if isinstance(op_node, Tree):
            rhs = _to_expr(op_node)
            expr = ast.BinOp(op=default_op, a=expr, b=rhs)
            i += 1
        elif isinstance(op_node, Token):
            op = str(op_node).upper()
            if i + 1 < len(children):
                rhs = _to_expr(children[i + 1])
                expr = ast.BinOp(op=op, a=expr, b=rhs)
                i += 2
            else:
                break
        else:
            op = str(op_node).upper()
            if i + 1 < len(children):
                rhs = _to_expr(children[i + 1])
                expr = ast.BinOp(op=op, a=expr, b=rhs)
                i += 2
            else:
                break
    return expr


def _tok(x) -> str:
    """Convert token or tree to string"""
    if isinstance(x, Token):
        return str(x)
    return str(x)


__all__ = [
    "ParserConfig",
    "parse_program",
]
