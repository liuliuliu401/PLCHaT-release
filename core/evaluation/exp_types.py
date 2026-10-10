"""
Unified Experimental IR for PLC Test Case Generation

Defines ExpUnifiedIR - the unified representation for test cases across
all testing engines (AFL++, DSE, Random, Direct LLM).

Key features:
- Physical sandbox filtering with IEC 61131-3 type limits
- Fuzzy variable matching for LLM-generated names
- Multi-cycle sparse timeline to dense harness input conversion
- Validation with intelligent hints for variable name corrections
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
import json
import sys
from pathlib import Path
import difflib
import re

# Project root resolution
# core/evaluation/exp_types.py → evaluation → core → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.constants import IEC_TYPE_LIMITS


@dataclass
class ExpUnifiedIR:
    """Unified Experimental Intermediate Representation for test cases.

    Attributes:
        exp_id: Unique experiment identifier
        target_st_path: Path to target ST program file
        schema_path: Path to input schema JSON file
        tester_type: Testing engine type (e.g., "PureLLM", "AFL", "DSE", "Random")
        scan_cycle_ms: Scan cycle period in milliseconds
        total_cycles: Total execution cycles
        sparse_timeline: Dict mapping cycle number to variable updates
        metadata: Additional experiment metadata
    """
    exp_id: str
    target_st_path: str
    schema_path: str
    tester_type: str = "PureLLM"
    scan_cycle_ms: int = 10
    total_cycles: int = 10
    sparse_timeline: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def _sanitize_value(self, value: Any, plc_type: str) -> str:
        """Physical layer filtering: enforce IEC_TYPE_LIMITS clipping.

        Args:
            value: Input value to sanitize
            plc_type: Target PLC IEC 61131-3 type

        Returns:
            Sanitized string representation

        Raises:
            ValueError: If value cannot be converted to target type
        """
        plc_type = str(plc_type).upper()
        # Default to INT if type not defined
        limits = IEC_TYPE_LIMITS.get(plc_type, IEC_TYPE_LIMITS["INT"])
        cast_func = limits["type"]

        # 1. Boolean type special mapping
        if plc_type == "BOOL":
            if str(value).upper() in ["TRUE", "1", "T", "ON"]:
                return "1"
            if str(value).upper() in ["FALSE", "0", "F", "OFF"]:
                return "0"

        # 2. Numeric conversion with legality check
        try:
            if value is None or str(value).strip() == "":
                num_val = 0
            else:
                num_val = cast_func(value)
        except (ValueError, TypeError):
            raise ValueError(
                f"ILLEGAL_INPUT: Cannot convert '{value}' to PLC Type {plc_type}"
            )

        # 3. Physical boundary clipping
        if num_val < limits["min"]:
            num_val = limits["min"]
        elif num_val > limits["max"]:
            num_val = limits["max"]

        # 4. Format output
        if cast_func == float:
            return f"{num_val:.6f}"
        return str(int(num_val))

    def _resolve_type(self, matched_col: str, data: Dict[str, Any]) -> Optional[str]:
        """Unified type resolution: metadata (v2) with types (v1) fallback.

        Args:
            matched_col: Column name to resolve
            data: Schema data dict

        Returns:
            IEC type string or None if not found
        """
        if not matched_col:
            return None

        # 1. Try Metadata extraction (Schema V2 standard)
        meta = data.get("metadata", {})
        if matched_col in meta:
            return meta[matched_col].get("iec_type")

        # 2. Try Types extraction (Schema V1 compatibility)
        types = data.get("types", {})
        if matched_col in types:
            return types[matched_col]

        # 3. Handle AFL physical path prefix (instance->)
        clean_name = matched_col.replace("instance->", "")
        if clean_name in meta:
            return meta[clean_name].get("iec_type")
        if clean_name in types:
            return types[clean_name]

        return None

    def _fuzzy_match(self, key: str, schema_cols: List[str]) -> Optional[str]:
        """Fuzzy variable name matching with array support.

        WARNING: EXPERIMENTAL - resolves LLM variable names (PUSH) against
        Schema column names (instance->PUSH.value). Enhanced to support
        MatIEC array format (VAR[0] -> VAR.value.table[0]).

        Args:
            key: Variable name to match
            schema_cols: List of valid schema column names

        Returns:
            Matched column name or None
        """
        key_upper = key.upper()

        # 1. Try direct exact match
        if key_upper in [col.upper() for col in schema_cols]:
            return schema_cols[[col.upper() for col in schema_cols].index(key_upper)]

        # 2. Parse base name and index for arrays
        # e.g., key="MATRIX1[0][0]" -> base="MATRIX1", suffix="[0][0]"
        match = re.match(r"^(\w+)(\[.*\])$", key_upper)

        if match:
            base, suffix = match.groups()
            candidates = []
            for col in schema_cols:
                col_upper = col.upper()
                if base not in col_upper:
                    continue
                if suffix in col_upper:
                    candidates.append(col)

            if candidates:
                return candidates[0]

        # 3. Fallback to scalar containment match
        candidates = [col for col in schema_cols if key_upper in col.upper()]
        if candidates:
            # Prioritize strong patterns like "->VAR."
            strong_match = next(
                (c for c in candidates
                 if f">{key_upper}." in c.upper() or f"{key_upper}[" in c.upper()),
                None
            )
            return strong_match if strong_match else candidates[0]

        return None

    def validate(self) -> Tuple[bool, List[str]]:
        """Validate inputs against physical harness schema.

        Returns:
            Tuple of (is_valid, error_list)
        """
        errors = []
        try:
            with open(self.schema_path, 'r') as f:
                data = json.load(f)
                schema = data["columns"] if isinstance(data, dict) and "columns" in data else data

            # 1. Check timeline depth
            max_cycle_in_timeline = -1
            if self.sparse_timeline:
                max_cycle_in_timeline = max([int(k) for k in self.sparse_timeline.keys()])

            if max_cycle_in_timeline >= self.total_cycles:
                self.total_cycles = max_cycle_in_timeline + 1

            # Extract valid base names for hints
            valid_bases = set()
            for col in schema:
                name = col.replace("instance->", "")
                base = re.split(r'\[|\.', name)[0]
                valid_bases.add(base)
            valid_bases_list = list(valid_bases)

            # 2. Preload metadata (keep variable name compatible)
            schema_types = data.get("types", {})

            # 3. Check variables and their values
            for cycle, updates in self.sparse_timeline.items():
                # Handle nested sparse_timeline structure
                if isinstance(updates, dict) and "sparse_timeline" in updates:
                    updates = updates["sparse_timeline"].get(str(cycle), {}) \
                        or updates["sparse_timeline"].get(int(cycle), {})

                for var_name, value in updates.items():
                    # 3.1 Variable name validation
                    matched = self._fuzzy_match(var_name, schema)
                    if not matched:
                        closest = difflib.get_close_matches(
                            var_name.lower(),
                            [v.lower() for v in valid_bases_list],
                            n=1, cutoff=0.6
                        )
                        hint = f" Did you mean '{closest[0]}'?" if closest else ""
                        errors.append(
                            f"Variable '{var_name}' in Cycle {cycle} is REJECTED. "
                            f"REASON: Not a recognized VAR_INPUT.{hint}"
                        )
                    else:
                        # 3.2 Type resolution with V1/V2 compatibility
                        target_type = self._resolve_type(matched, data)
                        if not target_type:
                            errors.append(
                                f"Variable '{var_name}' in Cycle {cycle} is REJECTED. "
                                f"REASON: Matched column '{matched}' has no defined PLC type. "
                                "It may be a non-injectable internal variable."
                            )
                            continue

                        try:
                            # Recursive validation for arrays
                            if isinstance(value, list):
                                for item in value:
                                    self._sanitize_value(item, target_type)
                            else:
                                self._sanitize_value(value, target_type)
                        except ValueError as ve:
                            errors.append(
                                f"Value Error in Cycle {cycle} for '{var_name}': {str(ve)}. "
                                "REASON: Physical IO Layer rejected the malformed data type."
                            )

            # 3. Single-cycle check
            if self.total_cycles <= 1:
                print("[Hint] Single-cycle test generated. Valid, but multi-cycle "
                      "sequences are encouraged for stateful PLC logic.")

        except Exception as e:
            errors.append(f"Validation failed with internal error: {e}")

        return len(errors) == 0, list(set(errors))

    def to_harness_input(self) -> str:
        """Physical layer serialization: enforce sandbox filtering before harness.

        Returns:
            Multi-line string with space-separated values per cycle
        """
        with open(self.schema_path, 'r') as f:
            data = json.load(f)
            schema_cols = data.get("columns", [])
            schema_types = data.get("types", {})

        full_stream = []
        # Initialize all-zero dense state
        current_dense_state = {col: "0" for col in schema_cols}

        # Determine total execution cycles
        exec_cycles = max(
            self.total_cycles,
            (max([int(k) for k in self.sparse_timeline.keys()]) + 1)
            if self.sparse_timeline else 0
        )

        for c in range(exec_cycles):
            # Get updates for current cycle
            updates = self.sparse_timeline.get(c) or self.sparse_timeline.get(str(c))

            if updates:
                for key, val in updates.items():
                    # Case A: Array/list data
                    if isinstance(val, list):
                        # Flatten multi-dimensional arrays
                        flat_data = []

                        def flatten(l):
                            for i in l:
                                if isinstance(i, list):
                                    flatten(i)
                                else:
                                    flat_data.append(i)

                        flatten(val)

                        base_upper = key.upper()
                        # Get all matching array element columns
                        related_cols = [
                            col for col in schema_cols
                            if f">{base_upper}." in col.upper() or f"{base_upper}[" in col.upper()
                        ]

                        for i in range(min(len(flat_data), len(related_cols))):
                            col_name = related_cols[i]
                            target_type = self._resolve_type(col_name, data)
                            if target_type:
                                current_dense_state[col_name] = self._sanitize_value(
                                    flat_data[i], target_type
                                )

                    # Case B: Scalar variables
                    else:
                        matched_col = self._fuzzy_match(key, schema_cols)
                        if matched_col:
                            target_type = self._resolve_type(matched_col, data)
                            if target_type:
                                current_dense_state[matched_col] = self._sanitize_value(
                                    val, target_type
                                )

            # Append current cycle's full state to stream
            line = " ".join([current_dense_state[col] for col in schema_cols])
            full_stream.append(line)

        return "\n".join(full_stream)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("ExpUnifiedIR - Unified Experimental IR for PLC Testing")
    print("=" * 80)
    print(f"\nPROJECT_ROOT: {PROJECT_ROOT}")
    print("Module loaded successfully. Use ExpUnifiedIR class for test case representation.")
