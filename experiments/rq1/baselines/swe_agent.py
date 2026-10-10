"""
SWE-agent Baseline for RQ1 Table 1

This module provides SWE-agent as a baseline for PLC harness generation.
SWE-agent is a general-purpose coding agent that uses tool-use to solve tasks.

Requirements:
- SWE-agent installation (provided via --external-lib swe-agent=/path/to/swe-agent)
- Docker image sweagent-plc:latest
- MatIEC compiler (included in Docker image)
- Local LLM API (default: http://localhost:8002/v1)

Usage:
    python -m experiments.run rq1 --baseline swe-agent --table1 \\
        --external-lib swe-agent=/path/to/swe-agent

The first run will automatically copy the custom configuration files to the
SWE-agent directory.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_raw"
RESULTS_BASE = PROJECT_ROOT / "output" / "rq1_results" / "swe_agent"

# Default configuration
DEFAULT_TIMEOUT = 300
DEFAULT_MODEL = "qwen2.5-32B-local"
DEFAULT_API_BASE = "http://localhost:8002/v1"
DEFAULT_IMAGE = "sweagent-plc:latest"

# Problem statement template
PROBLEM_STATEMENT = """# Task: Build a Runnable C Test Harness

You are given a Structured Text (ST) PLC program file. Your task is to build a complete, runnable C test harness for this program.

## Goal Pipeline

1. **Transpile ST to C**: Use `iec2c` to compile the ST file to C
   ```bash
   iec2c -I /usr/local/matiec/lib /work/<file>.st
   ```
   This produces `POUS.c` and `POUS.h`

2. **Write main.c**: Create a test harness that:
   - Inspects `POUS.h` to find the actual function block type and function names
   - Instantiates the function block
   - Runs the body function for 100 scan cycles
   - Prints `OK: 100` on success

3. **Compile**: Use the provided `plc_compile` wrapper
   ```bash
   plc_compile -I . POUS.c main.c -o harness_test
   ```

4. **Verify**: Run the binary and confirm it prints `OK: 100` without crashing

## Important Notes

- The working directory is `/work` and contains the ST file
- Read `POUS.h` carefully after transpilation - the actual type names may differ from the ST file name
- The function block typically has `<FB>_init__` and `<FB>_body__` functions
- Use `iec2c` and `plc_compile` - they are preconfigured with the correct paths

## Success Criteria

When you run `./harness_test`, it should print exactly:
```
OK: 100
```

Without any crashes or errors.
"""


@dataclass
class SWEAgentResult:
    """Result from SWE-agent baseline run."""
    task_id: str
    archetype: str
    transpilation_pass: bool
    compilation_pass: bool
    execution_pass: bool
    steps: int
    total_tokens: int
    error: Optional[str] = None

    def to_csv_row(self) -> List[str]:
        return [
            self.task_id,
            self.archetype,
            "PASS" if self.transpilation_pass else "FAIL",
            "PASS" if self.compilation_pass else "FAIL",
            "PASS" if self.execution_pass else "FAIL",
            str(self.steps),
            str(self.total_tokens),
            self.error or ""
        ]


class SWEAgentBaseline:
    """SWE-agent baseline runner for RQ1 Table 1.

    This runner requires:
    - SWE-agent installation (external lib)
    - Docker image sweagent-plc:latest
    - Local LLM API endpoint

    The first run will copy custom configuration to the SWE-agent directory.
    """

    def __init__(self, swe_agent_path: Path, fast_mode: bool = False, **kwargs):
        """Initialize the SWE-agent baseline runner.

        Args:
            swe_agent_path: Path to SWE-agent installation
            fast_mode: Enable fast mode (3 tasks for testing)
            **kwargs: Additional configuration
                timeout: Task timeout in seconds
                model: Model name
                api_base: LLM API base URL
                image: Docker image name
                conda_env: Conda environment name (default: ktransformers)
        """
        self.fast_mode = fast_mode
        self.swe_agent_path = swe_agent_path
        self.project_root = PROJECT_ROOT
        self.benchmark_root = BENCHMARK_ROOT
        self.results_base = RESULTS_BASE

        # Configuration
        self.timeout = kwargs.get("timeout", DEFAULT_TIMEOUT)
        self.model = kwargs.get("model", DEFAULT_MODEL)
        self.api_base = kwargs.get("api_base", DEFAULT_API_BASE)
        self.image = kwargs.get("image", DEFAULT_IMAGE)
        self.conda_env = kwargs.get("conda_env", "ktransformers")

        # Paths
        self.config_file = self.swe_agent_path / "config" / "plc_harness.yaml"
        self.problem_file = self.results_base / "problem_statement.md"

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

    def _setup_config(self):
        """Copy custom configuration to SWE-agent directory if not present."""
        # Check if config already exists
        if self.config_file.exists():
            return

        # Copy custom config from external_configs
        source_config = (self.project_root / "experiments" / "rq1" /
                        "external_configs" / "swe_agent" / "plc_harness.yaml")

        if not source_config.exists():
            raise FileNotFoundError(
                f"Custom config not found at {source_config}. "
                "Please ensure the external_configs directory is intact."
            )

        # Create target directory
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_config, self.config_file)
        print(f"[SWE-agent] Copied custom config to {self.config_file}")

    def _setup_problem_statement(self):
        """Create problem statement file."""
        self.results_base.mkdir(parents=True, exist_ok=True)
        with open(self.problem_file, "w") as f:
            f.write(PROBLEM_STATEMENT)

    def _verify_swe_agent_installation(self) -> bool:
        """Verify that the provided path is a valid SWE-agent installation."""
        if not self.swe_agent_path.exists():
            raise FileNotFoundError(
                f"SWE-agent path does not exist: {self.swe_agent_path}\n"
                f"Please provide a valid path to SWE-agent installation."
            )

        # Check for key SWE-agent files/directories
        required_paths = [
            self.swe_agent_path / "sweagent",
            self.swe_agent_path / "config",
        ]

        missing = [p for p in required_paths if not p.exists()]

        if missing:
            raise FileNotFoundError(
                f"Invalid SWE-agent installation: {self.swe_agent_path}\n"
                f"Missing required files: {', '.join([p.name for p in missing])}\n"
                f"\nA valid SWE-agent installation should contain:\n"
                f"  - sweagent/ (main package)\n"
                f"  - config/ (configuration directory)\n"
                f"\nTo install SWE-agent, visit: https://github.com/princeton-nlp/SWE-agent"
            )

        return True

    def _check_docker_image(self) -> bool:
        """Check if Docker image exists."""
        try:
            result = subprocess.run(
                ["docker", "inspect", self.image],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def _find_python(self) -> Optional[Path]:
        """Find Python executable in conda environment."""
        try:
            # Try conda run
            result = subprocess.run(
                ["conda", "run", "-n", self.conda_env, "which", "python"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except Exception:
            pass

        # Fallback to common paths
        for path in [
            Path(f"/home/{os.environ.get('USER', 'user')}/miniconda3/envs/{self.conda_env}/bin/python"),
            Path(f"/opt/miniconda3/envs/{self.conda_env}/bin/python"),
        ]:
            if path.exists():
                return path

        return None

    def init_env(self, clean_existing: bool = False):
        """Initialize environment and configuration."""
        # Verify SWE-agent installation first
        self._verify_swe_agent_installation()

        self.results_base.mkdir(parents=True, exist_ok=True)

        if clean_existing and self.results_table1.exists():
            self.results_table1.unlink()

        # Setup custom config
        self._setup_config()
        self._setup_problem_statement()

        # Check Docker image
        if not self._check_docker_image():
            print(f"[SWE-agent] Warning: Docker image {self.image} not found")
            print(f"  Build with: docker build -t {self.image} "
                  f"-f experiments/rq1/external_configs/swe_agent/Dockerfile /path/to/matiec")

        # Initialize CSV
        if not self.results_table1.exists():
            with open(self.results_table1, "w", newline="") as f:
                import csv
                writer = csv.writer(f)
                writer.writerow([
                    "TaskID", "Archetype", "Transpilation", "Compilation",
                    "Execution", "Steps", "TotalTokens", "Error"
                ])

    def list_tasks(self, include: Optional[List[str]] = None) -> List[str]:
        """List tasks to run."""
        if include:
            return include
        if self.fast_mode:
            return sorted(self.classification.keys())[:3]
        return sorted(self.classification.keys())

    def _setup_task_dir(self, task_id: str) -> Path:
        """Create a temporary directory with the task's ST file as a git repo."""
        task_src = self.benchmark_root / task_id
        st_dir = task_src / "plc_st_files"
        st_files = list(st_dir.glob("*.st")) if st_dir.exists() else []

        if not st_files:
            raise FileNotFoundError(f"No ST files found for {task_id}")

        # Create temp directory
        task_dir = Path(tempfile.mkdtemp(prefix=f"swe_rq1_{task_id}_"))

        # Copy ST file
        for stf in st_files:
            shutil.copy(stf, task_dir / stf.name)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=task_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "swe@test.local"],
                      cwd=task_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "SWE-agent"],
                      cwd=task_dir, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=task_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"],
                      cwd=task_dir, capture_output=True)

        return task_dir

    def _cleanup_docker(self):
        """Stop all SWE-agent Docker containers."""
        try:
            subprocess.run(
                "docker stop $(docker ps -aq --filter name=sweagent) 2>/dev/null",
                shell=True, capture_output=True, timeout=10
            )
        except Exception:
            pass

    def run_table1_task(self, task_id: str) -> SWEAgentResult:
        """Run a single task for Table 1 evaluation.

        Args:
            task_id: Task identifier (e.g., "211_StackMin")

        Returns:
            SWEAgentResult with pipeline metrics
        """
        archetype = self.classification.get(task_id, {}).get("archetype", "?")

        # Setup task directory
        try:
            task_dir = self._setup_task_dir(task_id)
        except FileNotFoundError as e:
            return SWEAgentResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=0,
                total_tokens=0,
                error=str(e)
            )

        # Setup output directory
        output_dir = self.results_base / "runs" / task_id
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)

        # Find Python
        python = self._find_python()
        if python is None:
            return SWEAgentResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=0,
                total_tokens=0,
                error="Python not found in conda environment"
            )

        # Run SWE-agent
        env = {
            **os.environ,
            "OPENAI_API_KEY": "local",
            "PYTHONPATH": str(self.swe_agent_path),
        }

        cmd = [
            str(python), "-m", "sweagent", "run",
            "--config", str(self.config_file),
            "--env.deployment.image", self.image,
            "--env.repo.path", str(task_dir),
            "--problem_statement.path", str(self.problem_file),
            "--output_dir", str(output_dir),
        ]

        try:
            subprocess.run(
                cmd,
                cwd=self.project_root,
                env=env,
                timeout=self.timeout,
                capture_output=True,
                text=True
            )
        except subprocess.TimeoutExpired:
            self._cleanup_docker()
            shutil.rmtree(task_dir, ignore_errors=True)
            return SWEAgentResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=0,
                total_tokens=0,
                error="timeout"
            )
        except Exception as e:
            self._cleanup_docker()
            shutil.rmtree(task_dir, ignore_errors=True)
            return SWEAgentResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=0,
                total_tokens=0,
                error=str(e)[:100]
            )

        # Cleanup
        self._cleanup_docker()
        shutil.rmtree(task_dir, ignore_errors=True)
        time.sleep(1)

        # Parse result
        return self._parse_result(task_id, output_dir, archetype)

    def _parse_result(self, task_id: str, output_dir: Path,
                     archetype: str) -> SWEAgentResult:
        """Parse SWE-agent trajectory to extract results."""
        result = SWEAgentResult(
            task_id=task_id,
            archetype=archetype,
            transpilation_pass=False,
            compilation_pass=False,
            execution_pass=False,
            steps=0,
            total_tokens=0
        )

        try:
            for d in output_dir.iterdir():
                traj_file = d / f"{d.name}.traj"
                if d.is_dir() and traj_file.exists():
                    t = json.load(open(traj_file))
                    ms = t.get("info", {}).get("model_stats", {})
                    s = t.get("trajectory", [])

                    # Check for transpilation success
                    result.transpilation_pass = any(
                        "POUS.c" in x.get("observation", "") and
                        "POUS.h" in x.get("observation", "")
                        for x in s
                    )

                    # Check for execution success
                    result.execution_pass = any(
                        "OK: 100" in x.get("observation", "")
                        for x in s
                    )

                    # Compilation is implicit if execution succeeds
                    result.compilation_pass = result.execution_pass

                    result.steps = len(s)
                    result.total_tokens = ms.get("tokens_sent", 0) + ms.get("tokens_received", 0)
                    break
        except Exception as e:
            result.error = f"parse_error: {str(e)[:50]}"

        return result

    def run_table1_batch(self, tasks: Optional[List[str]] = None) -> List[SWEAgentResult]:
        """Run Table 1 tests for a batch of tasks."""
        task_ids = self.list_tasks(include=tasks)
        results = []

        print(f"\nSWE-agent Baseline | model={self.model} image={self.image}")
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
            print(f"  -> {status} | steps={result.steps} tokens={result.total_tokens}")
            if result.error:
                print(f"  Error: {result.error}")

        # Print summary
        n = len(results)
        tp = sum(r.transpilation_pass for r in results)
        cp = sum(r.compilation_pass for r in results)
        ep = sum(r.execution_pass for r in results)
        tt = sum(r.total_tokens for r in results)

        print("\n===== SUMMARY =====")
        print(f"Tasks: {n}")
        print(f"Transpilation: {tp}/{n} ({100*tp/n:.1f}%)")
        print(f"Compilation: {cp}/{n} ({100*cp/n:.1f}%)")
        print(f"Execution: {ep}/{n} ({100*ep/n:.1f}%)")
        print(f"Total tokens: {tt:,} (mean {tt//max(n,1):,}/task)")
        print(f"Results: {self.results_table1}")

        return results

    def _append_result(self, result: SWEAgentResult):
        """Append a result to the CSV file."""
        import csv
        with open(self.results_table1, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(result.to_csv_row())
