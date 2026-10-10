"""
PLCHaT Coverage Analyzer

Intelligent coverage feedback extraction.

Key features:
- Extract covered/missed line IDs from coverage reports
- Build contiguous missed code blocks with context
- Generate intelligent coverage feedback for Agent analysis
"""

import re
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

from harness.compiler.utils import Logger, LEVEL
from core.data_types import CoverageSummary, CoverageReport


@dataclass
class MissedCodeBlock:
    """A contiguous block of missed code lines with context."""
    file: str
    start_line: int
    end_line: int
    missed_lines: List[int] = field(default_factory=list)
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)


@dataclass
class CoverageIntelligence:
    """Intelligent coverage feedback for Agent analysis."""
    covered_ids: List[str] = field(default_factory=list)  # Minimal, for compatibility
    missed_lines: List[str] = field(default_factory=list)  # Top missed lines
    missed_blocks: List[MissedCodeBlock] = field(default_factory=list)  # Contextual blocks
    coverage_percentage: Optional[str] = None


class CoverageAnalyzer:
    """
    Analyzes coverage reports and extracts intelligent feedback.

    This migrates the _extract_ids_from_coverage_report and _generate_covered_ids
    functionality from the original st_coverage.py.
    """

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger or Logger("/tmp/plchat", "coverage_analyzer.log", level=LEVEL.WARNING)

    def extract_intelligent_feedback(
        self,
        coverage_report_file: str,
        max_missed_lines: int = 10,
        max_covered_ids: int = 5
    ) -> CoverageIntelligence:
        """
        Extract intelligent coverage feedback from report file.

        Args:
            coverage_report_file: Path to target_function_coverage.txt
            max_missed_lines: Maximum number of missed lines to return
            max_covered_ids: Maximum number of covered IDs to return

        Returns:
            CoverageIntelligence with extracted feedback
        """
        intelligence = CoverageIntelligence()

        if not os.path.exists(coverage_report_file):
            self.logger.warning_print(f"Coverage report not found: {coverage_report_file}")
            return intelligence

        try:
            extracted = self._extract_ids_from_coverage_report(coverage_report_file)

            # Extract top missed lines (limit to prevent overflow)
            intelligence.missed_lines = extracted.get("missed", [])[:max_missed_lines]

            # Covered IDs - keep minimal for compatibility
            intelligence.covered_ids = extracted.get("covered", [])[:max_covered_ids]

            # Extract missed blocks with context
            intelligence.missed_blocks = extracted.get("missed_blocks", [])

        except Exception as e:
            self.logger.warning_print(f"Error extracting coverage intelligence: {e}")

        return intelligence

    def _extract_ids_from_coverage_report(self, report_file: str) -> Dict[str, Any]:
        """
        Extract specific line IDs from detailed coverage report.

        Groups contiguous missed lines into contextual blocks for Agent analysis.

        Migrated from: st_coverage.py::_extract_ids_from_coverage_report
        """
        result = {"covered": [], "missed": [], "missed_blocks": []}

        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            current_file = None
            file_lines = []

            # Step 1: Extract all valid lines
            for raw_line in lines:
                line_clean = raw_line.strip()

                # Detect file headers (format: "filename:")
                if line_clean.endswith(':') and not line_clean.startswith('|'):
                    file_path = line_clean.rstrip(':')
                    if file_path.endswith('.c') or file_path.endswith('.st'):
                        filename = file_path.split('/')[-1]
                        # Skip library files
                        if "iec_" in filename or "accessor" in filename or "harness" in filename:
                            current_file = None
                        else:
                            current_file = filename
                    continue

                # Parse coverage lines (format: "line | count | code")
                if current_file and '|' in line_clean and not line_clean.startswith('-'):
                    if line_clean.startswith('|'):
                        continue  # Skip separator lines

                    parts = line_clean.split('|', 2)
                    if len(parts) >= 3:
                        line_num = parts[0].strip()
                        count = parts[1].strip()
                        code = parts[2].strip()

                        if line_num.isdigit():
                            file_lines.append((current_file, int(line_num), count, code))

            # Step 2: Build contiguous missed code blocks with context
            result["missed_blocks"] = self._build_missed_blocks(file_lines)

            # Step 3: Extract covered and missed line IDs
            for fname, lnum, count, code in file_lines:
                is_meaningful = (
                    len(code) > 2 and
                    not code.startswith('//') and
                    code not in ["{", "}", "};"]
                )

                if not is_meaningful:
                    continue

                line_id = f"{fname}:{lnum}"

                if count == '0':
                    result["missed"].append(line_id)
                else:
                    result["covered"].append(line_id)

        except Exception as e:
            self.logger.warning_print(f"Error parsing coverage report: {e}")

        return result

    def _build_missed_blocks(
        self,
        file_lines: List[Tuple[str, int, str, str]]
    ) -> List[Dict[str, Any]]:
        """
        Build contiguous missed code blocks with context.

        Args:
            file_lines: List of (filename, line_num, count, code) tuples

        Returns:
            List of missed block dictionaries
        """
        missed_blocks = []
        current_block = None

        for i, (fname, lnum, count, code) in enumerate(file_lines):
            # Filter meaningful lines
            is_meaningful = (
                len(code) > 2 and
                not code.startswith('//') and
                code not in ["{", "}", "};"]
            )
            if not is_meaningful:
                continue

            if count == '0':
                # Start or continue a missed block
                if current_block is None or current_block["file"] != fname:
                    # Finalize previous block
                    if current_block is not None:
                        missed_blocks.append(current_block)

                    # Start new block with context
                    current_block = {
                        "file": fname,
                        "start_line": lnum,
                        "end_line": lnum,
                        "missed_lines": [lnum],
                        "context_before": [],
                        "code_snippets": [code]
                    }

                    # Look back for covered context (max 2 lines)
                    context = []
                    back_idx = i - 1
                    while back_idx >= 0 and len(context) < 2:
                        b_fname, b_lnum, b_count, b_code = file_lines[back_idx]
                        if b_fname != fname:
                            break
                        b_meaningful = (
                            len(b_code) > 2 and
                            not b_code.startswith('//') and
                            b_code not in ["{", "}", "};"]
                        )
                        if b_meaningful and b_count != '0':
                            context.append(f"  {b_lnum}| {b_code}")
                        back_idx -= 1

                    current_block["context_before"] = list(reversed(context))

                else:
                    # Continue current block
                    current_block["end_line"] = lnum
                    current_block["missed_lines"].append(lnum)
                    current_block["code_snippets"].append(code)
            else:
                # Finalize block if we hit covered code
                if current_block is not None:
                    missed_blocks.append(current_block)
                    current_block = None

        # Don't forget the last block
        if current_block is not None:
            missed_blocks.append(current_block)

        return missed_blocks

    def calculate_coverage_percentage(
        self,
        summary: Optional[CoverageSummary]
    ) -> Optional[str]:
        """Extract coverage percentage from summary."""
        if summary and summary.line_coverage:
            return summary.line_coverage.percentage
        return None

    def format_feedback_for_agent(
        self,
        intelligence: CoverageIntelligence,
        summary: Optional[CoverageSummary] = None
    ) -> str:
        """
        Format coverage feedback for Agent consumption.

        Returns a structured string with coverage information.
        """
        lines = []

        # Overall coverage
        if summary and summary.line_coverage:
            lines.append(f"Line Coverage: {summary.line_coverage.percentage}")
            lines.append(f"  Covered: {summary.line_coverage.covered}/{summary.line_coverage.total}")

        # Missed blocks (most useful for Agent)
        if intelligence.missed_blocks:
            lines.append("\nMissed Code Blocks:")
            for i, block in enumerate(intelligence.missed_blocks[:5], 1):
                lines.append(f"\n  Block {i}: {block['file']}:{block['start_line']}-{block['end_line']}")

                # Context before
                if block.get("context_before"):
                    lines.append("  Context (covered):")
                    for ctx in block["context_before"]:
                        lines.append(f"    {ctx}")

                # Missed lines
                if block.get("code_snippets"):
                    lines.append("  Missed code:")
                    for snippet in block["code_snippets"]:
                        lines.append(f"    X | {snippet}")

        return "\n".join(lines)
