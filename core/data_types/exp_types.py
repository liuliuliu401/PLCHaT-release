"""
PLCHaT Experimental Unified IR
Core data structure for unified test case representation and physical sandbox filtering.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
import json
import sys
from pathlib import Path
import difflib

from config.constants import IEC_TYPE_LIMITS


@dataclass
class ExpUnifiedIR:
    """
    Unified Intermediate Representation for PLC test cases.

    This class represents a test case in a sparse timeline format, where
    updates to variables are specified per cycle. It includes physical
    sandbox filtering to ensure IEC 61131-3 type compliance.

    Attributes:
        exp_id: Unique identifier for this experiment
        target_st_path: Path to the target ST file
        schema_path: Path to the JSON schema file
        tester_type: Type of tester (e.g., "PureLLM")
        scan_cycle_ms: Scan cycle duration in milliseconds
        total_cycles: Total number of cycles to execute
        sparse_timeline: Dictionary mapping cycle numbers to variable updates
        metadata: Additional metadata
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
        """
        Physical layer filtering core: Use IEC_TYPE_LIMITS for bit-precision forced truncation of inputs
        """
        plc_type = str(plc_type).upper()

        # 0. STRING type: pass through as-is (handled by %s in harness)
        if plc_type == "STRING":
            return str(value)

        # If type not in definition, default to INT handling
        limits = IEC_TYPE_LIMITS.get(plc_type, IEC_TYPE_LIMITS["INT"])
        cast_func = limits["type"]

        # 1. Boolean type special mapping
        if plc_type == "BOOL":
            if str(value).upper() in ["TRUE", "1", "T", "ON"]: return "1"
            if str(value).upper() in ["FALSE", "0", "F", "OFF"]: return "0"

        # 2. Numeric conversion and validity check
        try:
            # Handle empty values
            if value is None or str(value).strip() == "":
                num_val = 0
            else:
                # Explicit capture: if boolean type but not a valid boolean identifier, cast_func(int) will error
                num_val = cast_func(value)
        except (ValueError, TypeError):
            # [Core modification]: No longer default reset to 0, but raise exception, let caller decide to "reject" or "downgrade"
            raise ValueError(f"ILLEGAL_INPUT: Cannot convert '{value}' to PLC Type {plc_type}")

        # 3. Physical boundary clamping - Only truncate numeric overflows, this belongs to physical fault tolerance
        # Strictly follow the upper/lower limits calculated by bit operations to prevent non-logic-related crashes
        if num_val < limits["min"]:
            num_val = limits["min"]
        elif num_val > limits["max"]:
            num_val = limits["max"]

        # 4. Format output
        if cast_func == float:
            # Ensure floats won't be misjudged by Harness due to scientific notation
            return f"{num_val:.6f}"

        return str(int(num_val))

    def _resolve_type(self, matched_col: str, data: Dict[str, Any]) -> Optional[str]:
        """
        [Compatibility Fix] Unified type parsing: Prioritize metadata (v2), fallback to types (v1).
        """
        if not matched_col: return None
        # 1. Try to extract from Metadata (Schema V2 standard)
        meta = data.get("metadata", {})
        if matched_col in meta: return meta[matched_col].get("iec_type")

        # 2. Try to extract from Types (Schema V1 compatibility)
        types = data.get("types", {})
        if matched_col in types: return types[matched_col]

        # 3. Handle AFL physical path prefix (instance->)
        clean_name = matched_col.replace("instance->", "")
        if clean_name in meta: return meta[clean_name].get("iec_type")
        if clean_name in types: return types[clean_name]

        return None

    def _fuzzy_match(self, key: str, schema_cols: List[str]) -> str:
        """
        WARNING: EXPERIMENTAL, NOT SOLIDIFIED YET
        Helper function: Solve inconsistency between LLM variable names (PUSH) and Schema column names (instance->PUSH.value)
        Enhanced version: Support MatIEC array format (VAR[0] -> VAR.value.table[0])
        """
        key_upper = key.upper()

        # 1. Try direct exact match
        if key_upper in schema_cols:
            return key_upper

        # 2. Parse base name and index in Key (for arrays)
        import re
        match = re.match(r"^(\w+)(\[.*\])$", key_upper)

        if match:
            base, suffix = match.groups()
            # Strategy: Find columns that contain both Base and Suffix
            # Schema might be "instance->MATRIX1.value.table[0][0]"
            candidates = []
            for col in schema_cols:
                col_upper = col.upper()
                # Check if Base is in column name
                if base not in col_upper:
                    continue
                # Check if Suffix is at column name end (or contained within)
                if suffix in col_upper:
                    candidates.append(col)

            if candidates:
                # If multiple, prioritize shortest, or first one
                return candidates[0]

        # 3. If not array, or no match, fallback to original scalar substring matching
        # Find columns in schema that contain "VAR." or "VAR]"
        candidates = [col for col in schema_cols if key_upper in col.upper()]

        if candidates:
            # Prioritize matching strong features like "->VAR."
            strong_match = next((c for c in candidates if f">{key_upper}." in c.upper() or f"{key_upper}[" in c.upper()), None)
            return strong_match if strong_match else candidates[0]

        # 4. Naming convention standardization fallback: Harness temporary variable names have prefixes like temp_/stat_,
        #    schema column names have suffixes like _val, causing key not to be a substring of column.
        #    E.g.: temp_sys_enable vs sys_enable_val, temp_temp_ped_ns_raw vs temp_ped_ns_raw_val.
        BASE_PREFIXES = ("temp_", "stat_", "flag_", "cmd_", "val_", "prev_", "t_", "s_")
        stripped = key_upper
        while any(stripped.startswith(p.upper()) for p in BASE_PREFIXES):
            for pfx in BASE_PREFIXES:
                if stripped.startswith(pfx.upper()):
                    stripped = stripped[len(pfx):]
                    break
        if stripped and stripped != key_upper:
            # Retry exact match with stripped key
            if stripped in schema_cols:
                return stripped
            # Retry substring match with stripped key
            candidates = [col for col in schema_cols if stripped in col.upper()]
            if len(candidates) == 1:
                return candidates[0]
            if candidates:
                # When multiple candidates, prioritize matching after stripping _val suffix
                col_stems = {col: col.upper().replace("_VAL", "").replace(".VALUE", "") for col in candidates}
                for col, stem in col_stems.items():
                    if stem == stripped:
                        return col

        return None

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Hardens the class by validating inputs against the physical harness schema.
        Provides intelligent hints (using difflib) for variable name corrections without altering fuzzy match.
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

            # Extract valid base name set for providing correction suggestions
            valid_bases = set()
            import re
            for col in schema:
                name = col.replace("instance->", "")
                base = re.split(r'\[|\.', name)[0]
                valid_bases.add(base)
            valid_bases_list = list(valid_bases)

            # 2. Preload metadata (keep variable name compatibility)
            schema_types = data.get("types", {})

            # 3. Check variables and their values validity
            for cycle, updates in self.sparse_timeline.items():
                # [Structure Fix] Handle Nested sparse_timeline causing structure collapse
                if isinstance(updates, dict) and "sparse_timeline" in updates:
                    updates = updates["sparse_timeline"].get(str(cycle), updates["sparse_timeline"].get(int(cycle), {}))

                for var_name, value in updates.items():
                    # 3.1 Variable name validation
                    matched = self._fuzzy_match(var_name, schema)
                    if not matched:
                        closest = difflib.get_close_matches(var_name.lower(), [v.lower() for v in valid_bases_list], n=1, cutoff=0.6)
                        hint = f" Did you mean '{closest[0]}'?" if closest else ""
                        errors.append(f"Variable '{var_name}' in Cycle {cycle} is REJECTED. REASON: Not a recognized VAR_INPUT.{hint}")
                    else:
                        # 3.2 [RQ3 Fix] Use enhanced type parser, compatible with V1/V2
                        target_type = self._resolve_type(matched, data)
                        if not target_type:
                            errors.append(
                                f"Variable '{var_name}' in Cycle {cycle} is REJECTED. "
                                f"REASON: Matched column '{matched}' has no defined PLC type. It may be a non-injectable internal variable."
                            )
                            continue

                        try:
                            # Array type recursive validation
                            if isinstance(value, list):
                                for item in value:
                                    self._sanitize_value(item, target_type)
                            else:
                                self._sanitize_value(value, target_type)
                        except ValueError as ve:
                            errors.append(
                                f"Value Error in Cycle {cycle} for '{var_name}': {str(ve)}. "
                                f"REASON: Physical IO Layer rejected the malformed data type."
                            )

            # 3. Single-cycle check (physically valid, provide Hint)
            if self.total_cycles <= 1:
                print("[Hint] Single-cycle test generated. Valid, but multi-cycle sequences are encouraged for stateful PLC logic.")

        except Exception as e:
            errors.append(f"Validation failed with internal error: {e}")

        return len(errors) == 0, list(set(errors))

    def to_harness_input(self) -> str:
        """
        Physical layer serialization: Before feeding data to compiler, force execute sandbox filter layer.
        """
        with open(self.schema_path, 'r') as f:
            data = json.load(f)
            schema_cols = data.get("columns", [])
            schema_types = data.get("types", {})

        full_stream = []
        # Initialize all-zero dense state
        current_dense_state = {col: "0" for col in schema_cols}

        # Determine total execution cycles
        exec_cycles = max(self.total_cycles,
                         (max([int(k) for k in self.sparse_timeline.keys()]) + 1)
                         if self.sparse_timeline else 0)

        for c in range(exec_cycles):
            # Get current cycle update records
            updates = self.sparse_timeline.get(c) or self.sparse_timeline.get(str(c))

            if updates:
                for key, val in updates.items():
                    # --- Case A: Handle array/list data ---
                    if isinstance(val, list):
                        # Flatten multi-dimensional arrays
                        flat_data = []
                        def flatten(l):
                            for i in l:
                                if isinstance(i, list): flatten(i)
                                else: flat_data.append(i)
                        flatten(val)

                        base_upper = key.upper()
                        # Get all matching array element columns
                        related_cols = [col for col in schema_cols if f">{base_upper}." in col.upper() or f"{base_upper}[" in col.upper()]

                        for i in range(min(len(flat_data), len(related_cols))):
                            col_name = related_cols[i]
                            # [Fix] Fix indentation and reposition type lookup
                            target_type = self._resolve_type(col_name, data)
                            if target_type:
                                current_dense_state[col_name] = self._sanitize_value(flat_data[i], target_type)

                    # --- Case B: Handle scalar variables ---
                    else:
                        matched_col = self._fuzzy_match(key, schema_cols)
                        if matched_col:
                            # [Fix] Unify using enhanced parser
                            target_type = self._resolve_type(matched_col, data)
                            if target_type:
                                current_dense_state[matched_col] = self._sanitize_value(val, target_type)

            # Append current cycle's full state to stream
            line = " ".join([current_dense_state[col] for col in schema_cols])
            full_stream.append(line)

        return "\n".join(full_stream)
