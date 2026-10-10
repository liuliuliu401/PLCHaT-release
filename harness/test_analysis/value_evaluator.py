"""
Test Case Value Evaluator - Evaluate test cases in vulnerability discovery dimension.

Evaluate the value of test cases in the vulnerability discovery dimension and generate concise labels.

Evaluation dimensions:
- Boundary coverage: whether to trigger boundary conditions
Exception coverage: whether to trigger exception path
- State space: whether to explore new state combinations
# Vulnerability disclosure: whether it exposes potential vulnerabilities
- Information gain: information gain compared to existing use cases

Usage:
    from harness.test_analysis.value_evaluator import TestCaseValueEvaluator

    evaluator = TestCaseValueEvaluator()
    value = evaluator.evaluate(test_input, baseline_inputs)
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging

# Project root: value_evaluator.py → test_analysis → harness → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))


logger = logging.getLogger(__name__)


class TestCaseTag(Enum):
    """Test case tag."""
    BOUNDARY_EXPLORATION = "[Boundary Exploration]"
    ANOMALY_TRIGGER = "[Anomaly Trigger]"
    CONSTRAINT_VIOLATION = "[Constraint Violation]"
    STATE_TRANSITION = "[State Transition]"
    HIGH_INFO_GAIN = "[High Info Gain]"
    REDUNDANT = "[Redundant]"


@dataclass
class ValueDimensions:
    """Value evaluation dimension."""
    boundary_coverage: float  # Boundary coverage score (0-100)
    anomaly_coverage: float  # Anomaly Coverage Score (0-100)
    state_space_coverage: float  # State space coverage score (0-100)
    vulnerability_revealed: float  # Vulnerability Disclosure Score (0-100)
    information_gain: float  # Information gain score (0-100)

    def to_dict(self) -> Dict[str, float]:
        return {
            "boundary_coverage": self.boundary_coverage,
            "anomaly_coverage": self.anomaly_coverage,
            "state_space_coverage": self.state_space_coverage,
            "vulnerability_revealed": self.vulnerability_revealed,
            "information_gain": self.information_gain
        }


@dataclass
class TestCaseValueReport:
    """Test case value evaluation report."""
    value_score: float  # Overall value score (0-100)
    dimensions: ValueDimensions
    tags: List[str]
    comparison_with_baseline: str
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value_score": self.value_score,
            "dimensions": self.dimensions.to_dict(),
            "tags": self.tags,
            "comparison_with_baseline": self.comparison_with_baseline,
            "reasoning": self.reasoning
        }


class TestCaseValueEvaluator:
    """
Test case value evaluator.

# Evaluate the value of test cases in the dimension of vulnerability discovery.
    """

    # boundary value threshold
    BOUNDARY_THRESHOLDS = {
        "hilim": {"normal_max": 100.0, "critical_max": 800.0},
        "lolim": {"normal_max": 100.0, "critical_max": 800.0},
        "analog": {"normal_max": 10.0, "critical_max": 1000.0},
    }

    # Exception mode value
    ABNORMAL_MODES = [800, 80, 999]

    def __init__(self):
        """Initialize evaluator."""
        self.baseline_state: Optional[Dict] = None

    def evaluate(
        self,
        test_input: Dict[str, Any],
        baseline_inputs: Optional[List[Dict[str, Any]]] = None,
        key_frames: Optional[List[Dict]] = None
    ) -> TestCaseValueReport:
        """
Evaluate the value of test cases.

        Args:
test_input: test input to be evaluated
baseline_inputs: baseline test inputs (for comparison)
key_frames: optional key frames (if extracted)

        Returns:
TestCaseValueReport: Value Assessment Report
        """
        sparse_timeline = test_input.get("sparse_timeline", {})

        # Evaluate each dimension
        boundary_score, boundary_details = self._evaluate_boundary_coverage(sparse_timeline)
        anomaly_score, anomaly_details = self._evaluate_anomaly_coverage(sparse_timeline)
        state_score, state_details = self._evaluate_state_space_coverage(sparse_timeline)
        vuln_score, vuln_details = self._evaluate_vulnerability_revealed(sparse_timeline, key_frames)
        gain_score, gain_details = self._evaluate_information_gain(sparse_timeline, baseline_inputs)

        # Calculate overall score (weighted average)
        weights = {
            "boundary": 0.25,
            "anomaly": 0.25,
            "state": 0.15,
            "vuln": 0.25,
            "gain": 0.10
        }
        total_score = (
            boundary_score * weights["boundary"] +
            anomaly_score * weights["anomaly"] +
            state_score * weights["state"] +
            vuln_score * weights["vuln"] +
            gain_score * weights["gain"]
        )

        # Generate labels
        tags = self._generate_tags(
            boundary_score, anomaly_score, vuln_score, gain_score
        )

        # Generate comparison description
        comparison = self._generate_comparison(gain_score, gain_details)

        # Generate reason explanation
        reasoning = self._generate_reasoning(
            boundary_details, anomaly_details, state_details, vuln_details
        )

        return TestCaseValueReport(
            value_score=round(total_score, 1),
            dimensions=ValueDimensions(
                boundary_coverage=boundary_score,
                anomaly_coverage=anomaly_score,
                state_space_coverage=state_score,
                vulnerability_revealed=vuln_score,
                information_gain=gain_score
            ),
            tags=tags,
            comparison_with_baseline=comparison,
            reasoning=reasoning
        )

    def _evaluate_boundary_coverage(self, sparse_timeline: Dict[str, Dict]) -> tuple[float, str]:
        """# Evaluate boundary coverage."""
        boundary_exceeds = 0
        boundary_hits = 0
        total_boundary_vars = 0

        for cycle_vars in sparse_timeline.values():
            for var_name, var_value in cycle_vars.items():
                if "hilim" in var_name.lower() or "lolim" in var_name.lower() or "analog" in var_name.lower():
                    total_boundary_vars += 1
                    try:
                        value = float(var_value)

                        # Recognize type
                        if "hilim" in var_name.lower():
                            threshold = self.BOUNDARY_THRESHOLDS.get("hilim", {})
                        elif "lolim" in var_name.lower():
                            threshold = self.BOUNDARY_THRESHOLDS.get("lolim", {})
                        else:
                            threshold = self.BOUNDARY_THRESHOLDS.get("analog", {})

                        normal_max = threshold.get("normal_max", 100.0)
                        critical_max = threshold.get("critical_max", 800.0)

                        if value > critical_max:
                            boundary_exceeds += 1
                        elif value > normal_max:
                            boundary_hits += 1
                    except (ValueError, TypeError):
                        pass

        # Calculate score
        if total_boundary_vars == 0:
            return 0.0, "No boundary variables"

        # Higher weight for boundary breakthrough
        score = ((boundary_exceeds * 100 + boundary_hits * 50) / max(total_boundary_vars, 1))
        score = min(score, 100.0)

        details = f"Boundary variables: {total_boundary_vars}, exceeded: {boundary_exceeds}, hit: {boundary_hits}"
        return score, details

    def _evaluate_anomaly_coverage(self, sparse_timeline: Dict[str, Dict]) -> tuple[float, str]:
        """Evaluate exception coverage."""
        mode_switches = 0
        abnormal_modes = 0
        total_mode_vars = 0

        for cycle_vars in sparse_timeline.values():
            for var_name, var_value in cycle_vars.items():
                if "mode" in var_name.lower():
                    total_mode_vars += 1
                    try:
                        value = int(var_value)
                        if value in self.ABNORMAL_MODES:
                            abnormal_modes += 1
                        elif value not in [0, 1, 3]:
                            mode_switches += 1
                    except (ValueError, TypeError):
                        pass

        if total_mode_vars == 0:
            return 0.0, "No mode variables"

        score = ((abnormal_modes * 100 + mode_switches * 30) / max(total_mode_vars, 1))
        score = min(score, 100.0)

        details = f"Mode variables: {total_mode_vars}, abnormal: {abnormal_modes}, switches: {mode_switches}"
        return score, details

    def _evaluate_state_space_coverage(self, sparse_timeline: Dict[str, Dict]) -> tuple[float, str]:
        """Evaluate state space coverage."""
        # Count unique state combinations
        unique_states = set()

        for cycle, cycle_vars in sparse_timeline.items():
            # Create state signature
            enable_states = []
            for var_name, var_value in cycle_vars.items():
                if "enable" in var_name.lower():
                    try:
                        enable_states.append(f"{var_name}={int(var_value)}")
                    except (ValueError, TypeError):
                        pass

            if enable_states:
                state_sig = ",".join(sorted(enable_states))
                unique_states.add(state_sig)

        # Theoretical state space: if there are N enable variables, the theoretical state space is 2^N
        # Here it is simplified to the ratio of the actual number of states to the number of periods
        coverage_ratio = len(unique_states) / max(len(sparse_timeline), 1)
        score = coverage_ratio * 100

        details = f"Unique states: {len(unique_states)}, total cycles: {len(sparse_timeline)}"
        return min(score, 100.0), details

    def _evaluate_vulnerability_revealed(
        self,
        sparse_timeline: Dict[str, Dict],
        key_frames: Optional[List[Dict]]
    ) -> tuple[float, str]:
        """Assess vulnerability disclosure."""
        # If there is a keyframe, use the constraint violation in the keyframe.
        if key_frames:
            constraint_violations = sum(
                1 for kf in key_frames
                if kf.get("event_type_code") == "CONSTRAINT_VIOLATION"
            )
            boundary_critical = sum(
                1 for kf in key_frames
                if kf.get("event_type_code") == "BOUNDARY_EXCEED" and kf.get("severity") == "critical"
            )

            score = ((constraint_violations * 100 + boundary_critical * 80) / max(len(key_frames), 1))
            details = f"Constraint violations: {constraint_violations}, critical boundaries: {boundary_critical}"
            return min(score, 100.0), details

        # Otherwise direct detection
        violations = 0
        critical_bounds = 0

        for cycle_vars in sparse_timeline.values():
            # Collect variables of the same cycle
            hilims = {}
            lolims = {}
            enables = {}

            for var_name, var_value in cycle_vars.items():
                if "[" in var_name and "]" in var_name:
                    try:
                        base_name = var_name.split("[")[0]
                        idx = int(var_name.split("[")[1].split("]")[0])

                        if "hilim" in base_name.lower():
                            hilims[idx] = float(var_value)
                            if float(var_value) > 800:
                                critical_bounds += 1
                        elif "lolim" in base_name.lower():
                            lolims[idx] = float(var_value)
                        elif "enable" in base_name.lower():
                            enables[idx] = int(var_value)
                    except (ValueError, TypeError, IndexError):
                        pass

            # Detect constraint violation
            for idx in set(list(hilims.keys()) + list(lolims.keys())):
                hilim = hilims.get(idx)
                lolim = lolims.get(idx)
                if hilim is not None and lolim is not None and hilim <= lolim:
                    violations += 1

                enable = enables.get(idx)
                if enable == 1:
                    if hilim is not None and hilim <= 0:
                        violations += 1
                    if lolim is not None and lolim <= 0:
                        violations += 1

        total_vars = sum(len(cycle) for cycle in sparse_timeline.values())
        if total_vars == 0:
            return 0.0, "No variables"

        score = (violations * 100 + critical_bounds * 80) / max(total_vars / 10, 1)
        details = f"Constraint violations: {violations}, critical boundaries: {critical_bounds}"
        return min(score, 100.0), details

    def _evaluate_information_gain(
        self,
        sparse_timeline: Dict[str, Dict],
        baseline_inputs: Optional[List[Dict[str, Any]]]
    ) -> tuple[float, str]:
        """# Evaluate information gain (compared to baseline)."""
        if not baseline_inputs:
            # No baseline, assuming medium value
            return 50.0, "No baseline comparison"

        # Compute features of the current test case
        current_features = self._extract_features(sparse_timeline)

        # Calculate similarity with baseline
        similarities = []
        for baseline in baseline_inputs:
            baseline_timeline = baseline.get("sparse_timeline", {})
            baseline_features = self._extract_features(baseline_timeline)
            sim = self._calculate_similarity(current_features, baseline_features)
            similarities.append(sim)

        avg_similarity = sum(similarities) / len(similarities) if similarities else 0

        # Information gain = 1 - similarity
        gain = (1 - avg_similarity) * 100

        details = f"Average similarity: {avg_similarity:.2%}, difference from baseline: {gain:.1f}%"
        return gain, details

    def _extract_features(self, sparse_timeline: Dict[str, Dict]) -> Dict[str, Any]:
        """Extract the features of test cases."""
        features = {
            "total_cycles": len(sparse_timeline),
            "variables": set(),
            "value_ranges": {},
            "state_patterns": []
        }

        for cycle_vars in sparse_timeline.values():
            for var_name, var_value in cycle_vars.items():
                features["variables"].add(var_name)

                # Record the value range
                try:
                    val = float(var_value)
                    base_name = var_name.split("[")[0] if "[" in var_name else var_name
                    if base_name not in features["value_ranges"]:
                        features["value_ranges"][base_name] = []
                    features["value_ranges"][base_name].append(val)
                except (ValueError, TypeError):
                    pass

        return features

    def _calculate_similarity(self, features1: Dict, features2: Dict) -> float:
        """Calculate the similarity between two features."""
        # Variable overlap
        vars1 = features1["variables"]
        vars2 = features2["variables"]

        if not vars1 or not vars2:
            return 0.0

        overlap = len(vars1 & vars2)
        union = len(vars1 | vars2)

        return overlap / union if union > 0 else 0.0

    def _generate_tags(
        self,
        boundary_score: float,
        anomaly_score: float,
        vuln_score: float,
        gain_score: float
    ) -> List[str]:
        """# Generate labels."""
        tags = []

        if boundary_score > 50:
            tags.append(TestCaseTag.BOUNDARY_EXPLORATION.value)

        if anomaly_score > 50:
            tags.append(TestCaseTag.ANOMALY_TRIGGER.value)

        if vuln_score > 60:
            tags.append(TestCaseTag.CONSTRAINT_VIOLATION.value)

        if gain_score > 70:
            tags.append(TestCaseTag.HIGH_INFO_GAIN.value)
        elif gain_score < 20:
            tags.append(TestCaseTag.REDUNDANT.value)

        if not tags:
            tags.append("[State Transition]")

        return tags

    def _generate_comparison(self, gain_score: float, gain_details: str) -> str:
        """Generate comparison description with baseline."""
        if gain_score > 70:
            return f"High information gain test case. {gain_details}"
        elif gain_score > 40:
            return f"Medium information gain test case. {gain_details}"
        elif gain_score > 20:
            return f"Low information gain test case. {gain_details}"
        else:
            return f"Highly similar to existing test cases, low value. {gain_details}"

    def _generate_reasoning(
        self,
        boundary_details: str,
        anomaly_details: str,
        state_details: str,
        vuln_details: str
    ) -> str:
        """Generate evaluation reason."""
        return (
            f"Boundary coverage: {boundary_details}; "
            f"Anomaly coverage: {anomaly_details}; "
            f"State space: {state_details}; "
            f"Vulnerability revealed: {vuln_details}"
        )


def format_value_report_for_llm(report: TestCaseValueReport) -> str:
    """
Format the value assessment report as LLM-readable text.

    Args:
report: valuation report

    Returns:
Formatted text
    """
    lines = [
        f"=== Test Case Value Assessment ===",
        f"",
        f"**Overall Value Score**: {report.value_score}/100",
        f"",
        f"**Tags**: {' '.join(report.tags)}",
        f"",
        f"**Comparison with Baseline**: {report.comparison_with_baseline}",
        f"",
        f"**Assessment Dimensions**:"
    ]

    for dim, value in report.dimensions.to_dict().items():
        lines.append(f"  - {dim}: {value:.1f}/100")

    lines.extend([
        f"",
        f"**Assessment Reason**: {report.reasoning}",
        f""
    ])

    return "\n".join(lines)


__all__ = [
    "TestCaseValueEvaluator",
    "TestCaseValueReport",
    "ValueDimensions",
    "TestCaseTag",
    "format_value_report_for_llm"
]
