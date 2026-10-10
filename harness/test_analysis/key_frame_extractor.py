"""
Key Frame Extractor - Extract critical moments from test execution.

By analyzing the state changes of test inputs, identify key moments (key frames) to reduce the cognitive load of LLM.

Keyframe type:
- Boundary break: variable value exceeds expected range
- State transition: boolean variable 0→1 or 1→0
- Exception mode: mode value switches from 0 to exception value
First occurrence: variable first assigned
- Constraint violation: hiLim ≤ loLim and other business constraint violations

Usage:
    from harness.test_analysis.key_frame_extractor import KeyFrameExtractor

    extractor = KeyFrameExtractor()
    key_frames = extractor.extract(test_input)
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
import logging
from dataclasses import dataclass, field
from enum import Enum

# Project root: key_frame_extractor.py → test_analysis → harness → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))


logger = logging.getLogger(__name__)


class KeyFrameType(Enum):
    """# Keyframe type."""
    BOUNDARY_EXCEED = "BOUNDARY_EXCEED"      # Variable value is out of expected range
    STATE_TOGGLE = "STATE_TOGGLE"            # Boolean variable state toggle
    MODE_SWITCH = "MODE_SWITCH"              # Mode value change
    FIRST_APPEARANCE = "FIRST_APPEARANCE"    # Variable is first assigned
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"  # Business constraint violation
    RANGE_ANOMALY = "RANGE_ANOMALY"          # The value is in the abnormal range


@dataclass
class KeyFrame:
    """Keyframe data structure."""
    cycle: int
    event_type: KeyFrameType
    variables: Dict[str, Any]
    context: str
    severity: str = "info"  # info, warning, critical

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle": self.cycle,
            "event_type": self.event_type.value,
            "event_type_code": self.event_type.name,
            "variables": self.variables,
            "context": self.context,
            "severity": self.severity
        }


@dataclass
class KeyFrameSummary:
    """Keyframe summary."""
    total_frames: int
    frames_by_type: Dict[str, int]
    information_density: float
    compression_ratio: float
    key_frames: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_frames": self.total_frames,
            "frames_by_type": self.frames_by_type,
            "information_density": self.information_density,
            "compression_ratio": self.compression_ratio,
            "key_frames": self.key_frames
        }


class KeyFrameExtractor:
    """
Keyframe extractor.

Identify key moments by analyzing state changes of test inputs.
    """

    # Default boundary value configuration
    DEFAULT_BOUNDARIES = {
        "hilim": {"min": 0.0, "max": 100.0, "critical_max": 800.0},
        "lolim": {"min": 0.0, "max": 100.0, "critical_max": 800.0},
        "analog": {"min": 0.0, "max": 10.0, "critical_max": 1000.0},
        "count": {"min": 0, "max": 100, "critical_max": 1000},
        "mode": {"valid_range": [0, 1, 3, 8], "abnormal": [800, 80]},
        "enable": {"valid": [0, 1]},
        "bipolar": {"valid": [0, 1]},
    }

    def __init__(self, boundaries: Optional[Dict] = None):
        """
Initialize the keyframe extractor.

        Args:
boundaries: custom boundary value configuration
        """
        self.boundaries = boundaries or self.DEFAULT_BOUNDARIES
        self.appeared_vars: Set[str] = set()
        self.prev_state: Dict[str, Any] = {}

    def extract(
        self,
        test_input: Dict[str, Any],
        max_frames: int = 20
    ) -> KeyFrameSummary:
        """
Extract key frames from test input.

        Args:
test_input: test input in AFL sparse_timeline format
max_frames: maximum number of keyframes (to prevent excessive output)

        Returns:
KeyFrameSummary: keyframe summary
        """
        # Reset state
        self.appeared_vars = set()
        self.prev_state = {}

        sparse_timeline = test_input.get("sparse_timeline", {})
        if not sparse_timeline:
            return self._empty_summary()

        key_frames: List[KeyFrame] = []
        total_state_updates = 0

        # Process in cycle order
        for cycle_str in sorted(sparse_timeline.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            cycle = int(cycle_str) if cycle_str.isdigit() else 0
            variables = sparse_timeline[cycle_str]
            total_state_updates += len(variables)

            # Detect various keyframes
            frames = self._detect_key_frames(cycle, variables)
            key_frames.extend(frames)

            # Save current state
            self.prev_state.update(variables)

        # Limit the number of keyframes
        if len(key_frames) > max_frames:
            # Sort by severity and importance
            key_frames = self._prioritize_frames(key_frames)[:max_frames]

        # Calculate compression ratio
        compression_ratio = total_state_updates / len(key_frames) if key_frames else 0

        # Calculate information density
        information_density = self._calculate_information_density(key_frames, total_state_updates)

        # Count the number of each type
        frames_by_type = {}
        for kf in key_frames:
            event_type = kf.event_type.value
            frames_by_type[event_type] = frames_by_type.get(event_type, 0) + 1

        return KeyFrameSummary(
            total_frames=len(key_frames),
            frames_by_type=frames_by_type,
            information_density=information_density,
            compression_ratio=compression_ratio,
            key_frames=[kf.to_dict() for kf in key_frames]
        )

    def _detect_key_frames(self, cycle: int, variables: Dict[str, Any]) -> List[KeyFrame]:
        """Detect keyframes of a single cycle."""
        frames = []

        for var_name, var_value in variables.items():
            # 1. Detect boundary breakthrough
            boundary_frame = self._detect_boundary_exceed(cycle, var_name, var_value)
            if boundary_frame:
                frames.append(boundary_frame)

            # 2. Detect state transition
            toggle_frame = self._detect_state_toggle(cycle, var_name, var_value)
            if toggle_frame:
                frames.append(toggle_frame)

            # 3. Detect mode switch
            mode_frame = self._detect_mode_switch(cycle, var_name, var_value)
            if mode_frame:
                frames.append(mode_frame)

            # 4. Detect first occurrence
            first_frame = self._detect_first_appearance(cycle, var_name, var_value)
            if first_frame:
                frames.append(first_frame)

        # 5. Detect constraint violations (requires multiple variables)
        constraint_frames = self._detect_constraint_violations(cycle, variables)
        frames.extend(constraint_frames)

        return frames

    def _detect_boundary_exceed(self, cycle: int, var_name: str, var_value: Any) -> Optional[KeyFrame]:
        """# Detect numerical boundary breakthrough—based on common IEC61131 types, no restriction on variable names."""
        try:
            value = float(var_value)
        except (ValueError, TypeError):
            return None

        # IEC 61131-3 common type limits (approximate)
        if -128 <= value <= 127:
            iec_type = "SINT/BYTE/BOOL"
            limits = (-128, 127)
        elif -32768 <= value <= 32767:
            iec_type = "INT"
            limits = (-32768, 32767)
        elif -2147483648 <= value <= 2147483647:
            iec_type = "DINT"
            limits = (-2147483648, 2147483647)
        else:
            iec_type = "LINT/LREAL"
            limits = (-9e18, 9e18)

        low, high = limits
        near_limit = abs(value) > (abs(high) * 0.9) if high > 100 else abs(value) > (abs(high) * 0.7)
        # Also detect extreme values (> 10^6)
        extreme = abs(value) > 1e6

        if extreme:
            return KeyFrame(cycle=cycle, event_type=KeyFrameType.BOUNDARY_EXCEED,
                variables={var_name: value}, context=f"{var_name}={value} extreme value(>{int(1e6)})",
                severity="warning")
        elif near_limit and abs(value) > 100:
            return KeyFrame(cycle=cycle, event_type=KeyFrameType.BOUNDARY_EXCEED,
                variables={var_name: value},
                context=f"{var_name}={value} near {iec_type} boundary[{low},{high}]",
                severity="info")
        return None

    def _detect_state_toggle(self, cycle: int, var_name: str, var_value: Any) -> Optional[KeyFrame]:
        """Detect boolean state transition — any variable with 0/1 value changes between cycles, regardless of variable name."""
        try:
            current_value = int(var_value)
        except (ValueError, TypeError):
            return None

        if current_value not in [0, 1]:
            return None

        prev_value = self.prev_state.get(var_name)
        if prev_value is not None:
            try:
                prev_int = int(prev_value)
                if prev_int != current_value:
                    return KeyFrame(cycle=cycle, event_type=KeyFrameType.STATE_TOGGLE,
                        variables={var_name: current_value},
                        context=f"{var_name}: {prev_int}→{current_value}",
                        severity="info")
            except (ValueError, TypeError):
                pass
        return None

    def _detect_mode_switch(self, cycle: int, var_name: str, var_value: Any) -> Optional[KeyFrame]:
        """Detect mode switch - integer variable value changes, variable name not limited."""
        try:
            current_value = int(var_value)
        except (ValueError, TypeError):
            return None

        # Skip trivial 0/1 (handled by state_toggle)
        if current_value in [0, 1]:
            return None

        prev_value = self.prev_state.get(var_name)
        if prev_value is not None:
            try:
                prev_int = int(prev_value)
                if prev_int != current_value:
                    return KeyFrame(cycle=cycle, event_type=KeyFrameType.MODE_SWITCH,
                        variables={var_name: current_value},
                        context=f"{var_name}: {prev_int}→{current_value}",
                        severity="info")
            except (ValueError, TypeError):
                pass
        return None

    def _detect_first_appearance(self, cycle: int, var_name: str, var_value: Any) -> Optional[KeyFrame]:
        """Detect first occurrence of variables — record all variables, regardless of variable name."""
        if var_name not in self.appeared_vars:
            self.appeared_vars.add(var_name)
            # Record first appearance for ALL variables
            return KeyFrame(cycle=cycle, event_type=KeyFrameType.FIRST_APPEARANCE,
                variables={var_name: var_value},
                context=f"{var_name} first appeared, value={var_value}",
                severity="info")
        return None

    def _detect_constraint_violations(self, cycle: int, variables: Dict[str, Any]) -> List[KeyFrame]:
        """Detect constraint violation – general version, based on variable value relationships rather than variable names."""
        frames = []
        # Collect pairs of related variables (same base name with different suffixes)
        pairs = {}
        for var_name, var_value in variables.items():
            try:
                val = float(var_value)
                # Group variables by base name (strip trailing digits/suffixes)
                import re
                base = re.sub(r'[_\d]+$', '', var_name)
                if base not in pairs:
                    pairs[base] = []
                pairs[base].append((var_name, val))
            except (ValueError, TypeError):
                continue

        # Check for contradictory pairs (e.g., min > max pattern)
        for base, vals in pairs.items():
            if len(vals) >= 2:
                sorted_vals = sorted(vals, key=lambda x: x[1])
                lo_name, lo_val = sorted_vals[0]
                hi_name, hi_val = sorted_vals[-1]
                # Detect "upper bound < lower bound" pattern
                if 'hi' in lo_name.lower() and 'lo' in hi_name.lower():
                    if lo_val <= hi_val:
                        frames.append(KeyFrame(cycle=cycle,
                            event_type=KeyFrameType.CONSTRAINT_VIOLATION,
                            variables={lo_name: lo_val, hi_name: hi_val},
                            context=f"constraint violation: {lo_name}({lo_val}) <= {hi_name}({hi_val})",
                            severity="critical"))
        return frames

    def _prioritize_frames(self, frames: List[KeyFrame]) -> List[KeyFrame]:
        """Sort keyframes by priority."""
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(frames, key=lambda f: (
            severity_order.get(f.severity, 3),
            f.cycle
        ))

    def _calculate_information_density(self, key_frames: List[KeyFrame], total_updates: int) -> float:
        """Calculate information density."""
        if not key_frames:
            return 0.0

        # Count the number of different types
        type_count = len(set(kf.event_type for kf in key_frames))

        # Density = (type count / keyframe count) * (keyframe severity weight)
        severity_weight = sum(3 if kf.severity == "critical" else 2 if kf.severity == "warning" else 1
                              for kf in key_frames)

        return (type_count / len(key_frames)) * (severity_weight / len(key_frames))

    def _empty_summary(self) -> KeyFrameSummary:
        """Return empty summary."""
        return KeyFrameSummary(
            total_frames=0,
            frames_by_type={},
            information_density=0.0,
            compression_ratio=0.0,
            key_frames=[]
        )


def format_key_frames_for_llm(summary: KeyFrameSummary) -> str:
    """
Format keyframe summaries into LLM-readable text.

    Args:
summary: Keyframe summary

    Returns:
"Formatted text"
    """
    lines = [
        f"=== Key Frame Summary ===",
        f"Total Key Frames: {summary.total_frames}",
        f"Information Density: {summary.information_density:.2f}",
        f"Compression Ratio: {summary.compression_ratio:.1f}:1",
        f"",
        f"=== Key Frame Type Distribution ==="
    ]

    for event_type, count in summary.frames_by_type.items():
        lines.append(f"  {event_type}: {count}")

    lines.append("")
    lines.append("=== Detailed Key Frames ===")

    for i, kf in enumerate(summary.key_frames, 1):
        severity_marker = "🔴" if kf["severity"] == "critical" else "🟡" if kf["severity"] == "warning" else "🔵"
        lines.append(f"{severity_marker} [{i}] Cycle {kf['cycle']}: {kf['event_type']}")
        lines.append(f"     Variables: {kf['variables']}")
        lines.append(f"     Context: {kf['context']}")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "KeyFrameExtractor",
    "KeyFrameType",
    "KeyFrame",
    "KeyFrameSummary",
    "format_key_frames_for_llm"
]
