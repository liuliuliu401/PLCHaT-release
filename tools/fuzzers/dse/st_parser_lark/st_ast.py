from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union


# ---------- Types ----------

# IEC standard function block types that need special handling in TIA Portal
IEC_FB_TYPES = {"TON", "TOF", "TP", "SR", "RS", "R_TRIG", "F_TRIG", "CTU", "CTD", "CTUD"}


@dataclass
class TypeName:
    name: str
    array: Optional[Tuple[int, int, "TypeSpec"]] = None  # (lo, hi, elem)


@dataclass
class EnumType:
    """Inline enumeration type, such as (S_Safe, S_Tripped, S_Resetting)"""
    values: List[str]


@dataclass
class EnumTypeDef:
    """Named enum type definition, e.g., TYPE E_Mode : (A, B); END_TYPE"""
    name: str
    values: List[str]


@dataclass
class FBInstanceType:
    """IEC standard function block instance types (TON, SR, R_TRIG, etc.)
    
In TIA Portal SCL, these types need to be mapped to specific system type names, such as:
    - TON -> TON_TIME
    - TOF -> TOF_TIME  
    - TP -> TP_TIME
- SR, RS, R_TRIG, F_TRIG, CTU, CTD, CTUD remain unchanged.
    """
    fb_type: str  # Original type names: TON, TOF, TP, SR, RS, R_TRIG, F_TRIG, CTU, CTD, CTUD


# TypeSpec is a union type of TypeName, EnumType, or FBInstanceType
TypeSpec = Union[TypeName, "EnumType", "FBInstanceType"]


# ---------- Declarations ----------
@dataclass
class VarDecl:
    name: str
    typ: TypeSpec
    init: Optional["Expr"] = None


@dataclass
class AtOverlayDecl:
    name: str
    typ: TypeSpec  # Supports TypeName, EnumType or FBInstanceType
    target: str  # e.g., "w" or "w.0"


@dataclass
class VarSection:
    kind: str  # VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_TEMP, VAR, VAR_CONSTANT
    decls: List[Union[VarDecl, AtOverlayDecl]] = field(default_factory=list)


# ---------- Expressions ----------
class Expr:
    pass


@dataclass
class IntLit(Expr):
    value: int


@dataclass
class RealLit(Expr):
    """Floating-point literals, e.g., 20.0, 3.14"""
    value: float


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class StringLit(Expr):
    value: str  # includes quotes, e.g. 'A'


@dataclass
class TimeLit(Expr):
    value: str  # raw literal


@dataclass
class TypedHexLit(Expr):
    value: str


@dataclass
class ArrayInit(Expr):
    """Array initialization literal, such as [31, 28, 31]"""
    values: List[Expr]


@dataclass
class AbsRef(Expr):
    value: str  # raw like I0.0 or DB1.DBW0
    kind: str   # "io" | "db"


@dataclass
class VarRef(Expr):
    name: str


@dataclass
class MemberAccess(Expr):
    """Function block instance member access, such as Timer.Q"""
    parts: List[str]  # e.g., ["HeartbeatTimer", "Q"]


@dataclass
class ArrayAccess(Expr):
    """Array index access, e.g., arr[i] or arr[i,j] or arr[i,j].Occupied"""
    name: str
    indices: List[Expr]  # Support multi-dimensional indexing
    member: Optional[str] = None  # Optional trailing member access


@dataclass
class UnOp(Expr):
    op: str
    x: Expr


@dataclass
class BinOp(Expr):
    op: str
    a: Expr
    b: Expr


@dataclass
class CallExpr(Expr):
    name: str
    args: List[Tuple[Optional[str], Expr]]  # (kw, expr)


# ---------- Statements ----------
class Stmt:
    pass


@dataclass
class Assign(Stmt):
    target: str
    expr: Expr


@dataclass
class CallStmt(Stmt):
    call: CallExpr


@dataclass
class IfStmt(Stmt):
    arms: List[Tuple[Expr, List[Stmt]]]  # (cond, block)
    else_block: Optional[List[Stmt]]


@dataclass
class CaseArm:
    labels: List[Tuple[Union[int, str], Optional[Union[int, str]]]]  # [(n, None), (lo, hi)] - supports integer or enumeration name
    body: List[Stmt]


@dataclass
class CaseStmt(Stmt):
    selector: Expr
    arms: List[CaseArm]
    else_block: Optional[List[Stmt]]


@dataclass
class ForStmt(Stmt):
    var: str
    start: Expr
    end: Expr
    step: Optional[Expr]
    body: List[Stmt]


@dataclass
class WhileStmt(Stmt):
    cond: Expr
    body: List[Stmt]


@dataclass
class RepeatStmt(Stmt):
    body: List[Stmt]
    until: Expr


@dataclass
class ExitStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ReturnStmt(Stmt):
    pass


# ---------- POU ----------
@dataclass
class POU:
    kind: str  # FUNCTION_BLOCK | FUNCTION | PROGRAM
    name: str
    return_type: Optional[TypeName] = None
    decls: List[VarSection] = field(default_factory=list)
    body: List[Stmt] = field(default_factory=list)
    type_defs: List[EnumTypeDef] = field(default_factory=list)
