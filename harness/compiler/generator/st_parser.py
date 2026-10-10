"""
ST Parser - Simplified ST source code variable classification extractor

# Use regular expressions to extract variable declarations and classifications (VAR_INPUT/OUTPUT/IN_OUT/TEMP) from ST source code.
# Do not perform complete syntax parsing, only used to obtain variable classification information.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ParsedVar:
    """parsed variable"""
    name: str
    iec_type: str
    is_array: bool = False
    array_size: int = None
    array_lo: int = None
    array_hi: int = None
    init_value: str = None


@dataclass
class ParsedPOU:
    """Parsed POU"""
    kind: str              # FUNCTION_BLOCK | FUNCTION | PROGRAM
    name: str
    vars_by_section: Dict[str, List[ParsedVar]]  # section -> vars


class STParserError(Exception):
    """ST parsing error"""
    pass


class STParser:
    """
ST source code variable classification extractor

Use regular expressions to extract variable declarations from ST code:
Identify VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_TEMP, VAR blocks
Extract variable name, type, and array information.
    """

    # Match VAR block: VAR_INPUT ... END_VAR
    VAR_BLOCK_RE = re.compile(
        r'(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR(?:\s+CONSTANT)?|VAR)\s*(.*?)\s*END_VAR',
        re.DOTALL | re.IGNORECASE
    )

    # Match variable declaration: name : ARRAY[lo..hi] OF type | name : type
    VAR_DECL_RE = re.compile(
        r'(\w+)\s*:\s*(?:ARRAY\s*\[(\d+)\.\.(\d+)\]\s*OF\s+)?(\w+)',
        re.IGNORECASE
    )

    # Match POU declaration: FUNCTION_BLOCK name | FUNCTION name | PROGRAM name
    POU_DECL_RE = re.compile(
        r'(FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+(\w+)',
        re.IGNORECASE
    )

    def __init__(self, debug: bool = False):
        self.debug = debug

    def parse_file(self, st_path: Path) -> ParsedPOU:
        """Parse ST file"""
        content = st_path.read_text(encoding="utf-8")
        return self.parse_content(content)

    def parse_content(self, content: str) -> ParsedPOU:
        """Parse ST content"""
        # Preprocessing: Remove comments
        content = self._preprocess(content)

        # Extract POU type and name
        pou_match = self.POU_DECL_RE.search(content)
        if not pou_match:
            raise STParserError("No POU (FUNCTION_BLOCK/FUNCTION/PROGRAM) found")

        kind = pou_match.group(1).upper()
        name = pou_match.group(2)

        # Extract variable declaration
        vars_by_section = self._extract_declarations(content)

        return ParsedPOU(kind=kind, name=name, vars_by_section=vars_by_section)

    def _preprocess(self, content: str) -> str:
        """Preprocess ST code (remove comments)"""
        # Remove multi-line comments (* ... *)
        content = re.sub(r'\(\*.*?\*\)', '', content, flags=re.DOTALL)
        # Remove single-line comment
        content = re.sub(r'//.*', '', content)
        return content

    def _extract_declarations(self, content: str) -> Dict[str, List[ParsedVar]]:
        """Extract variable declaration"""
        result = {}

        for match in self.VAR_BLOCK_RE.finditer(content):
            section = match.group(1).upper()
            # Handle "VAR CONSTANT" -> "VAR_CONSTANT"
            if "CONSTANT" in section:
                section = "VAR_CONSTANT"

            block_content = match.group(2)
            vars_list = []

            # Extract variable declaration
            for var_match in self.VAR_DECL_RE.finditer(block_content):
                var_name = var_match.group(1)
                array_lo = var_match.group(2)
                array_hi = var_match.group(3)
                var_type = var_match.group(4)

                is_array = array_lo is not None

                parsed_var = ParsedVar(
                    name=var_name,
                    iec_type=var_type.upper(),
                    is_array=is_array,
                    array_lo=int(array_lo) if array_lo else None,
                    array_hi=int(array_hi) if array_hi else None,
                    array_size=(int(array_hi) - int(array_lo) + 1) if is_array else None
                )
                vars_list.append(parsed_var)

            result[section] = vars_list

        return result


# test interface
if __name__ == "__main__":
    parser = STParser(debug=True)

    test_st = """
    FUNCTION_BLOCK MultiPumpCtrl
    VAR_INPUT
        mode : BOOL;
        priorities : ARRAY[1..5] OF INT;
    END_VAR
    VAR_OUTPUT
        RunComds : ARRAY[1..5] OF BOOL;
    END_VAR
    VAR
        i : INT;
    END_VAR
    END_FUNCTION_BLOCK
    """

    pou = parser.parse_content(test_st)
    print(f"POU: {pou.kind} {pou.name}")
    for section, vars_list in pou.vars_by_section.items():
        print(f"  {section}:")
        for v in vars_list:
            if v.is_array:
                print(f"    - {v.name}: ARRAY[{v.array_lo}..{v.array_hi}] OF {v.iec_type}")
            else:
                print(f"    - {v.name}: {v.iec_type}")
