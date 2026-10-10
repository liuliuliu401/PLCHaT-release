#!/usr/bin/env python3
"""RQ3 Ablation Runner v3 — Causal feedback + KeyFrame distillation."""

import sys, os, json, time, argparse, uuid, shutil, re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import core.llm_patch  # noqa

from harness.compiler.st_coverage_collector import STCoverageCollector
from harness.compiler.coverage import CoverageAnalyzer
from harness.compiler.utils import Logger, LEVEL
from harness.oracle import ViolationDetector
from harness.test_analysis.key_frame_extractor import KeyFrameExtractor, format_key_frames_for_llm
from core.data_types.exp_types import ExpUnifiedIR
from core.token_tracker import TokenTracker
from tools.fuzzers.random.generator import RandomCaseGenerator
from agents.generator import Generator
from agents.prompts import GeneratorPrompts

BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_raw"
BENCHMARK_MUTATED = PROJECT_ROOT / "benchmark" / "benchmark_260113" / "benchmark_mutated"
RESULT_OUTPUT = PROJECT_ROOT / "results" / "rq3"

IEC2C_BIN = shutil.which("iec2c")
MATIEC_PATH = str(Path(IEC2C_BIN).parent) if IEC2C_BIN else "/usr/local/bin"
MATIEC_LIB = os.environ.get("MATIEC_C_LIB_DIR", os.path.join(MATIEC_PATH, "lib", "C"))


def log(msg: str):
    print(f"[RQ3] {datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


# ============================================================================
# Config
# ============================================================================

class AblationConfig:
    CONFIGS = {
        "C1": {"distill": True,  "truncate": False, "oracle": True,  "metrics": True},
        "C2": {"distill": False, "truncate": True,  "oracle": True,  "metrics": True},
        "C3": {"distill": False, "truncate": False, "oracle": True,  "metrics": True},
        "C4": {"distill": True,  "truncate": False, "oracle": False, "metrics": True},
        "E_raw": {"distill": False, "truncate": False, "oracle": False, "metrics": False},
        "C0":    {"distill": False, "truncate": False, "oracle": False, "metrics": False},
    }

    def __init__(self, config_id: str):
        cfg = self.CONFIGS.get(config_id)
        if cfg is None:
            raise ValueError(f"Unknown config: {config_id}")
        self.id = config_id
        self.enable_distillation = cfg["distill"]
        self.enable_truncate = cfg["truncate"]
        self.enable_oracle = cfg["oracle"]
        self.enable_metrics = cfg["metrics"]


# ============================================================================
# Runner
# ============================================================================

class RQ3Runner:
    def __init__(self, task_id: str, config: AblationConfig, work_dir: Path, logger: Logger,
                 mutation_task: str = None):
        self.task_id = task_id; self.config = config; self.work_dir = work_dir
        self.logger = logger; self.mutation_task = mutation_task
        self.ground_truth_harness = None

        if mutation_task:
            mut_base = BENCHMARK_MUTATED / mutation_task
            self.st_path = mut_base / "plc_st_files" / f"{task_id}.st"
            self.schema_path = mut_base / "input" / "input_schema_v2.json"
            from harness.compiler.generator.pipeline import HarnessPipeline
            clean_dir = self.work_dir / "clean_harness"; clean_dir.mkdir(parents=True, exist_ok=True)
            pl = HarnessPipeline(logger=self.logger)
            r = pl.synthesize(self.st_path, clean_dir)
            self.harness_path = clean_dir / "harness.c" if r.success else mut_base / "plc_c_files" / "harness.c"
            self.ground_truth_harness = mut_base / "plc_c_files" / "harness.c"
            # Use the schema generated alongside the clean harness (matches its input
            # column layout), NOT the stale mutation-dir schema which may have fewer columns.
            harness_schema = self.harness_path.parent / "input_schema_v2.json"
            if harness_schema.exists(): self.schema_path = harness_schema
        else:
            self.st_path = BENCHMARK_ROOT / task_id / "plc_st_files" / f"{task_id}.st"
            self.schema_path = BENCHMARK_ROOT / task_id / "input" / "input_schema_v2.json"
            self.harness_path = BENCHMARK_ROOT / task_id / "plc_c_files" / "harness.c"
            if not self.harness_path.exists():
                alt = PROJECT_ROOT / "results" / "rq3_clean_harnesses" / task_id / "harness.c"
                if alt.exists(): self.harness_path = alt
            harness_schema = self.harness_path.parent / "input_schema_v2.json"
            if harness_schema.exists(): self.schema_path = harness_schema

        for p, n in [(self.st_path, "ST"), (self.schema_path, "Schema"), (self.harness_path, "Harness")]:
            if not p.exists():
                raise FileNotFoundError(f"{n} not found: {p}")

        self.st_code = self.st_path.read_text(encoding='utf-8')
        with open(self.schema_path) as f:
            self.schema = json.load(f)

        # Parse variable categories
        self.var_categories = {}
        current_is_input = False; current_is_output = False
        for line in self.st_code.split('\n'):
            line_upper = line.upper().strip()
            if line_upper.startswith('VAR_INPUT'): current_is_input = True
            elif line_upper.startswith('VAR_OUTPUT'): current_is_output = True
            elif line_upper.startswith('END_VAR'): current_is_input = False; current_is_output = False
            elif current_is_input or current_is_output:
                m = re.match(r'\s*(\w+)\s*:', line)
                if m:
                    self.var_categories[m.group(1).lower()] = 'Input' if current_is_input else 'Output'

        self.coverage_collector = STCoverageCollector(root_dir=str(PROJECT_ROOT), logger=self.logger,
                                                       default_output_format="StoredTestCase", llvm_version=18)
        self.violation_detector = ViolationDetector(logger=self.logger)
        self.keyframe_extractor = KeyFrameExtractor()

        # Token accounting: snapshot BEFORE assertion generation so that BOTH the
        # assertion-gen LLM calls AND the later test-case-gen agent calls are counted.
        self._tok_start = TokenTracker.get().snapshot()

        # Assertion generation
        self.assertion_count = 0
        self.assertion_descriptions: List[str] = []
        self.assertion_compilation_pass = False
        self.asserted_harness_path = None
        try:
            self._init_assertions()
        except Exception as e:
            self.logger.warning_print(f"Assertion skipped: {e}")
        _ta = TokenTracker.get().snapshot()
        self._assertion_token_input = _ta["input_tokens"] - self._tok_start["input_tokens"]
        self._assertion_token_output = _ta["output_tokens"] - self._tok_start["output_tokens"]

        # Generator agent
        gen_dir = self.work_dir / "gen_env" / self.task_id
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "plc_st_files").mkdir(exist_ok=True)
        (gen_dir / "input").mkdir(exist_ok=True)
        shutil.copy2(self.st_path, gen_dir / "plc_st_files" / f"{self.task_id}.st")
        shutil.copy2(self.schema_path, gen_dir / "input" / "input_schema_v2.json")
        self.generator = Generator(st_path=str(gen_dir / "plc_st_files" / f"{self.task_id}.st"),
                                    benchmark_dir=str(self.work_dir / "gen_env"))
        # NOTE: do NOT reset TokenTracker here — assertion-gen tokens must stay in the total.

        self.coverage_history: List[float] = []
        self.violations: List[Dict] = []
        self.assertion_triggers: int = 0
        self._last_case_summaries = []
        self._last_assertion_msgs = []
        self._last_exec_raw = ""
        self._last_stdout_full = ""
        self._trigger_map = {}
        self._reduced_repros = []
        self._all_cases = []
        self._total_cycles = 0
        self._triggered_assertions = set()
        self._triggered_cases = []  # accumulated cases that triggered assertions (newest first, for suite-reduction random pick)
        self._last_timeouts = 0     # cases timing out (>30s) in the main flow this round
        self._total_timeouts = 0    # cumulative main-flow timeout cases
        self._exam_pool = ThreadPoolExecutor(max_workers=2)  # background threads for per-round exams (concurrency limit = 2)
        self._exam_futures = []     # [(label, future)] background evaluation of each case batch
        self._tools_used_total = {}  # cumulative LLM tool calls (process differences)

    def _init_assertions(self):
        from harness.test_analysis.integration import TestCaseAnalyzer
        from harness.compiler.executor import STExecutor
        analyzer = TestCaseAnalyzer(st_path=self.st_path, harness_path=self.harness_path,
                                     logger=self.logger, work_dir=self.work_dir)
        result = analyzer.analyze(work_dir=self.work_dir)
        if result and result.patched_harness:
            src = Path(result.patched_harness)
            dst = self.work_dir / "harness_assertioned.c"
            if src.resolve() != dst.resolve(): shutil.copy2(src, dst)
            else: dst = src
            self.asserted_harness_path = dst
            if result.assertion_code:
                self.assertion_count = result.assertion_code.count("fflush(stderr)")
            try:
                self.assertion_descriptions = self._extract_assertion_descriptions(dst.read_text(encoding='utf-8'))
                if self.assertion_descriptions:
                    self.assertion_count = len(self.assertion_descriptions)
            except Exception as e:
                self.logger.warning_print(f"Assertion desc extract failed: {e}")
            from harness.compiler.executor import STExecutor
            executor = STExecutor(root_dir=str(PROJECT_ROOT), logger=self.logger, debug=False)
            tmp = self.work_dir / "assertion_build"; tmp.mkdir(exist_ok=True)
            if executor.compile_st_to_c(str(self.st_path), str(tmp), "/dev/null"):
                shutil.copy(dst, tmp / "harness.c")
                c_files = list(tmp.glob("*.c"))
                ok = executor.compile_c_to_binary([str(f) for f in c_files],
                    str(tmp / "plc_harness_assertioned"), [MATIEC_LIB, str(tmp)], [], False)
                self.assertion_compilation_pass = ok

    # ── Feedback builders ──

    def _build_context(self, iteration: int) -> Dict[str, Any]:
        if iteration == 1 or not self.coverage_history:
            return {"iteration": iteration, "first_round": True}
        if not self._last_case_summaries:
            return {"iteration": iteration, "first_round": True}
        
        cases = self._last_case_summaries
        prev_cov = self.coverage_history[-1]
        prev_cov_prev = self.coverage_history[-2] if len(self.coverage_history) >= 2 else 0
        trigger_msgs = list(set(self._last_assertion_msgs))
        
        if self.config.id in ("C1", "C4"):
            lines = self._build_C1(cases, trigger_msgs, prev_cov, prev_cov_prev)
            # Same 2000-character context budget as C2: the distillation group packs higher-density information into the same budget
            full = "\n".join(lines)
            if len(full) > 2000:
                lines = [full[:2000] + f"\n... (truncated, {len(full)-2000} more chars)"]
        elif self.config.id == "C2":
            lines = self._build_C3(cases, trigger_msgs, prev_cov, prev_cov_prev)
            full = "\n".join(lines)
            if len(full) > 2000:
                lines = [full[:2000] + f"\n... (truncated, {len(full)-2000} more chars)"]
        elif self.config.id == "E_raw":
            lines = self._build_Eraw(cases, trigger_msgs, prev_cov, prev_cov_prev)
        elif self.config.id == "C0":
            lines = self._build_C0()
        else:
            lines = self._build_C3(cases, trigger_msgs, prev_cov, prev_cov_prev)
        
        return {"iteration": iteration, "causal_feedback": "\n".join(lines),
                "current_coverage": prev_cov / 100.0}

    @staticmethod
    def _extract_assertion_descriptions(harness_text: str) -> List[str]:
        """Parse human-readable assertion descriptions from the assertioned C harness.
        Descriptions are taken verbatim from the SECURITY_ASSERTION_FAILED messages
        (printf format specifiers normalised to <N>). Never hardcoded."""
        descs = []
        for m in re.finditer(r'SECURITY_ASSERTION_FAILED:\s*([^"\\]*)', harness_text):
            d = re.sub(r'%[-#0-9.l]*[diuoxXeEfFgGsc]', '<N>', m.group(1)).strip()
            if d and d not in descs:
                descs.append(d)
        return descs

    def _assertion_block(self) -> List[str]:
        """Print the concrete assertion conditions (parsed from C, not hardcoded)."""
        if not self.assertion_descriptions:
            return [f"## Assertions: {self.assertion_count} active"]
        out = [f"## Assertions ({len(self.assertion_descriptions)} active — try to VIOLATE these):"]
        for i, d in enumerate(self.assertion_descriptions, 1):
            out.append(f"  A{i}: {d}")
        return out

    def _timeout_note(self) -> List[str]:
        """Main-flow timeout feedback: honestly tell the LLM these cases produced no results due to execution timeout (>30s)."""
        if self._last_timeouts > 0:
            return [f"## ⚠ {self._last_timeouts} case(s) TIMED OUT (>30s) and were NOT measured "
                    f"(no result, not because they failed). Generate SHORTER, non-looping "
                    f"multi-cycle inputs that terminate quickly."]
        return []

    def _parse_exec_by_case(self, stdout: str) -> List[Dict[int, Dict[str, str]]]:
        """Split harness stdout into per-case timelines, indexed by case order.
        The collector prefixes each case with 'Test case i output:' (authoritative
        boundary); a cycle reset to 1 is a fallback boundary. ALL variable state
        (inputs, outputs, intermediate) is taken from the execution output, so inputs
        and outputs are inherently aligned per cycle (no IR/output mismatch)."""
        cases: List[Dict[int, Dict[str, str]]] = []
        cur: Dict[int, Dict[str, str]] = {}
        cur_c = None; cur_d: Dict[str, str] = {}

        def close_cycle():
            nonlocal cur_c, cur_d
            if cur_c is not None and cur_d:
                cur[cur_c] = dict(cur_d)
            cur_c = None; cur_d = {}

        for line in stdout.split('\n'):
            line = line.strip()
            if re.match(r'Test case \d+ output:', line):
                close_cycle()
                if cur:
                    cases.append(cur); cur = {}
                continue
            if line.startswith('--- Cycle'):
                close_cycle()
                try:
                    n = int(line.split('Cycle')[1].replace('-', ' ').split()[0])
                except Exception:
                    n = None
                if n == 1 and cur:  # fallback boundary when no explicit marker
                    cases.append(cur); cur = {}
                cur_c = n
            elif ':' in line and not any(t in line for t in
                                         ('SECURITY', 'AUDIT', 'ASSERTION', 'Test case')):
                k, v = line.split(':', 1)
                cur_d[k.strip().lower()] = v.strip()
        close_cycle()
        if cur:
            cases.append(cur)
        return cases

    def _parse_triggers_by_case(self, stderr: str) -> Dict[int, Dict[int, List[str]]]:
        """Map assertioned-run stderr to {case_idx: {cycle: [msg, ...]}}.
        Stderr is grouped per case ('Test case i errors:'); within a case each trigger
        prints a SECURITY_ASSERTION_FAILED line immediately followed by the call-site's
        'ASSERTION_RESULT=.. ASSERTION_CYCLE=N' line (same stream, preserved order)."""
        out: Dict[int, Dict[int, List[str]]] = {}
        case_idx = -1
        pending: List[str] = []
        for line in stderr.split('\n'):
            ls = line.strip()
            m = re.match(r'Test case (\d+) error', ls)
            if m:
                case_idx = int(m.group(1)); pending = []
                continue
            if 'SECURITY_ASSERTION_FAILED' in ls:
                pending.append(ls[ls.find('SECURITY'):].strip()[:200])
            elif 'ASSERTION_CYCLE=' in ls:
                cm = re.search(r'ASSERTION_CYCLE=(\d+)', ls)
                if cm and pending:
                    cyc = int(cm.group(1))
                    bucket = out.setdefault(case_idx, {}).setdefault(cyc, [])
                    for msg in pending:
                        if msg not in bucket:
                            bucket.append(msg)
                    pending = []
        return out

    def _render_case_cycles(self, seg: Dict[int, Dict[str, str]], cycles: List[int],
                            triggers: Optional[Dict[int, List[str]]] = None,
                            indent: str = "  ") -> List[str]:
        """Render per-cycle Input/Output/State, all sourced from execution output.
        A triggered assertion (if any) is shown at the EXACT cycle it fired in."""
        triggers = triggers or {}
        lines = []
        for cyc in cycles:
            vals = seg.get(cyc, {})
            if not vals and cyc not in triggers:
                continue
            inp = {}; out = {}; oth = {}
            for var, v in vals.items():
                cat = self.var_categories.get(var.lower(), 'Other')
                (inp if cat == 'Input' else out if cat == 'Output' else oth)[var] = str(v)[:24]
            lines.append(f"{indent}Cycle {cyc}:")
            if inp: lines.append(f"{indent}  Input:  {inp}")
            if out: lines.append(f"{indent}  Output: {out}")
            if oth: lines.append(f"{indent}  State:  {oth}")
            for t in triggers.get(cyc, []):
                lines.append(f"{indent}  ⚠ TRIGGERED HERE: {t}")
        return lines

    def _reduce_cycles(self, seg: Dict[int, Dict[str, str]], cycles: List[int]) -> List[int]:
        """Honest distillation: keep cycles where output/key-state changes vs previous."""
        kept = []; prev = None
        for k in cycles:
            cur = seg.get(k, {})
            sig = tuple(sorted((kk, vv) for kk, vv in cur.items()
                               if self.var_categories.get(kk.lower()) == 'Output'
                               or kk.lower() in ('top', 'status', 'error', 'minindex', 'minvalue')))
            if prev is None or sig != prev:
                kept.append(k)
            prev = sig
        return kept or cycles

    def _persist_cases(self, iteration: int, cases: List[Any]):
        """Persist every generated case's RAW input (sparse_timeline) for this iteration
        so any post-hoc analysis (coverage re-measure, ddmin suite, GT verify ...) can be
        rebuilt OFFLINE without re-running the campaign. One JSON per case under
        cases/iter_NNNN/case_IIII.json (~200-500 bytes each). Called after generation but
        BEFORE execution so the inputs survive even if a later exec step crashes."""
        try:
            cdir = self.work_dir / "cases" / f"iter_{iteration:04d}"
            cdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.logger.warning_print(f"  persist mkdir failed: {e}"); return
        n = 0
        for idx, c in enumerate(cases):
            tl = getattr(c, "sparse_timeline", None)
            if not tl:
                continue
            rec = {
                "exp_id": getattr(c, "exp_id", f"case_{idx}"),
                "tester_type": getattr(c, "tester_type", ""),
                "total_cycles": getattr(c, "total_cycles", len(tl)),
                "target_st_path": str(self.st_path),
                "schema_path": str(self.schema_path),
                "sparse_timeline": {str(k): v for k, v in tl.items()},
            }
            try:
                with open(cdir / f"case_{idx:04d}.json", "w") as f:
                    json.dump(rec, f, default=str)
                n += 1
            except Exception:
                continue
        log(f"  persisted {n} cases -> cases/iter_{iteration:04d}/")

    def _build_reduced_repros(self, cases, iteration):
        """assertion -> ddmin reduction -> RE-EXECUTE the reduced case -> store + log.
        Each triggered case is minimised with real Delta-Debugging (whose oracle
        re-runs the assertioned harness), then the 1-minimal case is executed again
        so the feedback/log shows the reduced execution trace AND its triggered error."""
        self._reduced_repros = []
        if not (self._trigger_map and self.assertion_compilation_pass and self.asserted_harness_path):
            return
        from harness.test_analysis.ddmin import reduce_case_with_ddmin
        for i in sorted(self._trigger_map.keys()):
            if i < 0 or i >= len(cases):
                continue
            orig = cases[i]
            tl = {str(k): v for k, v in getattr(orig, 'sparse_timeline', {}).items()}
            if not tl:
                continue
            try:
                reduced_tl, iters = reduce_case_with_ddmin(
                    tl, str(self.st_path), str(self.schema_path),
                    str(self.asserted_harness_path), f"{self.task_id}__ddmin", max_iters=12)
            except Exception as e:
                self.logger.warning_print(f"  ddmin failed: {e}"); continue
            try:
                sp = {int(k) if str(k).isdigit() else k: v for k, v in reduced_tl.items()}
                dummy = ExpUnifiedIR(exp_id=f"{getattr(orig,'exp_id','case')}_min",
                    target_st_path=str(self.st_path), schema_path=str(self.schema_path),
                    tester_type=f"RQ3_{self.config.id}_min", total_cycles=len(sp), sparse_timeline=sp)
                rr = self.coverage_collector.execute_with_multiple_coverage(
                    st_code_input=str(self.st_path), harness_input=str(self.asserted_harness_path),
                    input_data_list=[dummy], benchmark_case=f"{self.task_id}__ddmin",
                    reuse_compilation=True, output_format="StoredTestCase")
                rstdout = rr.get("stdout", "") or ""; rstderr = rr.get("stderr", "") or ""
            except Exception as e:
                self.logger.warning_print(f"  reduced re-exec failed: {e}"); continue
            segs = self._parse_exec_by_case(rstdout)
            seg = segs[0] if segs else {}
            tmap = self._parse_triggers_by_case(rstderr).get(0, {})
            self._reduced_repros.append({
                "exp_id": getattr(orig, 'exp_id', '?'), "orig_n": len(tl),
                "reduced_n": (len(seg) if seg else len(reduced_tl)),
                "ddmin_iters": iters, "seg": seg, "triggers": tmap})
            log(f"  ddmin[{getattr(orig,'exp_id','?')[-4:]}]: {len(tl)}→{len(reduced_tl)} cyc "
                f"({iters} iters), re-exec triggers={sum(len(v) for v in tmap.values())}")
            if len(self._reduced_repros) >= 1:
                break
        if self._reduced_repros:
            rd = self.work_dir / "reductions"; rd.mkdir(exist_ok=True)
            with open(rd / f"iter_{iteration:04d}.txt", 'w') as f:
                for r in self._reduced_repros:
                    f.write(f"=== {r['exp_id']}  {r['orig_n']}->{r['reduced_n']} cyc "
                            f"(ddmin {r['ddmin_iters']} iters) ===\n")
                    for ln in self._render_case_cycles(r['seg'], sorted(r['seg'].keys()),
                                                       triggers=r['triggers']):
                        f.write(ln + "\n")
                    f.write("\n")

    def _build_C1(self, cases, trigger_msgs, prev_cov, prev_cov_prev):
        """C1: distilled feedback.
        - If an assertion was triggered -> show minimal reproduction (reduced cycles).
        - Otherwise -> reduction is meaningless, switch to EXPLORATION guidance and
          surface the concrete assertion targets so the LLM can aim to violate them.
        All per-cycle state is extracted from the execution output."""
        exec_cases = self._parse_exec_by_case(self._last_stdout_full)
        show_oracle = self.config.enable_oracle
        lines = [f"## Coverage: {prev_cov:.1f}% (Δ={prev_cov-prev_cov_prev:+.1f}pp), "
                 f"{len(cases)} cases executed"]
        lines += self._timeout_note()
        if show_oracle:
            lines += self._assertion_block()
        lines.append("")

        if not trigger_msgs:
            if show_oracle:
                lines.append("## STATUS: No assertion triggered yet — REDUCTION SKIPPED.")
                lines.append("## STRATEGY: Prioritise EXPLORATION. Build multi-cycle input "
                             "sequences that drive the state toward violating the assertions above.")
            else:
                lines.append("## STATUS: Nothing notable to reduce yet.")
                lines.append("## STRATEGY: Explore more diverse multi-cycle input sequences "
                             "to reach new program states.")
            lines.append("")
            for i, seg in enumerate(exec_cases[:3]):
                exp_id = cases[i].get('exp_id', '?') if i < len(cases) else '?'
                keys = sorted(seg.keys())
                lines.append(f"## Sample executed case {i+1} ({exp_id}, {len(keys)} cyc)")
                lines += self._render_case_cycles(seg, keys)
                lines.append("")
            return lines

        if not self._reduced_repros:
            lines.append("## (cases triggered but no minimal reproduction could be re-executed this round)")
            return lines

        if show_oracle:
            n_trig = sum(len(m) for cyc in self._trigger_map.values() for m in cyc.values())
            lines.append(f"## {n_trig} assertion trigger(s) — ddmin-reduced & re-executed "
                         f"(trigger shown at its cycle):")
        else:
            lines.append("## ddmin-reduced & re-executed minimal cases:")
        lines.append("")
        for idx, r in enumerate(self._reduced_repros[:3]):
            seg = r['seg']; tmap = r['triggers']
            keys = sorted(seg.keys())
            if show_oracle:
                trig_cyc = ",".join(str(c) for c in sorted(tmap)) or "?"
                lines.append(f"## Reduced Case {idx+1} ({r['exp_id']}, {r['orig_n']}→{r['reduced_n']} cyc, "
                             f"ddmin {r['ddmin_iters']} iters; triggered at cycle {trig_cyc})")
                lines += self._render_case_cycles(seg, keys, triggers=tmap)
            else:
                # C4: SAME reduced execution trace as C1, but NO assertion/trigger debug info
                lines.append(f"## Reduced Case {idx+1} ({r['exp_id']}, {r['orig_n']}→{r['reduced_n']} cyc)")
                lines += self._render_case_cycles(seg, keys)
            lines.append("")
        return lines

    def _build_C3(self, cases, trigger_msgs, prev_cov, prev_cov_prev):
        """C3: full per-case per-cycle report, all state from execution output."""
        exec_cases = self._parse_exec_by_case(self._last_stdout_full)
        lines = [f"## Coverage: {prev_cov:.1f}% (Δ={prev_cov-prev_cov_prev:+.1f}pp), {len(cases)} cases"]
        lines += self._timeout_note()
        lines += self._assertion_block()
        lines.append("")
        for i, seg in enumerate(exec_cases[:6]):
            exp_id = cases[i].get('exp_id', '?') if i < len(cases) else '?'
            keys = sorted(seg.keys())
            tmap = self._trigger_map.get(i, {})
            trig_note = f" — triggered at cycle {','.join(str(c) for c in sorted(tmap))}" if tmap else ""
            lines.append(f"## Case {i+1} ({exp_id}, {len(keys)} cyc){trig_note}")
            lines += self._render_case_cycles(seg, keys, triggers=tmap)
            lines.append("")
        lines.append(f"## Distinct triggers: {len(trigger_msgs)}")
        for t in trigger_msgs[:8]:
            lines.append(f"  ⚠ {t}")
        lines.append("")
        return lines

    def _build_Eraw(self, cases, trigger_msgs, prev_cov, prev_cov_prev):
        lines = [f"=== Round Report ===", ""]
        if self._last_exec_raw:
            lines.append(self._last_exec_raw[:3000])
        else:
            lines.append(f"{len(cases)} cases executed. No trace.")
        return lines

    def _build_C0(self):
        """C0: zero inter-round feedback. The LLM receives no execution output,
        no coverage history, and no assertion reports — only its own generated
        cases from the first round. This isolates whether feedback provides any
        signal beyond the initial ST code + schema prompt."""
        return ["Continue generating test cases to explore the program behavior.",
                "No additional feedback available this round."]

    def _verify_ground_truth(self):
        """EVALUATION pass: run ALL generated cases through the benchmark's pre-built
        GROUND-TRUTH harness (mutation_X/plc_c_files/harness.c). This harness yields BOTH
        the reference oracle ('AUDIT FAIL') AND the authoritative coverage. The runner's
        freshly-synthesized clean harness is used only for in-loop GENERATION feedback and
        is fragile on rich-type tasks; EVALUATION always uses the pre-built harness."""
        info = {"available": False, "detected": False, "detecting_cases": 0, "first_msg": "",
                "eval_line": None, "eval_branch": None}
        gt = self.ground_truth_harness
        if not (gt and Path(gt).exists() and self._all_cases):
            return info
        info["available"] = True
        try:
            r = self.coverage_collector.execute_with_multiple_coverage(
                st_code_input=str(self.st_path), harness_input=str(gt),
                input_data_list=self._all_cases[:300], benchmark_case=f"{self.task_id}_{self.work_dir.name}__gt",
                reuse_compilation=True, output_format="StoredTestCase")
            out = (r.get("stdout", "") or "") + "\n" + (r.get("stderr", "") or "")
        except Exception as e:
            self.logger.warning_print(f"  GT verify failed: {e}")
            return info
        for line in out.split('\n'):
            if 'AUDIT FAIL' in line:
                info["detected"] = True
                info["detecting_cases"] += 1
                if not info["first_msg"]:
                    info["first_msg"] = line.strip()[line.find('AUDIT'):][:200]
        cd = r.get("coverage_data")
        if cd and getattr(cd, "coverage_summary", None):
            for attr, key in (("line_coverage", "eval_line"), ("branch_coverage", "eval_branch")):
                bd = getattr(cd.coverage_summary, attr, None)
                if bd and getattr(bd, "percentage", None):
                    try: info[key] = float(bd.percentage.replace("%", ""))
                    except Exception: pass
        return info

    # ── Suite-level reduction (distillation groups C1/C4 only) ──

    def _suite_line_cov(self, subset) -> float:
        try:
            r = self.coverage_collector.execute_with_multiple_coverage(
                st_code_input=str(self.st_path), harness_input=str(self.harness_path),
                input_data_list=subset, benchmark_case=self.task_id,
                reuse_compilation=True, output_format="StoredTestCase")
            cd = r.get("coverage_data")
            if cd and hasattr(cd, "coverage_summary") and cd.coverage_summary:
                bd = getattr(cd.coverage_summary, "line_coverage", None)
                if bd and bd.percentage:
                    return float(bd.percentage.replace("%", ""))
        except Exception as e:
            self.logger.warning_print(f"  suite cov failed: {e}")
        return -1.0

    def _suite_gt_hit(self, subset) -> bool:
        gt = self.ground_truth_harness
        if not (gt and Path(gt).exists()):
            return False
        try:
            r = self.coverage_collector.execute_with_multiple_coverage(
                st_code_input=str(self.st_path), harness_input=str(gt),
                input_data_list=subset, benchmark_case=f"{self.task_id}__gt",
                reuse_compilation=True, output_format="StoredTestCase")
            return 'AUDIT FAIL' in ((r.get("stdout", "") or "") + (r.get("stderr", "") or ""))
        except Exception:
            return False

    def _suite_trig(self, subset) -> bool:
        if not (self.assertion_compilation_pass and self.asserted_harness_path):
            return False
        try:
            r = self.coverage_collector.execute_with_multiple_coverage(
                st_code_input=str(self.st_path), harness_input=str(self.asserted_harness_path),
                input_data_list=subset, benchmark_case=f"{self.task_id}__assert",
                reuse_compilation=True, output_format="StoredTestCase")
            return 'SECURITY_ASSERTION_FAILED' in (r.get("stderr", "") or "")
        except Exception:
            return False

    def _pick_reduced_subset(self, max_keep: int = 12) -> List[Any]:
        """Zero-evaluation sampled reduction subset: randomly pick a portion of assertion-triggering cases (newer cases preferred)."""
        if not self._triggered_cases:
            return []
        import random
        seen = set(); pool = []
        for c in reversed(self._triggered_cases):   # new -> old
            k = id(c)
            if k not in seen:
                seen.add(k); pool.append(c)
        k = min(len(pool), max_keep)
        idxs = list(range(len(pool))); subset = []
        while len(subset) < k and idxs:             # triangular weights: newer = more likely to be picked
            pick = random.choices(idxs, weights=[len(pool) - j for j in idxs], k=1)[0]
            idxs.remove(pick); subset.append(pool[pick])
        return subset

    def _reduce_suite(self, max_keep: int = 12) -> Optional[Dict[str, Any]]:
        """Lightweight suite reduction (distill groups C1/C4 only): sampled reduction subset (zero evaluation) + a single evaluation."""
        if not self.config.enable_distillation or not self._triggered_cases:
            return None
        subset = self._pick_reduced_subset(max_keep)
        if not subset:
            return None
        line = self._suite_line_cov(subset)
        gt = self._suite_gt_hit(subset)
        trig = self._suite_trig(subset)
        cyc = sum(getattr(c, 'total_cycles', 0) or 0 for c in subset)
        log(f"  suite-reduce(random): {len(subset)} cases / {cyc} cyc | "
            f"line={line:.1f}% GT={gt} trig={trig}")
        return {"orig_suite_cases": min(len(self._all_cases), 50),
                "reduced_suite_cases": len(subset), "reduced_suite_cycles": cyc,
                "reduced_suite_line": line, "reduced_suite_gt": gt, "reduced_suite_trig": trig}

    def _exam_suite(self, label: str, snapshot: List[Any], want_gt: bool, want_trig: bool) -> Dict[str, Any]:
        """Examine one candidate suite in the background: full evaluation (coverage/GT/assertions/size), with timeout tag.
        Runs in a separate thread, using a separate collector instance + separate benchmark_case to isolate the compile cache."""
        res = {"label": label, "n_cases": len(snapshot),
               "n_cycles": sum(getattr(c, 'total_cycles', 0) or 0 for c in snapshot),
               "line": -1.0, "branch": -1.0, "gt": False, "trig": False, "timeout": False}
        if not snapshot:
            return res
        try:
            from harness.compiler.utils import Logger, LEVEL
            # Each run uses a unique log directory under its own work_dir, to avoid multi-thread/multi-process
            # races on a shared /tmp directory triggering Logger.__init__'s sys.exit(1). Catch BaseException as a fallback:
            # Logger failure raises SystemExit (a BaseException); plain Exception cannot catch it and it would kill the whole process.
            exam_log_dir = self.work_dir / "exam_logs"
            exam_log_dir.mkdir(parents=True, exist_ok=True)
            cc = STCoverageCollector(root_dir=str(PROJECT_ROOT),
                logger=Logger(str(exam_log_dir), "exam.log", level=LEVEL.ERROR, console_output=False),
                default_output_format="StoredTestCase", llvm_version=18)
        except BaseException:
            res["timeout"] = True; return res
        bc = f"{self.task_id}__exam_{label}"
        try:
            r = cc.execute_with_multiple_coverage(
                st_code_input=str(self.st_path), harness_input=str(self.harness_path),
                input_data_list=snapshot, benchmark_case=bc,
                reuse_compilation=True, output_format="StoredTestCase")
            if 'timed out' in ((r.get("stderr", "") or "") + (r.get("stdout", "") or "")):
                res["timeout"] = True
            cd = r.get("coverage_data")
            if cd and hasattr(cd, "coverage_summary") and cd.coverage_summary:
                for attr, key in [("line_coverage", "line"), ("branch_coverage", "branch")]:
                    bd = getattr(cd.coverage_summary, attr, None)
                    if bd and bd.percentage:
                        try: res[key] = float(bd.percentage.replace("%", ""))
                        except Exception: pass
        except Exception:
            res["timeout"] = True; return res
        if want_gt and self.ground_truth_harness and Path(self.ground_truth_harness).exists():
            try:
                r = cc.execute_with_multiple_coverage(
                    st_code_input=str(self.st_path), harness_input=str(self.ground_truth_harness),
                    input_data_list=snapshot, benchmark_case=bc + "_gt",
                    reuse_compilation=True, output_format="StoredTestCase")
                res["gt"] = 'AUDIT FAIL' in ((r.get("stdout", "") or "") + (r.get("stderr", "") or ""))
            except Exception:
                pass
        if want_trig and self.assertion_compilation_pass and self.asserted_harness_path:
            try:
                r = cc.execute_with_multiple_coverage(
                    st_code_input=str(self.st_path), harness_input=str(self.asserted_harness_path),
                    input_data_list=snapshot, benchmark_case=bc + "_as",
                    reuse_compilation=True, output_format="StoredTestCase")
                res["trig"] = 'SECURITY_ASSERTION_FAILED' in (r.get("stderr", "") or "")
            except Exception:
                pass
        return res

    @staticmethod
    def _select_best_suite(exams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Winner-group criterion: timed-out candidates get the lowest priority; among candidates still triggering GT/assertions,
        pick the smallest size subject to coverage dropping <10% from the best; if no faithful candidate exists, pick the highest coverage."""
        if not exams:
            return None
        non_to = [e for e in exams if not e.get("timeout")]
        pool = non_to if non_to else exams          # timeouts have the lowest priority
        faithful = [e for e in pool if e.get("gt") or e.get("trig")]
        if faithful:
            best_line = max(e["line"] for e in faithful)
            keep = [e for e in faithful if e["line"] >= best_line * 0.9]   # coverage drop <10%
            return min(keep, key=lambda e: (e["n_cases"], e["n_cycles"]))  # smallest size
        return max(pool, key=lambda e: e["line"])    # none triggers -> highest coverage

    # ── Main loop ──
    def run(self, time_budget: int = 300, cases_per_iter: int = 3, max_iterations: int = 200) -> Dict:
        log(f"=== {self.task_id} | Config={self.config.id} | Budget={time_budget}s ===")
        iterations = []; total_start = time.time(); total_cases = 0

        for it in range(1, max_iterations + 1):
            if time.time() - total_start > time_budget:
                log(f"  Budget exhausted after {it - 1} iterations"); break
            log(f"\n--- Iter {it} ({time.time() - total_start:.0f}s) ---")
            pre_tok = TokenTracker.get().snapshot()

            ctx = self._build_context(it)
            ctx_log_dir = self.work_dir / "llm_contexts"; ctx_log_dir.mkdir(exist_ok=True)
            formatted = GeneratorPrompts._format_context(ctx)
            with open(ctx_log_dir / f"iter_{it:04d}.txt", 'w') as f: f.write(formatted)

            remaining = int(max(0, time_budget - (time.time() - total_start)))
            # Tell the agent the economics so it routes deliberately: the WHOLE campaign
            # shares a fixed budget; slow tools (run_full_dse, run_afl_mutation) each eat a
            # large slice and leave fewer later iterations; AFL only pays off with good seeds.
            budget_note = (
                f"BUDGET: this campaign has ~{int(time_budget)}s TOTAL across ALL iterations; "
                f"~{remaining}s remain. Tool costs differ: random_fuzzing/solve_with_z3 are "
                f"cheap; whitebox_generate is moderate; run_full_dse (~60s) and "
                f"run_afl_mutation (~60-120s) are EXPENSIVE and reduce how many iterations you "
                f"get left, so call them deliberately (usually once, after a plateau). "
                f"run_afl_mutation is weak cold — pass seed_strategy=triggered/distilled to "
                f"mutate your best existing inputs."
            )
            goal = "Maximize branch coverage. Generate multi-cycle test inputs. " + budget_note
            # Iter 1: forced cold-start random_fuzzing, but ONLY a slice of the total
            # budget so the remaining time goes to feedback-driven iterations (otherwise
            # random eats the whole budget and the C1-C4/E_raw feedback never takes effect).
            if it == 1:
                first_budget = max(30, min(int(time_budget * 0.4), 90))
                goal = (f"CALL random_fuzzing ONLY with budget_sec={first_budget}. Generate "
                        f"multi-cycle test inputs. " + budget_note)
            # Inject the historical seed pool available to AFL (for the LLM to choose via run_afl_mutation's seed_strategy):
            # triggered = high-signal assertion-triggering cases, distilled = distillation subset, recent = latest batch, all = full sampling.
            try:
                self.generator.tool_manager.set_seed_pools({
                    "triggered": list(reversed(self._triggered_cases))[:20],
                    "distilled": self._pick_reduced_subset(),
                    "recent": self._all_cases[-20:],
                    "all": self._all_cases[:60],
                })
            except Exception:
                pass
            llm_cases = self.generator.generate(goal=goal, context=ctx, max_tool_calls=2)
            llm_cases = [c for c in llm_cases if hasattr(c, "sparse_timeline")]
            # Record which tools (and how often) the LLM chose after seeing feedback, what parameters were injected, and how many cases were produced,
            # for process-difference analysis (tool selection/execution differences across configurations under feedback).
            _gmeta = getattr(self.generator, 'metadata', {}) or {}
            tools_used = dict(_gmeta.get('tools_used', {}) or {})
            tool_log = list(_gmeta.get('tool_log', []) or [])
            for k, v in tools_used.items():
                self._tools_used_total[k] = self._tools_used_total.get(k, 0) + v

            rcg = RandomCaseGenerator(seed=None)
            rnd = []
            n_rnd = 30 if it == 1 else max(15, cases_per_iter)
            n_cyc = 8
            for _ in range(n_rnd):
                sp = {}
                for cyc in range(n_cyc):
                    p = rcg.generate_case(self.st_code, self.schema)
                    if p: sp[cyc] = p
                if sp:
                    rnd.append(ExpUnifiedIR(exp_id=f"{self.task_id}_rnd_{uuid.uuid4().hex[:4]}",
                        target_st_path=str(self.st_path), schema_path=str(self.schema_path),
                        tester_type=f"RQ3_{self.config.id}", total_cycles=len(sp), sparse_timeline=sp))
            cases = rnd + llm_cases
            for c in cases:
                if hasattr(c, "schema_path"): c.schema_path = str(self.schema_path)
            total_cases += len(cases)
            for c in cases:
                self._total_cycles += getattr(c, "total_cycles", 0) or 0
                if len(self._all_cases) < 300:
                    self._all_cases.append(c)

            # §4.1 persist raw inputs BEFORE execution: post-hoc analysis can be rebuilt
            # offline (coverage / ddmin suite) even if the exec below crashes/times out.
            self._persist_cases(it, cases)

            exec_h = self.harness_path  # CLEAN harness -> measures COVERAGE only
            try:
                result = self.coverage_collector.execute_with_multiple_coverage(
                    st_code_input=str(self.st_path), harness_input=str(exec_h),
                    input_data_list=cases[:50], benchmark_case=self.task_id,
                    reuse_compilation=True, output_format="StoredTestCase")
            except Exception as e:
                self.logger.error_print(f"  Exec failed: {e}"); break

            stdout = result.get("stdout", ""); stderr = result.get("stderr", "")
            self._last_exec_raw = stdout[:8000] + "\n" + stderr[:2000]
            self._last_stdout_full = stdout
            self._last_timeouts = (stderr + stdout).count("timed out")
            self._total_timeouts += self._last_timeouts

            # ASSERTIONED harness -> detects LOGIC violations only (kept separate from
            # coverage). Run the SAME cases; attribute each trigger to its case + cycle.
            assert_stderr = ""
            if self.assertion_compilation_pass and self.asserted_harness_path:
                try:
                    ares = self.coverage_collector.execute_with_multiple_coverage(
                        st_code_input=str(self.st_path),
                        harness_input=str(self.asserted_harness_path),
                        input_data_list=cases[:50], benchmark_case=f"{self.task_id}__assert",
                        reuse_compilation=True, output_format="StoredTestCase")
                    assert_stderr = ares.get("stderr", "") or ""
                except Exception as e:
                    self.logger.warning_print(f"  Assertioned exec failed: {e}")

            self._trigger_map = self._parse_triggers_by_case(assert_stderr)
            self._last_assertion_msgs = sorted({m for cyc in self._trigger_map.values()
                                                for msgs in cyc.values() for m in msgs})
            self._triggered_assertions.update(self._last_assertion_msgs)
            if self._trigger_map:
                self.assertion_triggers += sum(len(msgs) for cyc in self._trigger_map.values()
                                               for msgs in cyc.values())
                for i in self._trigger_map:
                    if 0 <= i < len(cases) and len(self._triggered_cases) < 200:
                        self._triggered_cases.append(cases[i])

            # assertion -> ddmin reduction -> re-execute the reduced case -> log result+error
            self._build_reduced_repros(cases, it)

            # Per-round exam: submit "the round's full batch" (+ the distill group's reduction subset) to background threads for evaluation,
            # while the main flow immediately proceeds to the next round (generation and evaluation decoupled, concurrency limit = 2).
            _wgt = bool(self.ground_truth_harness)
            _wtr = self.assertion_compilation_pass
            self._exam_futures.append(self._exam_pool.submit(
                self._exam_suite, f"it{it}_full", list(cases[:50]), _wgt, _wtr))
            if self.config.enable_distillation:
                _red = self._pick_reduced_subset()
                if _red:
                    self._exam_futures.append(self._exam_pool.submit(
                        self._exam_suite, f"it{it}_reduced", _red, _wgt, _wtr))

            self._last_case_summaries = []
            for c in cases:
                if not hasattr(c, "sparse_timeline") or not c.sparse_timeline: continue
                tl = {str(k): v for k, v in c.sparse_timeline.items()}
                nc = getattr(c, "total_cycles", len(tl))
                try:
                    kfs = self.keyframe_extractor.extract({"sparse_timeline": tl}, max_frames=20)
                    kft = format_key_frames_for_llm(kfs) if kfs.total_frames > 0 else ""
                    log(f"  KF[{getattr(c,'exp_id','?')[-4:]}]: {kfs.total_frames} frames, {nc}→{kfs.compression_ratio:.1f}x, types={dict(kfs.frames_by_type)}")
                    # Save full keyframe text to file for inspection
                    if kft:
                        kf_dir = self.work_dir / "keyframes"; kf_dir.mkdir(exist_ok=True)
                        with open(kf_dir / f"{getattr(c,'exp_id','?')}.txt", 'w') as f:
                            f.write(kft)
                except:
                    kft = ""; kfs = None
                self._last_case_summaries.append({
                    "exp_id": getattr(c, "exp_id", "?"), "cycles": nc, "timeline": tl,
                    "keyframes": kft, "compression_ratio": getattr(kfs, 'compression_ratio', 1.0) if kfs else 1.0,
                })

            cov = {"line": 0.0, "branch": 0.0}
            cd = result.get("coverage_data")
            if cd and hasattr(cd, "coverage_summary") and cd.coverage_summary:
                for attr, key in [("line_coverage","line"), ("branch_coverage","branch")]:
                    bd = getattr(cd.coverage_summary, attr, None)
                    if bd and bd.percentage:
                        try: cov[key] = float(bd.percentage.replace("%", ""))
                        except: pass
            self.coverage_history.append(cov["line"])

            post_tok = TokenTracker.get().snapshot()
            ti = post_tok["input_tokens"] - pre_tok["input_tokens"]
            to = post_tok["output_tokens"] - pre_tok["output_tokens"]
            vc = 0; vd = []
            try:
                er = result.get("execution_result")
                if er and not isinstance(er, dict):
                    vr = self.violation_detector.detect_violations(er)
                    vc = vr.total_violations
                    vd = [{"type": v.violation_type.value, "msg": v.message[:150]} for v in vr.violations[:5]]
            except: pass
            self.violations.extend(vd)

            iterations.append({"iteration": it, "cases": len(cases),
                "line_pct": cov["line"], "branch_pct": cov["branch"],
                "violations": vc, "violation_details": vd,
                "token_input": ti, "token_output": to,
                "tools_used": tools_used, "tool_log": tool_log,
                "n_llm_cases": len(llm_cases), "n_rnd_cases": len(rnd)})
            log(f"  [iter {it:3d}] cases={len(cases)} line={cov['line']:.1f}% branch={cov['branch']:.1f}% "
                f"violations={vc} tok(in/out)={ti}/{to}")

        total_elapsed = round(time.time() - total_start, 1)
        last = iterations[-1] if iterations else {}
        # Defense #3: each final evaluation step is wrapped in its own try; no crash/timeout may prevent the summary from being written.
        try:
            gt_info = self._verify_ground_truth()
        except Exception as e:
            self.logger.error_print(f"GT verify crashed: {e}")
            gt_info = {"available": False, "detected": False, "detecting_cases": 0, "first_msg": "",
                       "eval_line": None, "eval_branch": None}
        try:
            suite_red = self._reduce_suite() if self.config.enable_distillation else None
        except Exception as e:
            self.logger.error_print(f"suite-reduce crashed: {e}"); suite_red = None
        # Collect per-round exam results (background threads), pick the winner group, shut down the thread pool
        exams = []
        for fut in self._exam_futures:
            try:
                # Catch BaseException: a Logger failure in a background exam thread raises SystemExit; fut.result
                # re-raises it on the main thread, and if Exception cannot catch it the whole run dies with exit=1 without writing the summary.
                exams.append(fut.result(timeout=90))
            except BaseException:
                exams.append({"label": "?", "timeout": True, "n_cases": 0, "n_cycles": 0,
                              "line": -1.0, "branch": -1.0, "gt": False, "trig": False})
        try:
            self._exam_pool.shutdown(wait=False)
        except Exception:
            pass
        try:
            best_suite = self._select_best_suite(exams)
        except Exception as e:
            self.logger.error_print(f"best-suite crashed: {e}"); best_suite = None
        exam_timeouts = sum(1 for e in exams if e.get("timeout"))
        gen_tok_in = sum(i.get("token_input", 0) for i in iterations)
        gen_tok_out = sum(i.get("token_output", 0) for i in iterations)
        # TokenTracker.snapshot() is consume-and-reset, so the total token cost is the
        # SUM of the per-phase deltas: assertion generation + all test-case generation.
        tot_tok_in = self._assertion_token_input + gen_tok_in
        tot_tok_out = self._assertion_token_output + gen_tok_out
        summary = {
            "task_id": self.task_id, "config": self.config.id,
            "mutation_task": self.mutation_task,
            "total_iterations": len(iterations), "total_cases": total_cases,
            "total_cycles": self._total_cycles,
            "suite_size_cases": total_cases,
            "final_line_coverage": last.get("line_pct", 0.0),
            "final_branch_coverage": last.get("branch_pct", 0.0),
            # peak = max over iterations: avoids understating coverage when the LAST
            # round happens to regress (cheaper-feedback configs run more noisy rounds).
            "peak_line_coverage": max((i.get("line_pct", 0.0) for i in iterations), default=0.0),
            "peak_branch_coverage": max((i.get("branch_pct", 0.0) for i in iterations), default=0.0),
            # token cost = assertion-gen + ALL test-case-gen agent calls
            "total_token_input": tot_tok_in,
            "total_token_output": tot_tok_out,
            "assertion_gen_token_input": self._assertion_token_input,
            "assertion_gen_token_output": self._assertion_token_output,
            "generation_token_input": gen_tok_in,
            "generation_token_output": gen_tok_out,
            "assertion_generated": self.assertion_count,
            "assertion_compilation_pass": self.assertion_compilation_pass,
            "assertion_triggers": self.assertion_triggers,
            "main_flow_timeouts": self._total_timeouts,
            "distinct_assertions_triggered": len(self._triggered_assertions),
            "triggered_assertion_msgs": sorted(self._triggered_assertions)[:20],
            "ground_truth_available": gt_info["available"],
            "ground_truth_detected": gt_info["detected"],
            "ground_truth_detecting_cases": gt_info["detecting_cases"],
            "ground_truth_first_msg": gt_info["first_msg"],
            "eval_line_coverage": gt_info.get("eval_line"),
            "eval_branch_coverage": gt_info.get("eval_branch"),
            "reduced_repros": [{"exp_id": r["exp_id"], "orig_n": r["orig_n"],
                                "reduced_n": r["reduced_n"], "ddmin_iters": r["ddmin_iters"]}
                               for r in self._reduced_repros],
            "suite_reduction": suite_red,
            "reduced_suite_cases": (suite_red or {}).get("reduced_suite_cases"),
            "reduced_suite_cycles": (suite_red or {}).get("reduced_suite_cycles"),
            "exam_candidates": exams,
            "exam_timeouts": exam_timeouts,
            "best_suite": best_suite,
            "best_suite_cases": (best_suite or {}).get("n_cases"),
            "best_suite_cycles": (best_suite or {}).get("n_cycles"),
            "best_suite_line": (best_suite or {}).get("line"),
            "best_suite_gt": (best_suite or {}).get("gt"),
            "tools_used_total": self._tools_used_total,
            "total_elapsed": total_elapsed, "iterations": iterations,
        }
        try:
            with open(self.work_dir / "summary.json", 'w') as f:
                json.dump(summary, f, indent=2, default=str)
        except Exception as e:
            self.logger.error_print(f"summary dump failed: {e}; writing minimal summary")
            minimal = {k: summary.get(k) for k in (
                "task_id", "config", "mutation_task", "total_iterations", "total_cases",
                "total_cycles", "final_line_coverage", "final_branch_coverage",
                "assertion_generated", "assertion_compilation_pass", "assertion_triggers",
                "distinct_assertions_triggered", "ground_truth_detected", "total_token_input",
                "total_token_output", "main_flow_timeouts", "total_elapsed")}
            try:
                with open(self.work_dir / "summary.json", 'w') as f:
                    json.dump(minimal, f, indent=2, default=str)
            except Exception as e2:
                self.logger.error_print(f"minimal summary also failed: {e2}")
        log(f"  ✓ line={summary['final_line_coverage']:.1f}% branch={summary['final_branch_coverage']:.1f}% "
            f"asserts={self.assertion_count}({'✓' if self.assertion_compilation_pass else '✗'}) "
            f"trig={self.assertion_triggers}/{len(self._triggered_assertions)}distinct "
            f"GT={'HIT' if gt_info['detected'] else 'miss'} cases={total_cases} cycles={self._total_cycles} "
            f"tok={tot_tok_in}/{tot_tok_out}(assert {self._assertion_token_input}/{self._assertion_token_output}) "
            f"elapsed={total_elapsed}s → {self.work_dir / 'summary.json'}")
        return summary


# ============================================================================
# Offline rebuild (§4.1)
# ============================================================================

def load_persisted_cases(run_dir, iteration: Optional[int] = None) -> List[ExpUnifiedIR]:
    """Rebuild ExpUnifiedIR cases from persisted cases/iter_*/case_*.json.
    iteration=None -> all iters (in order); else only that iter. Enables offline
    re-execution (coverage / ddmin suite / GT verify) without re-running the campaign."""
    base = Path(run_dir) / "cases"
    if not base.exists():
        return []
    iter_dirs = ([base / f"iter_{iteration:04d}"] if iteration is not None
                 else sorted(base.glob("iter_*")))
    out: List[ExpUnifiedIR] = []
    for d in iter_dirs:
        if not d.is_dir():
            continue
        for jf in sorted(d.glob("case_*.json")):
            try:
                rec = json.loads(jf.read_text())
            except Exception:
                continue
            tl = rec.get("sparse_timeline") or {}
            sp = {int(k) if str(k).isdigit() else k: v for k, v in tl.items()}
            out.append(ExpUnifiedIR(
                exp_id=rec.get("exp_id", jf.stem),
                target_st_path=rec.get("target_st_path", ""),
                schema_path=rec.get("schema_path", ""),
                tester_type=rec.get("tester_type", "rebuilt"),
                total_cycles=rec.get("total_cycles", len(sp)),
                sparse_timeline=sp))
    return out


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="RQ3 Ablation Runner v3 — stable run + collect entry point")
    parser.add_argument("--task", type=str, default="211_StackMin")
    parser.add_argument("--config", type=str, default="C1", choices=["C0","C1","C2","C3","C4","E_raw"])
    parser.add_argument("--configs", type=str, default=None,
                        help="Comma list of configs to run IN PARALLEL, e.g. C1,C2,C3,C4,E_raw")
    parser.add_argument("--mutation", type=str, default=None)
    parser.add_argument("--mutation-all", action="store_true",
                        help="Run every mutation_N variant of the task (sequential per mutation)")
    parser.add_argument("--full-dataset", action="store_true",
                        help="Whole-benchmark batch: Phase1 one variant per task, Phase2 the rest")
    parser.add_argument("--phase1-only", action="store_true",
                        help="Full-dataset: only run Phase 1 (one variant per task)")
    parser.add_argument("--task-workers", type=int, default=5,
                        help="Full-dataset: number of tasks to run concurrently (default 5)")
    parser.add_argument("--budget", type=int, default=300)
    parser.add_argument("--cases-per-iter", type=int, default=5)
    parser.add_argument("--max-iterations", type=int, default=200)
    parser.add_argument("--hang-timeout", type=int, default=0,
                        help="SIGKILL a config subprocess exceeding this many seconds "
                             "(over-long task -> anomaly skip). 0 = auto: max(5400, budget*8).")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Full-dataset RESUME: skip any (task,mutation,config) that already "
                             "has a summary.json; only run the missing gaps.")
    parser.add_argument("--only-tasks", type=str, default=None,
                        help="Full-dataset: restrict to a comma-separated list of task ids "
                             "(re-run only this subset of tasks).")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--local-api", action="store_true")
    parser.add_argument("--collect", action="store_true",
                        help="Aggregate all results/rq3 summaries into a CSV + table (no run)")
    parser.add_argument("--collect-out", type=str, default=str(RESULT_OUTPUT / "rq3_collected.csv"))
    args = parser.parse_args()

    if args.collect:
        _collect(Path(args.collect_out)); return

    if args.local_api:
        # Environment variables must be set before loading config: the assertion generator reloads config.py via importlib,
        # so in-memory setattr has no effect on it; only env vars make assertion generation go through local 8002 (otherwise DashScope).
        os.environ["PLCHAT_GEN_MODEL"] = "qwen2.5-32B-local"
        os.environ["PLCHAT_GEN_KEY"] = "local"
        os.environ["PLCHAT_GEN_BASE_URL"] = "http://localhost:8002/v1"
        import config
        for key in ['generator', 'direct_llm', 'planner', 'evaluator']:
            setattr(config, f'{key}_model', 'qwen2.5-32B-local')
            setattr(config, f'{key}_api_key', 'local')
            setattr(config, f'{key}_base_url', 'http://localhost:8002/v1')
        log(f"Using local API: http://localhost:8002/v1 (gen+assert+eval)")

    if args.full_dataset:
        _run_full_dataset(args); return

    if args.configs:
        _run_parallel(args); return

    if args.task == "all":
        tasks = sorted(d.name for d in BENCHMARK_ROOT.iterdir() if d.is_dir() and d.name[0].isdigit())
        log(f"Batch: {len(tasks)} tasks, config={args.config}")
        for i, t in enumerate(tasks):
            if list((RESULT_OUTPUT / f"rq3_{args.config}" / t).glob("run_*/summary.json")):
                log(f"[{i+1}/{len(tasks)}] {t} SKIP"); continue
            try: _run(t, args)
            except Exception as e: log(f"[{i+1}/{len(tasks)}] {t} FAIL: {e}")
        log("Batch done.")
    else:
        for mut in _mutations_for(args):
            a = argparse.Namespace(**vars(args)); a.mutation = mut
            _run(args.task, a)


def _mutations_for(args) -> List[Optional[str]]:
    """Resolve the list of mutation tasks to run (one, all, or none)."""
    if args.mutation_all:
        base = BENCHMARK_MUTATED / args.task
        if base.exists():
            muts = sorted((f"{args.task}/{d.name}" for d in base.iterdir()
                           if d.is_dir() and d.name.startswith("mutation_")),
                          key=lambda s: int(s.rsplit('_', 1)[-1]) if s.rsplit('_', 1)[-1].isdigit() else 0)
            if muts:
                return muts
    return [args.mutation]


def _spawn_configs_parallel(task: str, mutation: Optional[str], configs: List[str], args, batch_dir: Path):
    """Spawn all configs for one (task, mutation) in parallel and wait for them.
    Each config subprocess is given its OWN session so a hung config (e.g. a busy-loop
    that burns a full core for hours — see 253_AlarmProcess) can be killpg'd. Any config
    exceeding `hang_timeout` is SIGKILL'd, logged as an ANOMALY (over-long task skipped),
    and recorded in results/rq3/ANOMALIES.txt so the batch keeps making progress."""
    import subprocess, os, signal
    hang_timeout = getattr(args, 'hang_timeout', 0) or max(5400, int(args.budget) * 8)
    procs = []
    for cfg in configs:
        cmd = [sys.executable, str(Path(__file__).resolve()),
               "--task", task, "--config", cfg,
               "--budget", str(args.budget), "--cases-per-iter", str(args.cases_per_iter),
               "--max-iterations", str(args.max_iterations)]
        if mutation: cmd += ["--mutation", mutation]
        if args.local_api: cmd.append("--local-api")
        if args.debug: cmd.append("--debug")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = f"{task}_{(mutation or 'base').replace('/', '-')}_{cfg}"
        lf = open(batch_dir / f"{tag}_{ts}.log", "w")
        procs.append((tag, subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                             start_new_session=True), lf))
        log(f"  spawn {tag}")
    log(f"[{task}/{mutation or 'base'}] running {len(procs)} configs in parallel...")
    for tag, p, lf in procs:
        try:
            rc = p.wait(timeout=hang_timeout)
            log(f"  [{tag}] exit={rc}")
        except subprocess.TimeoutExpired:
            try: os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                try: p.kill()
                except Exception: pass
            try: p.wait(timeout=10)
            except Exception: pass
            log(f"  [{tag}] ANOMALY: killed after {hang_timeout}s (over-long task skipped)")
            try:
                with open(RESULT_OUTPUT / "ANOMALIES.txt", "a") as af:
                    af.write(f"{datetime.now().isoformat()}  {tag}  killed_after={hang_timeout}s\n")
            except Exception: pass
        finally:
            lf.close()


def _run_parallel(args):
    """Run the requested configs IN PARALLEL (one subprocess per config) for one task.
    With --mutation-all, mutations run one at a time (first variant first)."""
    configs = [c.strip() for c in args.configs.split(',') if c.strip()]
    batch_dir = RESULT_OUTPUT / "batch_logs"; batch_dir.mkdir(parents=True, exist_ok=True)
    for mut in _mutations_for(args):
        _spawn_configs_parallel(args.task, mut, configs, args, batch_dir)
    log("Parallel batch done. Run with --collect to aggregate.")


def _task_mutations() -> Dict[str, List[str]]:
    """Map each mutated-benchmark task -> sorted list of its mutation_N variants."""
    out = {}
    if not BENCHMARK_MUTATED.exists():
        return out
    for t in sorted(d.name for d in BENCHMARK_MUTATED.iterdir() if d.is_dir() and d.name[0].isdigit()):
        muts = sorted((d.name for d in (BENCHMARK_MUTATED / t).iterdir()
                       if d.is_dir() and d.name.startswith("mutation_")),
                      key=lambda s: int(s.split('_')[-1]) if s.split('_')[-1].isdigit() else 9999)
        if muts:
            out[t] = muts
    return out


def _config_done(task: str, mutation: Optional[str], cfg: str) -> bool:
    """True if a summary.json already exists for this (task, mutation, config) — used by
    --skip-existing to RESUME a partial full-dataset run (only fill the gaps)."""
    m = re.search(r'mutation_(\w+)', mutation or "")
    mut_tag = f"mut{m.group(1)}_" if m else ""
    return bool(list((RESULT_OUTPUT / f"rq3_{cfg}" / task).glob(f"run_{mut_tag}*/summary.json")))


def _run_full_dataset(args):
    """Full-dataset batch over the whole mutated benchmark, with TASK-LEVEL parallelism.
    PHASE 1: one variant per task (mutation_0 if present, else the first available);
             --task-workers tasks run concurrently, each running its configs in parallel.
    PHASE 2: every remaining variant of each task (skipped with --phase1-only)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    configs = [c.strip() for c in (args.configs or "C1,C2,C3,C4,E_raw").split(',') if c.strip()]
    batch_dir = RESULT_OUTPUT / "batch_logs"; batch_dir.mkdir(parents=True, exist_ok=True)
    tm = _task_mutations()
    if getattr(args, 'only_tasks', None):
        keep = {t.strip() for t in args.only_tasks.split(',') if t.strip()}
        tm = {t: m for t, m in tm.items() if t in keep}
        log(f"=== --only-tasks: restricted to {len(tm)} tasks: {sorted(tm)} ===")
    workers = getattr(args, 'task_workers', 5) or 5
    log(f"=== FULL DATASET: {len(tm)} tasks, configs={configs}, budget={args.budget}s, "
        f"task_workers={workers} (={workers*len(configs)} concurrent runs) ===")

    def first_variant(muts):
        return "mutation_0" if "mutation_0" in muts else muts[0]

    def run_one(t, mutation):
        cfgs = ([c for c in configs if not _config_done(t, mutation, c)]
                if getattr(args, 'skip_existing', False) else configs)
        if not cfgs:
            log(f"  [{t}/{mutation}] all {len(configs)} configs already done — SKIP")
            return
        try:
            _spawn_configs_parallel(t, mutation, cfgs, args, batch_dir)
        except Exception as e:
            log(f"  [{t}/{mutation}] FAIL: {e}")

    log(f"=== PHASE 1: one variant per task ({len(tm)} tasks), {workers} tasks in parallel ===")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, t, f"{t}/{first_variant(muts)}"): t for t, muts in tm.items()}
        done = 0
        for fut in as_completed(futs):
            done += 1
            log(f"  PHASE1 progress: {done}/{len(tm)} tasks done")
    log("=== PHASE 1 DONE ===")

    if getattr(args, 'phase1_only', False):
        log("=== phase1-only: skipping PHASE 2. Run with --collect to aggregate. ===")
        return

    pairs = [(t, m) for t, muts in tm.items() for m in muts if m != first_variant(muts)]
    log(f"=== PHASE 2: {len(pairs)} remaining variants, {workers} in parallel ===")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, t, f"{t}/{m}"): (t, m) for t, m in pairs}
        done = 0
        for fut in as_completed(futs):
            done += 1
            log(f"  PHASE2 progress: {done}/{len(pairs)}")
    log("=== FULL DATASET DONE. Run with --collect to aggregate. ===")


def _collect(out_path: Path):
    """Scan results/rq3/rq3_*/<task>/run_*/summary.json and aggregate the EVALUATION
    metrics into a CSV + console table. Stable data-collection entry (no temp commands)."""
    import csv
    fields = ["task_id", "mutation_task", "config", "total_cases", "total_cycles",
              "final_line_coverage", "final_branch_coverage",
              "peak_line_coverage", "peak_branch_coverage",
              "assertion_generated", "assertion_compilation_pass",
              "assertion_triggers", "distinct_assertions_triggered",
              "ground_truth_available", "ground_truth_detected", "ground_truth_detecting_cases",
              "total_token_input", "total_token_output",
              "assertion_gen_token_input", "assertion_gen_token_output",
              "generation_token_input", "generation_token_output",
              "min_reduced_n", "reduced_suite_cases", "reduced_suite_cycles",
              "tools_used_total", "total_elapsed", "run_dir"]
    rows = []
    for cfg_dir in sorted(RESULT_OUTPUT.glob("rq3_*")):
        for summ in sorted(cfg_dir.glob("*/run_*/summary.json")):
            try:
                d = json.loads(summ.read_text())
            except Exception:
                continue
            rr = d.get("reduced_repros") or []
            d["min_reduced_n"] = min((r.get("reduced_n", 0) for r in rr), default="")
            tut = d.get("tools_used_total")
            d["tools_used_total"] = json.dumps(tut, separators=(",", ":")) if tut else ""
            d["run_dir"] = str(summ.parent)
            rows.append({k: d.get(k, "") for k in fields})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in rows:
            w.writerow(r)
    log(f"Collected {len(rows)} runs -> {out_path}")
    hdr = (f"{'task':14} {'mut':10} {'cfg':5} {'line%':>6} {'br%':>5} {'aGen':>4} {'aTrg':>4} "
           f"{'dTrg':>4} {'GT':>3} {'cases':>5} {'cyc':>6} {'sCase':>5} {'sCyc':>5} {'tokIn':>7} {'tokOut':>6} {'minRed':>6}")
    print(hdr); print("-" * len(hdr))
    for r in rows:
        mut = str(r.get("mutation_task") or "").split("/")[-1]
        print(f"{str(r['task_id'])[:14]:14} {mut[:10]:10} {str(r['config']):5} "
              f"{str(r.get('final_line_coverage','')):>6} {str(r.get('final_branch_coverage','')):>5} "
              f"{str(r.get('assertion_generated','')):>4} {str(r.get('assertion_triggers','')):>4} "
              f"{str(r.get('distinct_assertions_triggered','')):>4} "
              f"{('Y' if r.get('ground_truth_detected') else 'n'):>3} "
              f"{str(r.get('total_cases','')):>5} {str(r.get('total_cycles','')):>6} "
              f"{str(r.get('reduced_suite_cases','')):>5} {str(r.get('reduced_suite_cycles','')):>5} "
              f"{str(r.get('total_token_input','')):>7} {str(r.get('total_token_output','')):>6} "
              f"{str(r.get('min_reduced_n','')):>6}")


def _run(task_id: str, args):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mut_tag = ""
    if args.mutation:
        m = re.search(r'mutation_(\w+)', args.mutation)
        mut_tag = f"mut{m.group(1)}_" if m else ""
    wd = RESULT_OUTPUT / f"rq3_{args.config}" / task_id / f"run_{mut_tag}{ts}"
    wd.mkdir(parents=True, exist_ok=True)
    ld = wd / "logs"; ld.mkdir(exist_ok=True)
    logger = Logger(str(ld), "rq3.log", level=LEVEL.DEBUG if args.debug else LEVEL.WARNING, console_output=True)
    config = AblationConfig(args.config)
    runner = RQ3Runner(task_id, config, wd, logger, mutation_task=args.mutation)
    s = runner.run(time_budget=args.budget, cases_per_iter=args.cases_per_iter, max_iterations=args.max_iterations)
    log(f"Done: {task_id} [{args.config}] line={s['final_line_coverage']:.1f}% branch={s['final_branch_coverage']:.1f}% "
        f"GT={'HIT' if s.get('ground_truth_detected') else 'miss'} elapsed={s['total_elapsed']}s")


if __name__ == "__main__":
    main()
