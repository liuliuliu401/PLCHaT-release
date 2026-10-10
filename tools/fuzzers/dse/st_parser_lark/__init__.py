"""
Lark-based ST Parser for DSE

Self-contained IEC 61131-3 Structured Text parser using Lark.
Copied from st_parser_legacy/lang/ and adapted for DSE integration.

Components:
- grammar.py: Lark grammar definition
- ast.py: AST data structures
- parser.py: Parser implementation

Origin: st_parser_legacy/lang/
Date: 2026-06-03
"""

from .parser import ParserConfig, parse_program
from . import st_ast as ast

__all__ = [
    "ParserConfig",
    "parse_program",
    "ast",
]
