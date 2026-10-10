"""
Seed Generator - input.txt seed generator

Generate initial test seed input.txt based on Schema.
"""

import os
import sys
from pathlib import Path
from typing import List, Any, Dict

# Safe import method
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class SeedGenerator:
    """
input.txt seed generator

Generate boundary value test cases based on schema.
    """

    # IEC type boundary value
    TYPE_BOUNDARIES = {
        "BOOL": [0, 1],
        "SINT": [-128, -1, 0, 1, 127],
        "USINT": [0, 1, 127, 255],
        "BYTE": [0, 1, 127, 255],
        "INT": [-32768, -1, 0, 1, 32767],
        "UINT": [0, 1, 16383, 65535],
        "WORD": [0, 1, 16383, 65535],
        "DINT": [-2147483648, -1, 0, 1, 2147483647],
        "UDINT": [0, 1, 1073741823, 4294967295],
        "DWORD": [0, 1, 1073741823, 4294967295],
        "LINT": [0, 1, 100],  # Simplify
        "ULINT": [0, 1, 100],
        "REAL": [0.0, 1.0, -1.0, 100.0],
        "LREAL": [0.0, 1.0, -1.0, 100.0],
    }

    def generate(self, schema: Dict[str, Any], num_seeds: int = 20) -> List[str]:
        """
Generate seed list

        Args:
schema: input_schema_v2.json content
num_seeds: number of generated seeds

        Returns:
Seed row list
        """
        columns = schema["columns"]
        metadata = schema["metadata"]

        seeds = []

        # Seed 1: all zeros
        seeds.append(self._make_seed_line(columns, metadata, "zero"))

        # Seed 2: all ones
        seeds.append(self._make_seed_line(columns, metadata, "one"))

        # Seed 3: boundary value mixing
        seeds.append(self._make_seed_line(columns, metadata, "mixed"))

        # Seed 4-N: random value
        import random
        for _ in range(num_seeds - 3):
            seeds.append(self._make_seed_line(columns, metadata, "random"))

        return seeds

    def _make_seed_line(
        self,
        columns: List[str],
        metadata: Dict[str, Any],
        mode: str = "zero"
    ) -> str:
        """
Generate a single-line seed

        Args:
columns: list of column names
metadata: column metadata
            mode: zero/one/mixed/random

        Returns:
seed row string
        """
        import random

        values = []
        for col in columns:
            col_meta = metadata[col]
            iec_type = col_meta["iec_type"]

            if mode == "zero":
                val = self._get_zero_value(iec_type)
            elif mode == "one":
                val = self._get_one_value(iec_type)
            elif mode == "mixed":
                val = self._get_mixed_value(iec_type)
            else:  # random
                val = self._get_random_value(iec_type)

            values.append(str(val))

        return " ".join(values)

    def _get_zero_value(self, iec_type: str) -> Any:
        """Get zero value"""
        return 0

    def _get_one_value(self, iec_type: str) -> Any:
        """Get value 1"""
        return 1

    def _get_mixed_value(self, iec_type: str) -> Any:
        """Get mixed boundary values"""
        boundaries = self.TYPE_BOUNDARIES.get(iec_type, [0, 1])
        # Take the middle boundary value
        return boundaries[len(boundaries) // 2]

    def _get_random_value(self, iec_type: str) -> Any:
        """# Get random value"""
        import random
        boundaries = self.TYPE_BOUNDARIES.get(iec_type, [0, 100])
        if iec_type in ["REAL", "LREAL"]:
            return round(random.uniform(0, 100), 2)
        return random.choice(boundaries)

    def generate_to_file(
        self,
        schema: Dict[str, Any],
        output_path: Path,
        num_seeds: int = 20
    ) -> bool:
        """
Generate seed and write to file

        Args:
schema: content of input_schema_v2.json
output_path: output file path
num_seeds: The number of seeds generated

        Returns:
Whether successful
        """
        try:
            seeds = self.generate(schema, num_seeds)
            with open(output_path, 'w', encoding='utf-8') as f:
                for seed in seeds:
                    f.write(seed + "\n")
            return True
        except Exception as e:
            print(f"Error writing seeds: {e}")
            return False


# Test interface
if __name__ == "__main__":
    # Example: Manual test
    import json
    from pathlib import Path

    # Example schema
    example_schema = {
        "task": "Test",
        "version": "2.0",
        "column_count": 2,
        "columns": ["temp_bool", "temp_int"],
        "metadata": {
            "temp_bool": {"iec_type": "BOOL", "is_array": False},
            "temp_int": {"iec_type": "INT", "is_array": False}
        }
    }

    seed_gen = SeedGenerator()
    seeds = seed_gen.generate(example_schema, num_seeds=5)

    print(f"Generated {len(seeds)} seeds:")
    for i, seed in enumerate(seeds, 1):
        print(f"{i}. {seed}")
