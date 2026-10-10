"""
PLCHaT Evaluation Types
Data structures for evaluation reports and results.
"""

from dataclasses import dataclass, asdict, is_dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class EvaluationReport:
    """Corrected evaluation report structure matching actual system requirements."""
    test_suite_id: str
    coverage_summary: Dict[str, Any] = field(default_factory=dict)
    problems: List[Dict[str, Any]] = field(default_factory=list)
    recommendation: Dict[str, Any] = field(default_factory=dict)
    raw_execution_data: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_planner_context(self) -> Dict[str, Any]:
        """
        Adapter: Flattens the report into a clean context dictionary for the Planner.
        """
        # Helper for robust extraction (Object vs Dict)
        def get_val(obj, key, default=None):
            if obj is None: return default
            return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

        # 1. Coverage
        line_cov = "N/A"
        branch_cov = "N/A"
        if self.coverage_summary:
            l_data = get_val(self.coverage_summary, "line_coverage")
            b_data = get_val(self.coverage_summary, "branch_coverage")
            line_cov = get_val(l_data, "percentage", "N/A")
            branch_cov = get_val(b_data, "percentage", "N/A")

        # 2. Problems
        problem_snippets = []
        for p in self.problems[:3]:  # Top 3 only
            ptype = p.get("type", "Issue")
            ploc = p.get("location", "unknown")
            problem_snippets.append(f"{ptype}@{ploc}")

        # 3. Recommendation
        rec_type = "N/A"
        rec_target = "N/A"
        if self.recommendation:
            # Structure: {'recommendation': {'type': ..., 'target': ...}}
            inner = self.recommendation.get("recommendation", {})
            rec_type = inner.get("type", "N/A")
            rec_target = inner.get("target", "N/A")

        return {
            "coverage_line": line_cov,
            "coverage_branch": branch_cov,
            "problem_count": len(self.problems),
            "problem_list": problem_snippets,
            "rec_type": rec_type,
            "rec_target": rec_target
        }
