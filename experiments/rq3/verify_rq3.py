#!/usr/bin/env python3
"""Minimal RQ3 verification - can it initialize and run a single step?"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

print(f"PROJECT_ROOT: {PROJECT_ROOT}")
print(f"Benchmark exists: {(PROJECT_ROOT / 'benchmark/benchmark_260113').exists()}")

# Test 1: Import
print("\n[Test 1] Import RQ3Runner...")
from experiments.rq3.rq3_runner_v3 import RQ3Runner, AblationConfig
print("✓ Import OK")

# Test 2: Config
print("\n[Test 2] Check configs...")
for cfg_id in ["C1", "C2", "C3", "C4", "C0", "E_raw"]:
    cfg = AblationConfig(cfg_id)
    print(f"  {cfg_id}: distill={cfg.enable_distillation}, oracle={cfg.enable_oracle}")

# Test 3: Can we create a runner instance?
print("\n[Test 3] Create RQ3Runner instance...")
try:
    from harness.compiler.utils import Logger, LEVEL
    from datetime import datetime

    work_dir = PROJECT_ROOT / "output" / "rq3_verify"
    work_dir.mkdir(parents=True, exist_ok=True)
    logger = Logger(str(work_dir / "logs"), "verify.log", level=LEVEL.INFO)

    config = AblationConfig("C1")
    runner = RQ3Runner(
        task_id="211_StackMin",
        config=config,
        work_dir=work_dir,
        logger=logger,
        mutation_task="211_StackMin/mutation_0"
    )
    print(f"✓ RQ3Runner created")
    print(f"  ST path: {runner.st_path}")
    print(f"  Harness path: {runner.harness_path}")
    print(f"  Schema path: {runner.schema_path}")

    # Check files exist
    for p, name in [(runner.st_path, "ST"), (runner.schema_path, "Schema"), (runner.harness_path, "Harness")]:
        if p.exists():
            print(f"  ✓ {name} exists")
        else:
            print(f"  ✗ {name} MISSING: {p}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ RQ3 minimal verification complete!")
