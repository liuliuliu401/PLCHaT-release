"""
Schema Generator - input_schema_v2.json Generator

# Generate input_schema_v2.json data contract file based on POUInfo.
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# A safe way to import
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.generator import POUInfo, VarDecl

# IEC types that map to C scalars (compatible with sscanf/printf in harness)
_BASIC_IEC_TYPES = {
    "BOOL", "BYTE", "WORD", "DWORD", "LWORD",
    "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "REAL", "LREAL",
}


class SchemaGenerator:
    """
input_schema_v2.json generator

Generate a schema file that meets the validation requirements of ExpUnifiedIR.
    """

    def generate(self, pou_info: POUInfo) -> Dict[str, Any]:
        """
Generate schema dictionary

        Args:
pou_info: POU information

        Returns:
schema dictionary
        """
        # Expand array variable, generate columns list
        columns = []
        metadata = {}

        for var in pou_info.input_vars:
            if var.is_array:
                # Array expansion: arr[0], arr[1], ..., arr[size-1]
                for i in range(var.array_size):
                    col_name = f"temp_{var.name}_{i}"
                    columns.append(col_name)

                    # ST binding: using 1-based indexing
                    st_binding = f"{var.name}[{i + 1}]"

                    metadata[col_name] = {
                        "iec_type": var.iec_type,
                        "is_array": False,  # After expansion, each element is a scalar
                        "array_range": None,
                        "st_binding": st_binding
                    }
            else:
                # scalar variable
                col_name = f"temp_{var.name}"
                columns.append(col_name)

                metadata[col_name] = {
                    "iec_type": var.iec_type,
                    "is_array": False,
                    "array_range": None,
                    "st_binding": var.name
                }

        schema = {
            "task": pou_info.name,
            "version": "2.0",
            "extraction_source": "AUTO_GENERATED",
            "column_count": len(columns),
            "columns": columns,
            "metadata": metadata
        }

        return schema

    def generate_to_file(
        self,
        pou_info: POUInfo,
        output_path: Path
    ) -> bool:
        """
# Generate schema and write to file

        Args:
pou_info: POU information
output file path

        Returns:
whether successful
        """
        try:
            schema = self.generate(pou_info)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(schema, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error writing schema: {e}")
            return False


# Test interface
if __name__ == "__main__":
    import argparse
    from harness.compiler.generator.interface_extractor import InterfaceExtractor

    parser = argparse.ArgumentParser()
    parser.add_argument("st_path", type=Path, help="ST source file path")
    parser.add_argument("pous_path", type=Path, help="POUS.h file path")
    args = parser.parse_args()

    extractor = InterfaceExtractor(debug=False)
    pou_info = extractor.extract(args.st_path, args.pous_path)

    gen = SchemaGenerator()
    schema = gen.generate(pou_info)

    print(json.dumps(schema, indent=2))
