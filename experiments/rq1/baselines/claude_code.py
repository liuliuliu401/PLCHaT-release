"""
Claude Code / OpenCode-style Agentic Baseline for RQ1 Table 1

This module provides a self-contained baseline that simulates general-purpose
coding agents (like Claude Code or OpenCode) on PLC harness generation tasks.

Key features:
- ReAct-style tool-use loop (bash / write_file / submit)
- LLM-driven "fake user" that closes the feedback loop
- Docker sandbox for isolated execution
- Pipeline metrics: transpilation, compilation, execution

This baseline is self-contained and requires no external libraries.
"""

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_raw"
RESULTS_BASE = PROJECT_ROOT / "output" / "rq1_results" / "claude_code_baseline"

# Default configuration
DEFAULT_API_BASE = "http://localhost:8002/v1"
DEFAULT_MODEL = "qwen2.5-32B-local"
DEFAULT_IMAGE = "sweagent-plc:latest"
DEFAULT_API_KEY = "local"

# Execution parameters
WORK_IN_CONTAINER = "/work"
CMD_TIMEOUT = 60
OBS_LIMIT = 3000
DEFAULT_MAX_STEPS = 30
DEFAULT_USER_TURNS = 2
DEFAULT_TASK_TIMEOUT = 600


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are an autonomous coding agent (like Claude Code / opencode) working in a Linux shell.
You solve the task by issuing EXACTLY ONE action per message. Do not explain at length.

Available actions (respond with a single fenced block):

1. Run a shell command:
```bash
<command>
```

2. Create or overwrite a file (content is written verbatim):
```write <relative/path>
<file content>
```

3. When the task is fully verified, finish with a single line (no fence):
SUBMIT

Rules:
- One action per message. The first fenced block (or SUBMIT) is executed; extra prose is ignored.
- The working directory is /work and already contains the .st source file.
- Read the .st file first, then inspect POUS.h after transpilation for the real struct/function names.
- Verify your solution actually runs before SUBMIT."""


TASK_PROMPT = """# Task: build a runnable C test harness for a Structured Text (ST) PLC program

The working directory /work contains one file: `{st_name}` (IEC 61131-3 Structured Text).

Goal pipeline:
1. Transpile ST to C:  `iec2c -I /usr/local/matiec/lib /work/{st_name}`
   This produces `POUS.c` and `POUS.h` (the compiled function block) in /work.
2. Write `main.c` that instantiates the function block and runs its body for 100 scan cycles,
   then prints exactly `OK: 100` on success. Inspect POUS.h for the real type name and the
   `<FB>_init__` / `<FB>_body__` function signatures.
3. Compile with the provided wrapper:
   `plc_compile -I . POUS.c main.c -o harness_test`
   (`plc_compile` is clang-18 preconfigured with the MatIEC runtime headers.)
4. Run `./harness_test` and confirm it prints `OK: 100` without crashing.

Reference main.c skeleton:
```c
#include <stdio.h>
#include "POUS.h"
int main(void) {{
    FBTYPE fb;
    FBTYPE_init__(&fb, 1);
    for (int i = 0; i < 100; i++) FBTYPE_body__(&fb);
    printf("OK: 100\\n");
    return 0;
}}
```
Replace FBTYPE with the actual type from POUS.h. Begin now."""


USER_DRIVER_SYSTEM = """You are role-playing the *user* who asked a coding agent to build a runnable C test
harness for a PLC program. You are given the objective status of the agent's current attempt.
The agent claimed it was done, but some checkpoints still fail.

Write a SHORT (1-3 sentence) message to the agent, in the voice of a user, that:
- points out which checkpoint is still failing,
- includes the concrete error tail if provided,
- asks the agent to keep going and fix it.
Do NOT solve it for them. Reply with the message text only."""


# --------------------------------------------------------------------------- #
# LLM Client
# --------------------------------------------------------------------------- #

class LLMUnavailable(Exception):
    """Raised when the reasoning endpoint is unreachable."""
    pass


class LLMClient:
    """Simple LLM client for OpenAI-compatible APIs."""

    def __init__(self, api_base: str, model: str, api_key: str):
        self.url = api_base.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.tokens_sent = 0
        self.tokens_received = 0
        self.api_calls = 0

    def chat(self, messages: List[Dict], temperature: float = 0.2,
             max_tokens: int = 2048) -> str:
        """Send a chat completion request."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        try:
            r = requests.post(self.url, json=payload, headers=headers, timeout=180)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage", {}) or {}
            self.tokens_sent += usage.get("prompt_tokens", 0)
            self.tokens_received += usage.get("completion_tokens", 0)
            self.api_calls += 1
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise LLMUnavailable(f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Docker Sandbox
# --------------------------------------------------------------------------- #

class Sandbox:
    """Docker container sandbox for isolated command execution."""

    def __init__(self, image: str, host_workdir: Path):
        self.image = image
        self.host_workdir = host_workdir
        self.name = f"ccbaseline-{uuid.uuid4().hex[:10]}"

    def __enter__(self):
        try:
            subprocess.run(
                ["docker", "run", "-d", "--name", self.name,
                 "-v", f"{self.host_workdir}:{WORK_IN_CONTAINER}",
                 "-w", WORK_IN_CONTAINER, self.image, "sleep", "infinity"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start Docker container: {e.stderr}")
        return self

    def __exit__(self, *exc):
        subprocess.run(["docker", "rm", "-f", self.name],
                      capture_output=True)

    def bash(self, command: str) -> str:
        """Execute a bash command in the container."""
        try:
            proc = subprocess.run(
                ["docker", "exec", self.name, "bash", "-lc",
                 f"timeout {CMD_TIMEOUT} bash -c {self._json_arg(command)}"],
                capture_output=True, text=True, timeout=CMD_TIMEOUT + 15,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode != 0:
                out += f"\n[exit code: {proc.returncode}]"
            return out.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[command timed out after {CMD_TIMEOUT}s]"

    def exists(self, rel_path: str) -> bool:
        """Check if a file exists in the workdir."""
        return (self.host_workdir / self._rel_in_work(rel_path)).exists()

    @staticmethod
    def _json_arg(s: str) -> str:
        """Quote a string for safe use as a bash -c argument."""
        return "'" + s.replace("'", "'\\''") + "'"

    @staticmethod
    def _rel_in_work(path: str) -> str:
        """Normalize a path to be /work-relative."""
        p = path.lstrip("/")
        if p.startswith("work/"):
            p = p[len("work/"):]
        return p


# --------------------------------------------------------------------------- #
# Action Parsing
# --------------------------------------------------------------------------- #

BASH_RE = re.compile(r"```bash\s*\n(.*?)```", re.DOTALL)
WRITE_RE = re.compile(r"```write\s+(\S+)\s*\n(.*?)```", re.DOTALL)


def parse_action(text: str) -> Tuple[str, Optional[Tuple]]:
    """Parse LLM response to extract action.
    Returns (kind, payload) where kind is one of: bash, write, submit, none
    """
    # Check for SUBMIT (not inside a code fence)
    submit_match = re.search(r"(^|\n)\s*SUBMIT\s*($|\n)", text)
    if submit_match and "```" not in text.split("SUBMIT")[0][-50:]:
        if not (BASH_RE.search(text) or WRITE_RE.search(text)):
            return ("submit", None)

    # Check for write or bash
    w = WRITE_RE.search(text)
    b = BASH_RE.search(text)

    candidates = []
    if w:
        candidates.append((w.start(), "write", (w.group(1).strip(), w.group(2))))
    if b:
        candidates.append((b.start(), "bash", b.group(1).strip()))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        _, kind, payload = candidates[0]
        return (kind, payload)

    # Fallback SUBMIT check
    if submit_match:
        return ("submit", None)

    return ("none", None)


# --------------------------------------------------------------------------- #
# Checkpoint Evaluation
# --------------------------------------------------------------------------- #

def evaluate(sandbox: Sandbox) -> Dict:
    """Evaluate pipeline checkpoints objectively."""
    wd = sandbox.host_workdir

    # Checkpoint 1: Transpilation (POUS.c and POUS.h exist)
    transpilation = (wd / "POUS.c").exists() and (wd / "POUS.h").exists()

    # Checkpoint 2: Compilation (binary exists and is executable)
    binary = None
    for cand in ["harness_test", "harness", "a.out", "test", "main"]:
        p = wd / cand
        if p.exists() and os.access(p, os.X_OK) and p.is_file():
            binary = cand
            break
    compilation = binary is not None

    # Checkpoint 3: Execution (prints "OK: 100")
    execution = False
    run_tail = ""
    if binary:
        out = sandbox.bash(f"./{binary}")
        run_tail = out[-400:]
        execution = "OK: 100" in out or re.search(r"OK:\s*100", out) is not None

    return {
        "transpilation_pass": transpilation,
        "compilation_pass": compilation,
        "execution_pass": execution,
        "binary": binary,
        "run_tail": run_tail,
    }


def failing_summary(checkpoint: Dict, sandbox: Sandbox) -> Tuple[Optional[str], str]:
    """Generate human-readable description of first failing checkpoint."""
    if not checkpoint["transpilation_pass"]:
        tail = sandbox.bash("ls -la /work; echo '---'; iec2c -I /usr/local/matiec/lib /work/*.st 2>&1 | tail -5")
        return "transpilation", tail[-500:]
    if not checkpoint["compilation_pass"]:
        tail = sandbox.bash("ls -la /work")
        return "compilation", "No runnable harness binary was produced.\n" + tail[-300:]
    if not checkpoint["execution_pass"]:
        return "execution", "The binary did not print 'OK: 100'. Output tail:\n" + checkpoint["run_tail"]
    return None, ""


def make_fake_user_msg(user_llm: LLMClient, which: str, detail: str) -> str:
    """Generate a fake-user message using LLM."""
    try:
        return user_llm.chat(
            [{"role": "system", "content": USER_DRIVER_SYSTEM},
             {"role": "user", "content": f"Failing checkpoint: {which}\nError tail:\n{detail}"}],
            temperature=0.4, max_tokens=200,
        ).strip()
    except Exception:
        return f"It still fails at the {which} step. Please fix it and verify it runs.\n{detail}"


# --------------------------------------------------------------------------- #
# Result Data Structure
# --------------------------------------------------------------------------- #

@dataclass
class ClaudeCodeResult:
    """Result from Claude Code baseline run."""
    task_id: str
    archetype: str
    transpilation_pass: bool
    compilation_pass: bool
    execution_pass: bool
    steps: int
    user_turns: int
    total_tokens: int
    error: Optional[str] = None
    binary: Optional[str] = None
    run_tail: str = ""

    def to_csv_row(self) -> List[str]:
        return [
            self.task_id,
            self.archetype,
            "PASS" if self.transpilation_pass else "FAIL",
            "PASS" if self.compilation_pass else "FAIL",
            "PASS" if self.execution_pass else "FAIL",
            str(self.steps),
            str(self.user_turns),
            str(self.total_tokens),
            self.error or ""
        ]


# --------------------------------------------------------------------------- #
# Main Runner Class
# --------------------------------------------------------------------------- #

class ClaudeCodeBaseline:
    """Claude Code / OpenCode style baseline runner for RQ1 Table 1.

    This baseline simulates general-purpose coding agents on PLC harness
    generation using a ReAct-style tool loop with LLM-driven feedback.
    """

    def __init__(self, fast_mode: bool = False, **kwargs):
        """Initialize the baseline runner.

        Args:
            fast_mode: Enable fast mode (3 tasks for testing)
            **kwargs: Additional configuration options
                api_base: LLM API base URL
                model: Model name
                api_key: API key
                image: Docker image name
                max_steps: Maximum agent steps per task
                user_turns: Maximum fake-user turns
                timeout: Task timeout in seconds
                no_fake_user: Disable LLM fake-user
        """
        self.fast_mode = fast_mode
        self.project_root = PROJECT_ROOT
        self.benchmark_root = BENCHMARK_ROOT
        self.results_base = RESULTS_BASE

        # Configuration
        self.api_base = kwargs.get("api_base", DEFAULT_API_BASE)
        self.model = kwargs.get("model", DEFAULT_MODEL)
        self.api_key = kwargs.get("api_key", DEFAULT_API_KEY)
        self.image = kwargs.get("image", DEFAULT_IMAGE)
        self.max_steps = kwargs.get("max_steps", DEFAULT_MAX_STEPS)
        self.user_turns = kwargs.get("user_turns", DEFAULT_USER_TURNS)
        self.timeout = kwargs.get("timeout", DEFAULT_TASK_TIMEOUT)
        self.no_fake_user = kwargs.get("no_fake_user", False)

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

    def init_env(self, clean_existing: bool = False):
        """Initialize output directories and CSV file."""
        self.results_base.mkdir(parents=True, exist_ok=True)

        if clean_existing and self.results_table1.exists():
            self.results_table1.unlink()

        # Initialize CSV with headers
        if not self.results_table1.exists():
            with open(self.results_table1, "w", newline="") as f:
                import csv
                writer = csv.writer(f)
                writer.writerow([
                    "TaskID", "Archetype", "Transpilation", "Compilation",
                    "Execution", "Steps", "UserTurns", "TotalTokens", "Error"
                ])

    def list_tasks(self, include: Optional[List[str]] = None,
                  archetype: Optional[str] = None) -> List[str]:
        """List tasks to run, optionally filtered."""
        if include:
            return include
        if archetype:
            return [t for t, i in self.classification.items()
                   if i.get("archetype") == archetype]
        if self.fast_mode:
            return sorted(self.classification.keys())[:3]
        return sorted(self.classification.keys())

    def run_table1_task(self, task_id: str) -> ClaudeCodeResult:
        """Run a single task for Table 1 evaluation.

        Args:
            task_id: Task identifier (e.g., "211_StackMin")

        Returns:
            ClaudeCodeResult with pipeline metrics
        """
        archetype = self.classification.get(task_id, {}).get("archetype", "?")
        src = self.benchmark_root / task_id / "plc_st_files"
        st_files = list(src.glob("*.st")) if src.exists() else []

        if not st_files:
            return ClaudeCodeResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=0,
                user_turns=0,
                total_tokens=0,
                error="no .st file"
            )

        st_file = st_files[0]
        st_name = st_file.name

        # Setup work directory
        workdir = self.results_base / "runs" / task_id
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        shutil.copy(st_file, workdir / st_name)

        # Initialize LLMs
        agent_llm = LLMClient(self.api_base, self.model, self.api_key)
        user_llm = LLMClient(self.api_base, self.model, self.api_key)

        # Initialize messages
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TASK_PROMPT.format(st_name=st_name)},
        ]

        # Run agent loop
        steps = 0
        user_turns = 0
        no_action_strikes = 0
        deadline = time.time() + self.timeout
        final_cp = None

        try:
            with Sandbox(self.image, workdir) as box:
                llm_errors = 0
                while (steps < self.max_steps and time.time() < deadline
                       and user_turns <= self.user_turns):
                    # Get agent action
                    try:
                        reply = agent_llm.chat(messages, temperature=0.2)
                        llm_errors = 0
                    except LLMUnavailable as e:
                        llm_errors += 1
                        if llm_errors >= 3:
                            raise
                        messages.append({
                            "role": "user",
                            "content": f"[system error: {e}; please retry your last action]"
                        })
                        steps += 1
                        time.sleep(2)
                        continue

                    messages.append({"role": "assistant", "content": reply})
                    kind, payload = parse_action(reply)
                    steps += 1

                    # Execute action
                    if kind == "bash":
                        obs = box.bash(payload)[:OBS_LIMIT]
                        messages.append({"role": "user", "content": f"[shell output]\n{obs}"})
                        no_action_strikes = 0

                    elif kind == "write":
                        rel, content = payload
                        rel = Sandbox._rel_in_work(rel)
                        target = workdir / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content)
                        messages.append({"role": "user",
                                       "content": f"[wrote {rel} ({len(content)} bytes)]"})
                        no_action_strikes = 0

                    elif kind == "submit":
                        cp = evaluate(box)
                        final_cp = cp
                        if all([cp["transpilation_pass"],
                               cp["compilation_pass"],
                               cp["execution_pass"]]):
                            break
                        if user_turns >= self.user_turns or self.no_fake_user:
                            break
                        # Fake user closes the loop
                        which, detail = failing_summary(cp, box)
                        user_turns += 1
                        nudge = make_fake_user_msg(user_llm, which, detail)
                        messages.append({"role": "user", "content": nudge})

                    else:  # none
                        no_action_strikes += 1
                        if no_action_strikes >= 3:
                            messages.append({
                                "role": "user",
                                "content": "Reminder: respond with exactly one action block."
                            })
                        else:
                            messages.append({
                                "role": "user",
                                "content": "No executable action found."
                            })

                if final_cp is None:
                    final_cp = evaluate(box)

        except LLMUnavailable as e:
            return ClaudeCodeResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=steps,
                user_turns=user_turns,
                total_tokens=agent_llm.tokens_sent + agent_llm.tokens_received,
                error=f"LLMUnavailable: {e}"
            )
        except Exception as e:
            return ClaudeCodeResult(
                task_id=task_id,
                archetype=archetype,
                transpilation_pass=False,
                compilation_pass=False,
                execution_pass=False,
                steps=steps,
                user_turns=user_turns,
                total_tokens=0,
                error=repr(e)
            )

        # Save trajectory
        try:
            with open(workdir / "trajectory.json", "w") as f:
                json.dump({"messages": messages}, f, indent=2)
        except Exception:
            pass

        return ClaudeCodeResult(
            task_id=task_id,
            archetype=archetype,
            transpilation_pass=final_cp["transpilation_pass"],
            compilation_pass=final_cp["compilation_pass"],
            execution_pass=final_cp["execution_pass"],
            steps=steps,
            user_turns=user_turns,
            total_tokens=(agent_llm.tokens_sent + agent_llm.tokens_received
                         + user_llm.tokens_sent + user_llm.tokens_received),
            binary=final_cp.get("binary"),
            run_tail=final_cp.get("run_tail", "")[-200:]
        )

    def run_table1_batch(self, tasks: Optional[List[str]] = None,
                        archetype: Optional[str] = None) -> List[ClaudeCodeResult]:
        """Run Table 1 tests for a batch of tasks.

        Args:
            tasks: List of task IDs (default: all or fast_mode subset)
            archetype: Filter by archetype (P_alg, P_seq, P_time)

        Returns:
            List of ClaudeCodeResult
        """
        task_ids = self.list_tasks(include=tasks, archetype=archetype)
        results = []

        print(f"\nClaude Code Baseline | model={self.model} image={self.image}")
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
            print(f"  -> {status} | steps={result.steps} "
                 f"user_turns={result.user_turns} tokens={result.total_tokens}")
            if result.error:
                print(f"  Error: {result.error}")

        # Print summary
        n = len(results)
        tp = sum(r.transpilation_pass for r in results)
        cp = sum(r.compilation_pass for r in results)
        ep = sum(r.execution_pass for r in results)
        tok = sum(r.total_tokens for r in results)

        print("\n===== SUMMARY =====")
        print(f"Tasks: {n}")
        print(f"Transpilation: {tp}/{n} ({100*tp/n:.1f}%)")
        print(f"Compilation: {cp}/{n} ({100*cp/n:.1f}%)")
        print(f"Execution: {ep}/{n} ({100*ep/n:.1f}%)")
        print(f"Total tokens: {tok:,} (mean {tok//max(n,1):,}/task)")
        print(f"Results: {self.results_table1}")

        return results

    def _append_result(self, result: ClaudeCodeResult):
        """Append a result to the CSV file."""
        import csv
        with open(self.results_table1, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(result.to_csv_row())
