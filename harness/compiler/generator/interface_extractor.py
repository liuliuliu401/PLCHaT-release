"""
Interface Extractor - Integrates ST and POUS.h parsing results

Obtain complete variable information by comparing ST source code analysis and MatIEC output:
- ST parser provides: variable classification（VAR_INPUT/OUTPUT/IN_OUT/TEMP）
- POUS.h parser provides: MatIEC structure mapping (variable names, types, array information)
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Safe import method
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.generator import VarDecl, POUInfo
from harness.compiler.generator.st_parser import STParser, ParsedPOU, ParsedVar
from harness.compiler.generator.pou_parser import POUSParser, ParsedPOUFromH


class InterfaceExtractorError(Exception):
    """Interface extraction error"""
    pass


class InterfaceExtractor:
    """
Interface extractor

Integrate the parsing results of ST and POUS.h to generate a complete POUInfo.
    """

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.st_parser = STParser(debug=debug)
        self.pous_parser = POUSParser()

    def extract(
        self,
        st_path: Path,
        pous_h_path: Optional[Path] = None
    ) -> POUInfo:
        """
Extract complete POU interface information

        Args:
st_path: ST source file path
pous_h_path: Path to POUS.h file (optional, will try to locate automatically if not provided)

        Returns:
POUInfo object
        """
        # 1. Parse ST source code
        if self.debug:
            print(f"[InterfaceExtractor] Parsing ST: {st_path}")
        parsed_st = self.st_parser.parse_file(st_path)

        # 2. Parse POUS.h
        if pous_h_path is None:
            # Try to automatically locate (temp_compile/POUS.h in the same directory as the ST file)
            pous_h_path = self._locate_pous_h(st_path)

        if pous_h_path and pous_h_path.exists():
            if self.debug:
                print(f"[InterfaceExtractor] Parsing POUS.h: {pous_h_path}")
            parsed_pous = self.pous_parser.parse_file(pous_h_path)
        else:
            # No POUS.h, only use ST parsing result
            parsed_pous = None

        # 3. Integrate results
        return self._merge(parsed_st, parsed_pous)

    def _locate_pous_h(self, st_path: Path) -> Optional[Path]:
        """Attempt to automatically locate the POUS.h file"""
        # Find temp_compile/POUS.h in the same directory
        possible_locations = [
            st_path.parent / "temp_compile" / "POUS.h",
            st_path.parent.parent / "plc_c_files" / "POUS.h",
            st_path.parent / "POUS.h",
        ]

        for loc in possible_locations:
            if loc.exists():
                return loc

        return None

    def _merge(
        self,
        parsed_st: ParsedPOU,
        parsed_pous: Optional[ParsedPOUFromH]
    ) -> POUInfo:
        """
Integrate the parsing results of ST and POUS.h

Strategy:
- Use ST parsing to get variable classification (INPUT/OUTPUT/IN_OUT/TEMP)
- Use POUS.h to parse and obtain MatIEC structure mapping (variable name format)
- Merge by matching variable names
        """
        pou_info = POUInfo(
            kind=parsed_st.kind,
            name=parsed_st.name,
            pou_name_upper=parsed_pous.pou_name_upper if parsed_pous else parsed_st.name.upper()
        )

        # Create variable name mapping (ST lowercase -> MatIEC variable)
        pous_var_map: Dict[str, VarDecl] = {}
        if parsed_pous:
            for var in parsed_pous.vars:
                pous_var_map[var.name.lower()] = var

        # Process each variable section in ST
        for section, st_vars in parsed_st.vars_by_section.items():
            target_list = self._get_target_list(pou_info, section)

            for st_var in st_vars:
                # Find the corresponding POUS.h variable
                var_decl = self._find_or_create_var(st_var, pous_var_map)
                var_decl.direction = section
                target_list.append(var_decl)

                # Remove from mapping (used to detect missing variables)
                if var_decl.name.lower() in pous_var_map:
                    del pous_var_map[var_decl.name.lower()]

        # Process variables that exist in POUS.h but are not declared in ST (usually added by the compiler)
        for remaining_var in pous_var_map.values():
            if remaining_var.direction == "UNKNOWN":
                # Default classified as TEMP variable
                pou_info.temps.append(remaining_var)

        return pou_info

    def _get_target_list(self, pou_info: POUInfo, section: str) -> List[VarDecl]:
        """# Get the corresponding variable list according to the section type"""
        mapping = {
            "VAR_INPUT": pou_info.inputs,
            "VAR_OUTPUT": pou_info.outputs,
            "VAR_IN_OUT": pou_info.in_outs,
            "VAR_TEMP": pou_info.temps,
            "VAR": pou_info.locals,
            "VAR_CONSTANT": pou_info.locals,
        }
        return mapping.get(section, pou_info.locals)

    def _find_or_create_var(
        self,
        st_var: ParsedVar,
        pous_var_map: Dict[str, VarDecl]
    ) -> VarDecl:
        """
Find or create VarDecl

# Prioritize using information from POUS.h (because it has the correct MatIEC variable name format)
Otherwise, create based on ST information.
        """
        var_name_lower = st_var.name.lower()

        # Attempt to find in POUS.h
        if var_name_lower in pous_var_map:
            pous_var = pous_var_map[var_name_lower]
            # Use information from POUS.h, but retain array boundary information in ST
            pous_var.direction = "UNKNOWN"  # will be set in _merge
            if st_var.is_array:
                pous_var.array_lo = st_var.array_lo
                pous_var.array_hi = st_var.array_hi
            return pous_var

        # Not found in POUS.h, create based on ST information
        return VarDecl(
            name=var_name_lower,
            pou_name=st_var.name.upper(),  # MatIEC format is uppercase
            iec_type=st_var.iec_type,
            direction="UNKNOWN",
            is_array=st_var.is_array,
            array_size=st_var.array_size,
            array_lo=st_var.array_lo,
            array_hi=st_var.array_hi
        )


# test interface
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    # Create test file
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

    test_pous_h = """
__DECLARE_ARRAY_TYPE(__ARRAY_OF_INT_5,INT,[5])
__DECLARE_ARRAY_TYPE(__ARRAY_OF_BOOL_5,BOOL,[5])
typedef struct {
  __DECLARE_VAR(BOOL,EN)
  __DECLARE_VAR(BOOL,ENO)
  __DECLARE_VAR(BOOL,MODE)
  __DECLARE_VAR(__ARRAY_OF_INT_5,PRIORITIES)
  __DECLARE_VAR(__ARRAY_OF_BOOL_5,RUNCOMDS)
  __DECLARE_VAR(INT,I)
} MULTIPUMPCTRL;
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Write test file
        st_path = tmpdir / "test.st"
        st_path.write_text(test_st)

        pous_path = tmpdir / "POUS.h"
        pous_path.write_text(test_pous_h)

        # Test extraction
        extractor = InterfaceExtractor(debug=True)
        pou_info = extractor.extract(st_path, pous_path)

        print(f"\n=== POU Info ===")
        print(f"Kind: {pou_info.kind}")
        print(f"Name: {pou_info.name}")
        print(f"POU Name (upper): {pou_info.pou_name_upper}")

        print(f"\n=== Inputs ===")
        for v in pou_info.inputs:
            print(f"  - {v.name}: {v.iec_type}")

        print(f"\n=== Outputs ===")
        for v in pou_info.outputs:
            print(f"  - {v.name}: {v.iec_type}")

        print(f"\n=== Temps ===")
        for v in pou_info.temps:
            print(f"  - {v.name}: {v.iec_type}")
