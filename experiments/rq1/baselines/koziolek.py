"""
Koziolek Baseline for RQ1 Table 1

This module provides the LLM-CodeGen-TestGen (Koziolek et al.) baseline for
PLC test generation. This baseline uses template-based harness generation
rather than LLM-based generation.

Key features:
- Template-based test harness (TestRunnerProgram + CONFIGURATION)
- MatIEC ST→C transpilation
- GCC compilation with coverage instrumentation
- Execution and coverage collection

Requirements:
- LLM-CodeGen-TestGen installation (provided via --external-lib koziolek=/path/to/LLM-CodeGen-TestGen)
- MatIEC compiler (provided via --external-lib matiec=/path/to/matiec)

Usage:
    python -m experiments.run rq1 --baseline koziolek --table1 \\
        --external-lib koziolek=/path/to/LLM-CodeGen-TestGen \\
        --external-lib matiec=/path/to/matiec
"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_raw"
RESULTS_BASE = PROJECT_ROOT / "output" / "rq1_results" / "koziolek"

# Templates
TEST_RUNNER_TEMPLATE = """PROGRAM TestRunnerProgram
VAR
  testResult AT %QX0.0 : BOOL := FALSE;
END_VAR
VAR
  totalTests AT %QW0 : INT := 0;
  passedTests AT %QW1 : INT := 0;
END_VAR
  totalTests := 1;
  passedTests := 1;
  testResult := TRUE;
END_PROGRAM
"""

CONFIG_TEMPLATE = """CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#100ms,PRIORITY := 0);
    PROGRAM instance0 WITH task0 : TestRunnerProgram;
  END_RESOURCE
END_CONFIGURATION
"""


@dataclass
class KoziolekResult:
    """Result from Koziolek baseline run."""
    task_id: str
    archetype: str
    transpilation_pass: bool
    compilation_pass: bool
    execution_pass: bool
    coverage_pass: bool
    error: Optional[str] = None

    def to_csv_row(self) -> List[str]:
        return [
            self.task_id,
            self.archetype,
            "PASS" if self.transpilation_pass else "FAIL",
            "PASS" if self.compilation_pass else "FAIL",
            "PASS" if self.execution_pass else "FAIL",
            "PASS" if self.coverage_pass else "FAIL",
            self.error or ""
        ]


class KoziolekBaseline:
    """Koziolek et al. baseline runner for RQ1 Table 1.

    This baseline uses template-based test harness generation from
    LLM-CodeGen-TestGen, combining the original ST program with
    a test runner program.

    Requires:
    - LLM-CodeGen-TestGen directory (for main.c and plc.c templates)
    - MatIEC compiler (for ST→C transpilation)
    """

    def __init__(self, koziolek_path: Path, matiec_path: Path,
                 fast_mode: bool = False, **kwargs):
        """Initialize the Koziolek baseline runner.

        Args:
            koziolek_path: Path to LLM-CodeGen-TestGen directory
            matiec_path: Path to MatIEC installation
            fast_mode: Enable fast mode (3 tasks for testing)
            **kwargs: Additional configuration options
        """
        self.fast_mode = fast_mode
        self.koziolek_path = koziolek_path
        self.matiec_path = matiec_path
        self.project_root = PROJECT_ROOT
        self.benchmark_root = BENCHMARK_ROOT
        self.results_base = RESULTS_BASE

        # MatIEC paths
        self.iec2c = matiec_path / "iec2c"
        self.matiec_lib = matiec_path / "lib"
        self.matiec_lib_c = matiec_path / "lib" / "C"

        # Template files from LLM-CodeGen-TestGen
        self.template_main = koziolek_path / "Output" / "main.c"
        self.template_plc = koziolek_path / "Output" / "plc.c"

        # Results file
        self.results_table1 = self.results_base / "table1.csv"

        # Load task classification
        self.classification = self._load_classification()

    def _load_classification(self) -> Dict:
        """Load task classification from benchmark."""
        cls_file = self.benchmark_root / "task_classification.json"
        if cls_file.exists():
            with open(cls_file) as f:
                return json.load(f)
        return {}

    def _verify_prerequisites(self):
        """Verify that required files and directories exist."""
        # Check MatIEC compiler
        if not self.iec2c.exists():
            raise FileNotFoundError(
                f"MatIEC iec2c not found at {self.iec2c}\n"
                f"Please ensure --external-lib matiec={self.matiec_path} points to a valid MatIEC installation.\n"
                f"Or install MatIEC using: ./scripts/install_matiec.sh"
            )
        if not self.matiec_lib.exists():
            raise FileNotFoundError(
                f"MatIEC lib not found at {self.matiec_lib}\n"
                f"Please ensure --external-lib matiec={self.matiec_path} points to a valid MatIEC installation."
            )

        # Check LLM-CodeGen-TestGen installation
        if not self.koziolek_path.exists():
            raise FileNotFoundError(
                f"LLM-CodeGen-TestGen path does not exist: {self.koziolek_path}\n"
                f"Please provide a valid path to LLM-CodeGen-TestGen installation."
            )

        if not self.template_main.exists():
            raise FileNotFoundError(
                f"main.c template not found at {self.template_main}\n"
                f"Invalid LLM-CodeGen-TestGen installation: missing Output/main.c\n"
                f"Please ensure --external-lib koziolek={self.koziolek_path} points to a valid installation."
            )
        if not self.template_plc.exists():
            raise FileNotFoundError(
                f"plc.c template not found at {self.template_plc}\n"
                f"Invalid LLM-CodeGen-TestGen installation: missing Output/plc.c\n"
                f"Please ensure --external-lib koziolek={self.koziolek_path} points to a valid installation."
            )

    def init_env(self, clean_existing: bool = False):
        """Initialize environment and verify prerequisites."""
        # Verify prerequisites first (early validation)
        self._verify_prerequisites()

        self.results_base.mkdir(parents=True, exist_ok=True)

        if clean_existing and self.results_table1.exists():
            self.results_table1.unlink()

        # Initialize CSV
        if not self.results_table1.exists():
            with open(self.results_table1, "w", newline="") as f:
                import csv
                writer = csv.writer(f)
                writer.writerow([
                    "TaskID", "Archetype", "Transpilation", "Compilation",
                    "Execution", "Coverage", "Error"
                ])

    def list_tasks(self, include: Optional[List[str]] = None) -> List[str]:
        """List tasks to run."""
        if include:
            return include
        if self.fast_mode:
            return sorted(self.classification.keys())[:3]
        return sorted(self.classification.keys())

    def run_table1_task(self, task_id: str) -> KoziolekResult:
        """Run a single task for Table 1 evaluation.

        Args:
            task_id: Task identifier (e.g., "211_StackMin")

        Returns:
            KoziolekResult with pipeline metrics
        """
        archetype = self.classification.get(task_id, {}).get("archetype", "?")

        # Get ST file
        st_dir = self.benchmark_root / task_id / "plc_st_files"
        st_files = list(st_dir.glob("*.st")) if st_dir.exists() else []

        if not st_files:
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error="no ST file"
            )

        st_file = st_files[0]

        # Create task work directory
        task_work_dir = self.results_base / "runs" / task_id
        if task_work_dir.exists():
            shutil.rmtree(task_work_dir)
        task_work_dir.mkdir(parents=True)

        # Create Output subdirectory (working directory for compilation)
        output_dir = task_work_dir / "Output"
        output_dir.mkdir()

        # Copy template files
        try:
            shutil.copy(self.template_main, output_dir / "main.c")
            shutil.copy(self.template_plc, output_dir / "plc.c")
        except FileNotFoundError as e:
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error=f"template_missing: {e}"
            )

        # Step 1: Create complete ST program
        try:
            fb_content = st_file.read_text()
            full_st = fb_content + "\n\n" + TEST_RUNNER_TEMPLATE + "\n" + CONFIG_TEMPLATE
            test_st = task_work_dir / "TEST_PROGRAM.st"
            test_st.write_text(full_st)
        except Exception as e:
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error=f"st_read_error: {e}"
            )

        # Step 2: ST → C (MatIEC transpilation)
        original_cwd = os.getcwd()
        os.chdir(output_dir)

        try:
            iec2c_cmd = [
                str(self.iec2c),
                '-Ol',
                '-I', str(self.matiec_lib),
                '../TEST_PROGRAM.st'
            ]

            result = subprocess.run(
                iec2c_cmd,
                cwd=output_dir,
                capture_output=True,
                text=True,
                timeout=30
            )

            transpilation_pass = result.returncode == 0

            if not transpilation_pass:
                # Save error output
                (output_dir / "iec2c_error.txt").write_text(
                    f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
                )
                return KoziolekResult(
                    task_id=task_id,
                    archetype=archetype,
                    transpilation_pass=False,
                    compilation_pass=False,
                    execution_pass=False,
                    coverage_pass=False,
                    error=f"iec2c_failed (exit {result.returncode})"
                )

        except subprocess.TimeoutExpired:
            os.chdir(original_cwd)
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error="iec2c_timeout"
            )
        except Exception as e:
            os.chdir(original_cwd)
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error=f"iec2c_error: {e}"
            )
        finally:
            os.chdir(original_cwd)

        # Step 3: C → Binary (GCC compilation)
        try:
            lib_c = str(self.matiec_lib_c)
            gcc_cmd = [
                'gcc',
                '-I', lib_c,
                '-fprofile-arcs',
                '-ftest-coverage'
            ]

            # Add all C files
            c_files = ['Config0.c', 'Res0.c', 'plc.c', 'main.c']
            for f in c_files:
                if (output_dir / f).exists():
                    gcc_cmd.append(f)

            gcc_cmd.extend(['-o', 'softplc', '-lm', '-lrt'])

            result = subprocess.run(
                gcc_cmd,
                cwd=output_dir,
                capture_output=True,
                text=True,
                timeout=30
            )

            compilation_pass = result.returncode == 0

            if not compilation_pass:
                (output_dir / "gcc_error.txt").write_text(
                    f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
                )
                return KoziolekResult(
                    task_id=task_id,
                    archetype=archetype,
                    transpilation_pass=True,
                    compilation_pass=False,
                    execution_pass=False,
                    coverage_pass=False,
                    error="gcc_failed"
                )

        except subprocess.TimeoutExpired:
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=True,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error="gcc_timeout"
            )
        except Exception as e:
            return KoziolekResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=True,
                compilation_pass=False,
                execution_pass=False,
                coverage_pass=False,
                error=f"gcc_error: {e}"
            )

        # Step 4: Execution
        binary_path = output_dir / "softplc"
        try:
            result = subprocess.run(
                ['stdbuf', '-oL', str(binary_path)],
                cwd=output_dir,
                capture_output=True,
                text=True,
                timeout=10
            )

            # Save output
            (output_dir / "output.txt").write_text(
                f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
            )

            output_content = result.stdout + result.stderr
            execution_pass = result.returncode == 0 and "Tick" in output_content

        except subprocess.TimeoutExpired:
            execution_pass = False
        except Exception as e:
            execution_pass = False

        # Step 5: Coverage check
        gcda_files = list(output_dir.glob("*.gcda"))
        gcno_files = list(output_dir.glob("*.gcno"))
        coverage_pass = len(gcda_files) > 0 and len(gcno_files) > 0

        return KoziolekResult(
            task_id=task_id,
            archetype=archetype,
            transpilation_pass=transpilation_pass,
            compilation_pass=compilation_pass,
            execution_pass=execution_pass,
            coverage_pass=coverage_pass
        )

    def run_table1_batch(self, tasks: Optional[List[str]] = None) -> List[KoziolekResult]:
        """Run Table 1 tests for a batch of tasks."""
        task_ids = self.list_tasks(include=tasks)
        results = []

        print(f"\nKoziolek Baseline | matiec={self.matiec_path}")
        print(f"Running {len(task_ids)} task(s)\n")

        for i, task_id in enumerate(task_ids):
            arch = self.classification.get(task_id, {}).get("archetype", "?")
            print(f"[{i+1}/{len(task_ids)}] {task_id} ({arch}) ...", flush=True)

            result = self.run_table1_task(task_id)
            results.append(result)

            # Append to CSV
            self._append_result(result)

            # Print status
            status = ("EXEC OK" if result.execution_pass else
                     "COMPILE OK" if result.compilation_pass else
                     "TRANSPILE OK" if result.transpilation_pass else "FAIL")
            print(f"  -> {status} | coverage={result.coverage_pass}")
            if result.error:
                print(f"  Error: {result.error}")

        # Print summary
        n = len(results)
        tp = sum(r.transpilation_pass for r in results)
        cp = sum(r.compilation_pass for r in results)
        ep = sum(r.execution_pass for r in results)
        cvp = sum(r.coverage_pass for r in results)

        print("\n===== SUMMARY =====")
        print(f"Tasks: {n}")
        print(f"Transpilation: {tp}/{n} ({100*tp/n:.1f}%)")
        print(f"Compilation: {cp}/{n} ({100*cp/n:.1f}%)")
        print(f"Execution: {ep}/{n} ({100*ep/n:.1f}%)")
        print(f"Coverage: {cvp}/{n} ({100*cvp/n:.1f}%)")
        print(f"Results: {self.results_table1}")

        return results

    def _append_result(self, result: KoziolekResult):
        """Append a result to the CSV file."""
        import csv
        with open(self.results_table1, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(result.to_csv_row())
