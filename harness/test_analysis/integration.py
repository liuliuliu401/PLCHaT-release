"""
Test case analysis main entry

Integrate all components and provide a unified interface.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any
import logging
import os

# Project root: integration.py → test_analysis → harness → PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

# Debug print function (controlled by environment variable)
def debug_print(msg):
    if os.environ.get('PLCHAT_DEBUG', '0') == '1':
        print(f"[DEBUG-INT] {msg}", flush=True)

# global relative position reference
from harness.test_analysis.intent.intent_provider import IntentProvider
from harness.test_analysis.assertion.llm_assertion_designer import LLMAssertionDesigner
from harness.test_analysis.assertion.patch_inserter import AssertionPatcher
from harness.compiler.generator.interface_extractor import InterfaceExtractor

# Data type
from core.data_types.test_analysis_types import TestCaseReport


@dataclass
class TestAnalysisResult:
    """Test analysis result"""
    original_harness: Path
    patched_harness: Path
    assertion_code: str
    test_intent: str


def analyze_and_patch(
    st_path: Path,
    harness_path: Path,
    test_intent: str = None
) -> TestAnalysisResult:
    """
# Analyze test cases and generate patched harness.

    Args:
st_path: ST source code path
harness_path: original harness.c path
test_intent: optional test intent

    Returns:
TestAnalysisResult: Contains patched harness path and assertion code
    """
    logger = logging.getLogger(__name__)
    logger.info(f"=== Analyzing test case: {st_path.stem} ===")

    # Phase 1: Get test intent
    intent_provider = IntentProvider(logger)
    intent = intent_provider.get_intent(st_path, test_intent)

    # Phase 2: Get POU information
    extractor = InterfaceExtractor()
    pou_info = extractor.extract(st_path)

    # Phase 3: Design assertions (v3: learns variable access from existing harness.c)
    assertion_designer = LLMAssertionDesigner(logger)
    assertion_code = assertion_designer.design_assertions(
        st_path, pou_info, intent,
        existing_harness_path=harness_path  # KEY: v3 learns correct variable access patterns
    )

    # Phase 4: Insert assertions
    patcher = AssertionPatcher(logger)
    patch_result = patcher.insert_assertions(
        harness_path,
        assertion_code,
        pou_info.pou_name_upper
    )

    logger.info(f"=== Analysis complete, patched harness: {patch_result.patched_path.name} ===")

    return TestAnalysisResult(
        original_harness=harness_path,
        patched_harness=patch_result.patched_path,
        assertion_code=assertion_code.c_code,
        test_intent=intent.description
    )


@dataclass
class TestCaseAnalyzer:
    """Test case analyzer class - supports multiple analyses."""
    st_path: Path
    harness_path: Path
    logger: logging.Logger = None
    work_dir: Path = None  # Work directory, used to store intermediate files (POUS.c, POUS.h, etc.)

    def __post_init__(self):
        """Initialize component"""
        self.intent_provider = IntentProvider(self.logger)
        # Use a dedicated log file
        log_file = None
        if self.work_dir:
            log_file = self.work_dir / "assertion_generation.log"
        self.assertion_designer = LLMAssertionDesigner(self.logger, log_file=str(log_file) if log_file else None)
        self.patcher = AssertionPatcher(self.logger)
        self.extractor = InterfaceExtractor()

        # cache
        self._pou_info = None
        self._pous_c_path = None

    def analyze(self, test_intent: str = None, work_dir: Path = None) -> TestAnalysisResult:
        """Analyze test cases."""
        debug_print(f"analyze() called: st_path={self.st_path.stem}")

        # Determine the working directory
        output_dir = work_dir if work_dir else self.work_dir
        if not output_dir:
            output_dir = self.harness_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        debug_print(f"output_dir: {output_dir}")

        # Step 1: Compile ST to generate POUS.c and POUS.h
        if self._pous_c_path is None:
            debug_print("Step 1: Compiling ST to C...")
            from harness.compiler.executor import STExecutor
            executor = STExecutor(root_dir=str(PROJECT_ROOT), logger=self.logger, debug=False)

            # Compile ST to C using MatIEC
            temp_compile_dir = output_dir / "temp_compile"
            temp_compile_dir.mkdir(exist_ok=True)

            self.logger.info(f"Compiling ST to generate POUS.c/POUS.h: {self.st_path}")
            debug_print(f"Calling compile_st_to_c: {self.st_path}")
            st_ok = executor.compile_st_to_c(
                st_code_path=str(self.st_path),
                output_dir=str(temp_compile_dir),
                harness_path="/dev/null"  # No need for harness, only need POUS file
            )
            debug_print(f"compile_st_to_c returned: {st_ok}")

            if st_ok:
                self._pous_c_path = temp_compile_dir / "POUS.c"
                self._pous_h_path = temp_compile_dir / "POUS.h"
                self.logger.info(f"POUS.c generated successfully: {self._pous_c_path}")
                debug_print(f"POUS files: {self._pous_c_path}, {self._pous_h_path}")
            else:
                self.logger.warning(f"POUS.c generation failed, continuing analysis")
                self._pous_c_path = None
                self._pous_h_path = None

        # Step 2: Get POU information (prefer using generated POUS.h)
        debug_print("Step 2: Extracting POU info...")
        if self._pou_info is None:
            if self._pous_h_path and self._pous_h_path.exists():
                self._pou_info = self.extractor.extract(self.st_path, self._pous_h_path)
                debug_print(f"POU info extracted from POUS.h")
            else:
                self._pou_info = self.extractor.extract(self.st_path)
                debug_print(f"POU info extracted from ST")

        # Step 3: Get test intent
        debug_print("Step 3: Getting test intent...")
        intent = self.intent_provider.get_intent(self.st_path, test_intent, self._pou_info)
        debug_print(f"Test intent: {intent.description[:50]}...")

        # Step 4: Design assertions (v4: Pass the POUS.c path to extract call logic)
        debug_print("Step 4: Designing assertions...")
        assertion_code = self.assertion_designer.design_assertions(
            self.st_path, self._pou_info, intent,
            existing_harness_path=self.harness_path,
            pous_c_path=self._pous_c_path  # Pass the POUS.c path
        )
        debug_print(f"Assertions designed: {len(assertion_code.c_code)} chars")

        # Step 5: Insert assertion
        debug_print("Step 5: Inserting assertions...")
        patch_result = self.patcher.insert_assertions(
            self.harness_path,
            assertion_code,
            self._pou_info.pou_name_upper,
            output_dir=output_dir,
            pous_h_path=getattr(self, "_pous_h_path", None)
        )

        return TestAnalysisResult(
            original_harness=self.harness_path,
            patched_harness=patch_result.patched_path,
            assertion_code=assertion_code.c_code,
            test_intent=intent.description
        )


__all__ = [
    "analyze_and_patch",
    "TestCaseAnalyzer",
    "TestAnalysisResult",
]
