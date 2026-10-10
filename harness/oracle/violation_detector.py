"""
PLCHaT Violation Detector (Oracle Layer ℱ)

Violation detection system for PLC execution results.
Detects hard violations (crashes, timeouts) and soft violations (keyword patterns).

Key features:
- Hard violation detection (crash/timeout)
- Soft violation detection (keyword matching)
- Violation diagnostic tuple generation
- Structured violation reporting
"""

import os
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

# Add parent directory to path for imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from harness.compiler.utils import Logger, LEVEL
from core.data_types.execution_coverage import STExecutionResult, ExecutionStatus


class ViolationSeverity(Enum):
    """Severity levels for violations."""
    CRITICAL = "critical"  # Hard violations that prevent execution
    HIGH = "high"  # Serious violations that may affect correctness
    MEDIUM = "medium"  # Moderate violations that should be investigated
    LOW = "low"  # Minor violations that are informational
    INFO = "info"  # Informational findings


class ViolationType(Enum):
    """Types of violations."""
    # Hard violations
    CRASH = "crash"  # Process crashed
    TIMEOUT = "timeout"  # Execution timed out
    COMPILATION_FAILED = "compilation_failed"  # Compilation failed
    BUILD_FAILED = "build_failed"  # Build/link failed

    # Soft violations (keyword-based)
    ASSERTION_FAILED = "assertion_failed"  # Assertion failed
    ERROR_DETECTED = "error_detected"  # Error keyword detected
    OVERFLOW_DETECTED = "overflow_detected"  # Overflow detected
    SEGFAULT = "segfault"  # Segmentation fault
    DIVIDE_BY_ZERO = "divide_by_zero"  # Division by zero
    NULL_POINTER = "null_pointer"  # Null pointer dereference
    BUFFER_OVERFLOW = "buffer_overflow"  # Buffer overflow
    MEMORY_ERROR = "memory_error"  # Memory error

    # Other violations
    ABNORMAL_VALUE = "abnormal_value"  # Abnormal variable value
    STATE_INCONSISTENCY = "state_inconsistency"  # State inconsistency detected
    UNEXPECTED_BEHAVIOR = "unexpected_behavior"  # Unexpected behavior


@dataclass
class Violation:
    """
    Represents a single violation detected during execution.

    Attributes:
        violation_type: Type of violation
        severity: Severity level
        message: Human-readable violation message
        location: Location where violation occurred (cycle, file, etc.)
        evidence: Evidence supporting the violation
        diagnostic_info: Additional diagnostic information
    """
    violation_type: ViolationType
    severity: ViolationSeverity
    message: str
    location: Optional[Dict[str, Any]] = None
    evidence: Optional[str] = None
    diagnostic_info: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "violation_type": self.violation_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "evidence": self.evidence,
            "diagnostic_info": self.diagnostic_info
        }


@dataclass
class ViolationReport:
    """
    Complete violation report for an execution.

    Attributes:
        execution_status: Overall execution status
        total_violations: Total number of violations
        violations_by_type: Violations grouped by type
        violations_by_severity: Violations grouped by severity
        critical_violations: List of critical violations
        summary: Human-readable summary
    """
    execution_status: ExecutionStatus
    total_violations: int = 0
    violations: List[Violation] = field(default_factory=list)
    violations_by_type: Dict[str, List[Violation]] = field(default_factory=dict)
    violations_by_severity: Dict[str, List[Violation]] = field(default_factory=dict)

    @property
    def critical_violations(self) -> List[Violation]:
        """Get all critical violations."""
        return self.violations_by_severity.get("critical", [])

    def add_violation(self, violation: Violation) -> None:
        """Add a violation to the report."""
        self.violations.append(violation)
        self.total_violations += 1

        # Group by type
        type_key = violation.violation_type.value
        if type_key not in self.violations_by_type:
            self.violations_by_type[type_key] = []
        self.violations_by_type[type_key].append(violation)

        # Group by severity
        severity_key = violation.severity.value
        if severity_key not in self.violations_by_severity:
            self.violations_by_severity[severity_key] = []
        self.violations_by_severity[severity_key].append(violation)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "execution_status": self.execution_status,
            "total_violations": self.total_violations,
            "violations": [v.to_dict() for v in self.violations],
            "violations_by_type": {
                k: [v.to_dict() for v in violations]
                for k, violations in self.violations_by_type.items()
            },
            "violations_by_severity": {
                k: [v.to_dict() for v in violations]
                for k, violations in self.violations_by_severity.items()
            },
            "summary": self._generate_summary()
        }

    def _generate_summary(self) -> str:
        """Generate human-readable summary."""
        if self.total_violations == 0:
            return "No violations detected. Execution completed successfully."

        lines = [f"Detected {self.total_violations} violation(s):"]

        # Group by severity
        for severity in ["critical", "high", "medium", "low"]:
            violations = self.violations_by_severity.get(severity, [])
            if violations:
                types = set(v.violation_type.value for v in violations)
                lines.append(f"  - {severity.upper()}: {len(violations)} violation(s) ({', '.join(types)})")

        return "\n".join(lines)


class ViolationDetector:
    """
    Violation detection system for PLC execution results.

    Detects both hard violations (crashes, timeouts) and soft violations
    (keyword patterns in output, abnormal values).
    """

    # Keyword patterns for soft violation detection
    SOFT_VIOLATION_PATTERNS = {
        ViolationType.ASSERTION_FAILED: [
            r"assertion.*failed",
            r"assert.*failed",
            r"ASSERTION.*FAILED",
            r"AssertionError"
        ],
        ViolationType.ERROR_DETECTED: [
            r"\berror\b",
            r"\bERROR\b",
            r"\bError\b"
        ],
        ViolationType.OVERFLOW_DETECTED: [
            r"overflow",
            r"Overflow",
            r"OVERFLOW"
        ],
        ViolationType.SEGFAULT: [
            r"segfault",
            r"segmentation fault",
            r"Segmentation fault"
        ],
        ViolationType.DIVIDE_BY_ZERO: [
            r"divide by zero",
            r"division by zero",
            r"DivisionByZero"
        ],
        ViolationType.NULL_POINTER: [
            r"null pointer",
            r"NULL pointer",
            r"nullptr"
        ],
        ViolationType.BUFFER_OVERFLOW: [
            r"buffer overflow",
            r"Buffer overflow",
            r"stack overflow"
        ],
        ViolationType.MEMORY_ERROR: [
            r"memory error",
            r"out of memory",
            r"Out of memory"
        ]
    }

    def __init__(
        self,
        logger: Optional[Logger] = None,
        debug: bool = False,
        custom_keywords: Optional[Dict[str, List[str]]] = None
    ):
        """
        Initialize violation detector.

        Args:
            logger: Logger instance
            debug: Enable debug logging
            custom_keywords: Custom keyword patterns for violation detection
        """
        self.logger = logger or Logger("/tmp/plchat_violation_detector_logs", "violation_detector.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug

        # Compile regex patterns for efficiency
        self.compiled_patterns = {}
        for vtype, patterns in self.SOFT_VIOLATION_PATTERNS.items():
            self.compiled_patterns[vtype] = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]

        # Add custom patterns if provided
        if custom_keywords:
            for keyword, patterns in custom_keywords.items():
                try:
                    vtype = ViolationType(keyword)
                    self.compiled_patterns[vtype] = [
                        re.compile(pattern, re.IGNORECASE) for pattern in patterns
                    ]
                except ValueError:
                    self.logger.warning_print(f"Unknown violation type: {keyword}")

    def detect_violations(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0
    ) -> ViolationReport:
        """
        Detect violations in execution result.

        Args:
            execution_result: Execution result to analyze
            test_case_index: Index of test case to analyze

        Returns:
            ViolationReport with all detected violations
        """
        self.logger.info_print(f"Detecting violations in test case {test_case_index}")

        report = ViolationReport(execution_status=execution_result.status)

        # Detect hard violations (status-based)
        self._detect_hard_violations(execution_result, report)

        # Detect soft violations (keyword-based)
        self._detect_soft_violations(execution_result, report)

        # Detect abnormal value violations
        if test_case_index < len(execution_result.test_cases):
            self._detect_abnormal_values(execution_result, test_case_index, report)

        self.logger.info_print(f"Violation detection complete: {report.total_violations} violation(s) found")

        return report

    def _detect_hard_violations(
        self,
        execution_result: STExecutionResult,
        report: ViolationReport
    ) -> None:
        """Detect hard violations based on execution status."""
        status = execution_result.status

        if status == "compilation_failed":
            violation = Violation(
                violation_type=ViolationType.COMPILATION_FAILED,
                severity=ViolationSeverity.CRITICAL,
                message="Compilation failed",
                location={"return_code": execution_result.return_code},
                evidence=execution_result.raw_stderr,
                diagnostic_info={"return_code": execution_result.return_code}
            )
            report.add_violation(violation)

        elif status == "build_failed":
            violation = Violation(
                violation_type=ViolationType.BUILD_FAILED,
                severity=ViolationSeverity.CRITICAL,
                message="Build/link failed",
                location={"return_code": execution_result.return_code},
                evidence=execution_result.raw_stderr,
                diagnostic_info={"return_code": execution_result.return_code}
            )
            report.add_violation(violation)

        elif status == "timeout":
            violation = Violation(
                violation_type=ViolationType.TIMEOUT,
                severity=ViolationSeverity.HIGH,
                message="Execution timed out",
                location={"return_code": execution_result.return_code},
                evidence=execution_result.message or execution_result.raw_stderr
            )
            report.add_violation(violation)

        elif status == "error" or status == "execution_failed":
            # Check if it's a crash (non-zero return code with specific patterns)
            if execution_result.return_code < 0:
                violation = Violation(
                    violation_type=ViolationType.CRASH,
                    severity=ViolationSeverity.CRITICAL,
                    message="Process crashed",
                    location={"return_code": execution_result.return_code},
                    evidence=execution_result.raw_stderr or execution_result.message
                )
                report.add_violation(violation)

    def _detect_soft_violations(
        self,
        execution_result: STExecutionResult,
        report: ViolationReport
    ) -> None:
        """Detect soft violations based on keyword patterns in output."""
        text_to_check = execution_result.raw_stderr + "\n" + execution_result.raw_stdout

        for vtype, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                matches = pattern.finditer(text_to_check)
                for match in matches:
                    # Extract context around the match
                    line_start = text_to_check.rfind('\n', 0, match.start()) + 1
                    line_end = text_to_check.find('\n', match.end())
                    if line_end == -1:
                        line_end = len(text_to_check)
                    context_line = text_to_check[line_start:line_end].strip()

                    violation = Violation(
                        violation_type=vtype,
                        severity=self._get_severity_for_type(vtype),
                        message=f"Keyword pattern matched: {vtype.value}",
                        location={"pattern": pattern.pattern, "line": context_line},
                        evidence=context_line,
                        diagnostic_info={"match": match.group(), "pattern": pattern.pattern}
                    )
                    report.add_violation(violation)

    def _detect_abnormal_values(
        self,
        execution_result: STExecutionResult,
        test_case_index: int,
        report: ViolationReport
    ) -> None:
        """Detect abnormal values in execution results."""
        if test_case_index >= len(execution_result.test_cases):
            return

        test_case = execution_result.test_cases[test_case_index]

        for cycle in test_case.cycles:
            # Check VAR_OUTPUT for abnormal values
            for var_name, value in cycle.after_execution.VAR_OUTPUT.items():
                if self._is_abnormal_value(value):
                    violation = Violation(
                        violation_type=ViolationType.ABNORMAL_VALUE,
                        severity=ViolationSeverity.MEDIUM,
                        message=f"Abnormal value detected in output variable",
                        location={
                            "cycle": cycle.cycle,
                            "variable": var_name,
                            "section": "VAR_OUTPUT"
                        },
                        evidence=f"{var_name} = {value}",
                        diagnostic_info={"value": str(value), "type": str(type(value))}
                    )
                    report.add_violation(violation)

            # Check VAR_INTERNAL for abnormal values
            for var_name, value in cycle.after_execution.VAR_INTERNAL.items():
                if self._is_abnormal_value(value):
                    violation = Violation(
                        violation_type=ViolationType.ABNORMAL_VALUE,
                        severity=ViolationSeverity.MEDIUM,
                        message=f"Abnormal value detected in internal variable",
                        location={
                            "cycle": cycle.cycle,
                            "variable": var_name,
                            "section": "VAR_INTERNAL"
                        },
                        evidence=f"internal.{var_name} = {value}",
                        diagnostic_info={"value": str(value), "type": str(type(value))}
                    )
                    report.add_violation(violation)

    def _is_abnormal_value(self, value: Any) -> bool:
        """Check if a value is abnormal (NaN, infinity, etc.)."""
        try:
            if isinstance(value, float):
                import math
                if math.isnan(value) or math.isinf(value):
                    return True
            return False
        except:
            return False

    def _get_severity_for_type(self, vtype: ViolationType) -> ViolationSeverity:
        """Get default severity for a violation type."""
        severity_mapping = {
            ViolationType.ASSERTION_FAILED: ViolationSeverity.HIGH,
            ViolationType.ERROR_DETECTED: ViolationSeverity.MEDIUM,
            ViolationType.OVERFLOW_DETECTED: ViolationSeverity.HIGH,
            ViolationType.SEGFAULT: ViolationSeverity.CRITICAL,
            ViolationType.DIVIDE_BY_ZERO: ViolationSeverity.HIGH,
            ViolationType.NULL_POINTER: ViolationSeverity.HIGH,
            ViolationType.BUFFER_OVERFLOW: ViolationSeverity.CRITICAL,
            ViolationType.MEMORY_ERROR: ViolationSeverity.HIGH,
            ViolationType.ABNORMAL_VALUE: ViolationSeverity.MEDIUM,
        }
        return severity_mapping.get(vtype, ViolationSeverity.LOW)

    def generate_diagnostic_tuple(
        self,
        violation: Violation
    ) -> Tuple[str, str, Any]:
        """
        Generate diagnostic tuple for a violation.

        Returns:
            Tuple of (violation_type, severity, evidence)
        """
        return (
            violation.violation_type.value,
            violation.severity.value,
            violation.evidence or violation.message
        )

    def check_for_safety_violations(
        self,
        execution_result: STExecutionResult,
        safety_critical_vars: Optional[List[str]] = None
    ) -> List[Violation]:
        """
        Check for safety-critical violations.

        Args:
            execution_result: Execution result to check
            safety_critical_vars: List of safety-critical variable names to monitor

        Returns:
            List of safety-related violations
        """
        self.logger.info_print("Checking for safety violations")

        safety_violations = []

        if not safety_critical_vars:
            return safety_violations

        for test_case in execution_result.test_cases:
            for cycle in test_case.cycles:
                # Check safety-critical variables for abnormal states
                for var_name in safety_critical_vars:
                    if var_name in cycle.after_execution.VAR_OUTPUT:
                        value = cycle.after_execution.VAR_OUTPUT[var_name]
                        if self._is_safety_violation(var_name, value):
                            violation = Violation(
                                violation_type=ViolationType.STATE_INCONSISTENCY,
                                severity=ViolationSeverity.CRITICAL,
                                message=f"Safety-critical variable in invalid state",
                                location={
                                    "cycle": cycle.cycle,
                                    "variable": var_name
                                },
                                evidence=f"{var_name} = {value}",
                                diagnostic_info={"value": str(value)}
                            )
                            safety_violations.append(violation)

        return safety_violations

    def _is_safety_violation(self, var_name: str, value: Any) -> bool:
        """
        Check if a safety-critical variable is in an invalid state.

        This is a placeholder implementation. Actual implementation
        should be customized for specific safety standards.
        """
        # Example: Check for negative values in variables that should be positive
        if isinstance(value, (int, float)) and value < 0:
            # Assume safety-critical variables starting with 'safety_' should be positive
            if var_name.startswith('safety_') or var_name.endswith('_safe'):
                return True

        return False
