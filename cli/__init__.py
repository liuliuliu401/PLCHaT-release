"""
PLChaT CLI Module

CLI command implementations for main.py
"""

from pathlib import Path
import sys
import os
import argparse
import shutil

# Project root resolution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config, get_matiec_path, get_cache_dir


# ============================================================================
# System Information Commands
# ============================================================================

def cmd_info(args):
    """Show system information."""
    print("PLChaT - Domain-Specific Test Harness for IEC 61131-3 PLC Programs")
    print()
    print("Project Root:", PROJECT_ROOT)
    print("Python Version:", sys.version.split()[0])
    print()

    config = get_config()

    print("Configuration:")
    print("  LLM Provider:", config.get("llm", {}).get("provider", "not set"))
    print("  LLM Model:", config.get("llm", {}).get("model", "not set"))
    print("  Base URL:", config.get("llm", {}).get("base_url", "not set"))
    api_key = config.get("llm", {}).get("api_key")
    print("  API Key:", "***set***" if api_key else "not set")
    print()

    matiec_path = get_matiec_path()
    print("MatIEC Path:", matiec_path if matiec_path else "not found")

    print()
    print("Cache Directories:")
    for cache_type in ["compilation", "coverage", "schema", "harness"]:
        cache_dir = get_cache_dir(cache_type)
        exists = "✓" if cache_dir.exists() else "✗"
        print(f"  {cache_type}: {cache_dir} {exists}")


def cmd_verify(args):
    """Verify installation."""
    print("Verifying PLChaT installation...")

    errors = []

    # Check Python dependencies
    import yaml
    print("✓ PyYAML installed")

    import pydantic
    print("✓ Pydantic installed")

    import z3
    print("✓ Z3 installed")

    # Check configuration
    config = get_config()
    print("✓ Configuration loaded")

    if config.get("llm", {}).get("api_key"):
        print("✓ LLM API key configured")
    else:
        print("⚠ LLM API key not set (set PLCHAT_LLM_API_KEY or DEEPSEEK_API_KEY)")

    # Check MatIEC
    matiec_path = get_matiec_path()
    iec2c_paths = [
        Path(matiec_path) / "iec2c" if matiec_path else Path(),
        Path("/usr/local/bin/iec2c"),
        Path("/usr/bin/iec2c"),
    ]

    iec2c_found = any(p.exists() for p in iec2c_paths if p)
    if iec2c_found:
        print("✓ MatIEC (iec2c) found")
    else:
        errors.append("MatIEC (iec2c) not found")

    # Check clang
    clang_path = shutil.which("clang-18") or shutil.which("clang")
    if clang_path:
        print(f"✓ Clang found: {clang_path}")
    else:
        errors.append("Clang not found")

    print()
    if errors:
        print("Errors found:")
        for err in errors:
            print(f"  ✗ {err}")
        return 1
    else:
        print("✓ All checks passed!")
        return 0


def cmd_cache(args):
    """Cache management commands."""

    if args.status:
        print("Cache Status:")
        print()

        total_size = 0
        for cache_type in ["compilation", "coverage", "schema", "harness"]:
            cache_dir = get_cache_dir(cache_type)
            if cache_dir.exists():
                size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
                total_size += size
                size_mb = size / (1024 * 1024)
                file_count = len(list(cache_dir.rglob("*")))
                print(f"  {cache_type:12} : {cache_dir}")
                print(f"    Size: {size_mb:.1f} MB, Files: {file_count}")
            else:
                print(f"  {cache_type:12} : {cache_dir} (empty)")
        print()
        print(f"  Total: {total_size / (1024 * 1024):.1f} MB")

    if args.clean:
        cleaned = 0

        if args.all:
            for cache_type in ["compilation", "coverage", "schema", "harness"]:
                cache_dir = get_cache_dir(cache_type)
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)
                    print(f"✓ Cleaned {cache_type}")
                    cleaned += 1
            print()
            print(f"Cleaned {cleaned} cache directories")

        elif args.compilation:
            cache_dir = get_cache_dir("compilation")
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                print("✓ Cleaned compilation cache")
        elif args.coverage:
            cache_dir = get_cache_dir("coverage")
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                print("✓ Cleaned coverage cache")
        elif args.schema:
            cache_dir = get_cache_dir("schema")
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                print("✓ Cleaned schema cache")
        elif args.harness:
            cache_dir = get_cache_dir("harness")
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                print("✓ Cleaned harness cache")


# ============================================================================
# MatIEC Commands
# ============================================================================

def cmd_matiec_check(args):
    """Check MatIEC installation status."""
    import subprocess

    print("MatIEC Installation Check")
    print("=" * 40)

    issues = []

    # Check MATIEC_PATH
    matiec_path = os.getenv("MATIEC_PATH")
    if matiec_path:
        print(f"✓ MATIEC_PATH set: {matiec_path}")
    else:
        print("⚠ MATIEC_PATH not set")
        issues.append("Set MATIEC_PATH environment variable")

    # Check iec2c in PATH
    iec2c_in_path = shutil.which("iec2c")
    if iec2c_in_path:
        print(f"✓ iec2c in PATH: {iec2c_in_path}")
    else:
        print("✗ iec2c not found in PATH")
        issues.append("iec2c not in PATH")

    # Locate iec2c binary
    iec2c_locations = []

    if matiec_path:
        iec2c_locations.append(Path(matiec_path) / "bin" / "iec2c")

    if iec2c_in_path:
        iec2c_locations.append(Path(iec2c_in_path))

    iec2c_locations.extend([
        Path("/usr/local/bin/iec2c"),
        Path("/usr/bin/iec2c"),
        Path("/usr/local/lib/matiec/bin/iec2c"),
    ])

    iec2c_found = None
    for loc in iec2c_locations:
        if loc.exists() and loc.is_file():
            iec2c_found = loc
            break

    if iec2c_found:
        print(f"✓ iec2c binary found: {iec2c_found}")

        try:
            result = subprocess.run(
                [str(iec2c_found), "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.split("\n")[0]
                print(f"  Version: {version}")
        except Exception:
            print("  ⚠ Could not determine version")
    else:
        print("✗ iec2c binary not found")
        issues.append("iec2c binary not found")

    print()
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"  ✗ {issue}")
        print()
        print("To install MatIEC:")
        print("  sudo ./scripts/install_matiec.sh")
        print("  or")
        print("  python main.py --matiec-guide")
        return 1
    else:
        print("✓ MatIEC is properly installed!")
        return 0


def cmd_matiec_install_guide(args):
    """Print MatIEC installation guide."""
    print("""
MatIEC Installation Guide
========================

MatIEC is the IEC 61131-3 compiler required by PLCHaT.

Method 1: Automated Installation (Recommended)
  Run the installation script:

    sudo ./scripts/install_matiec.sh

  Or install to a user directory:

    ./scripts/install_matiec.sh ~/matiec

Method 2: Manual Installation

  1. Install dependencies:
     sudo apt-get install build-essential flex bison

  2. Clone and build MatIEC:
     git clone https://github.com/beremiz/matiec /tmp/matiec
     cd /tmp/matiec
     ./configure --prefix=/usr/local/lib/matiec
     make
     sudo make install

  3. Create symlink (optional):
     sudo ln -sf /usr/local/lib/matiec/bin/iec2c /usr/local/bin/iec2c

After Installation:

  Set the MATIEC_PATH environment variable:

    export MATIEC_PATH=/usr/local/lib/matiec

  Add to ~/.bashrc or ~/.zshrc for persistence:

    echo 'export MATIEC_PATH=/usr/local/lib/matiec' >> ~/.bashrc

  Verify installation:

    python main.py --matiec-check
""")


# ============================================================================
# Harness Commands
# ============================================================================

def cmd_harness_generate(args):
    """Generate test harness from ST source code."""
    from harness.compiler.generator.pipeline import HarnessPipeline

    st_path = Path(args.st_path)
    output_dir = Path(args.output)

    if not st_path.exists():
        print(f"Error: ST file not found: {st_path}")
        return 1

    print(f"Generating harness from: {st_path}")
    print(f"Output directory: {output_dir}")
    print()

    pipeline = HarnessPipeline(debug=args.debug)
    result = pipeline.synthesize(st_path, output_dir, force_rebuild=args.force)

    if result.success:
        print(f"✓ Success! Generated files in: {output_dir}")
        print(f"  - harness.c")
        print(f"  - input_schema_v2.json")
        print(f"  - input.txt")
        return 0
    else:
        print(f"✗ Failed: {result.error}")
        if result.compilation_log:
            print("\nCompilation log:")
            print(result.compilation_log)
        return 1


def cmd_harness_compile(args):
    """Compile harness to binary."""
    from harness.compiler.executor import STExecutor

    harness_path = Path(args.harness)
    output_dir = Path(args.output) if args.output else Path(args.harness).parent

    print(f"Compiling harness: {harness_path}")
    print(f"Output directory: {output_dir}")
    print()

    executor = STExecutor(root_dir=str(PROJECT_ROOT), debug=args.debug)

    result = executor.compile_harness_to_binary(
        harness_path=str(harness_path),
        output_dir=str(output_dir)
    )

    if result.success:
        print(f"✓ Success! Binary: {result.binary_path}")
        return 0
    else:
        print(f"✗ Failed: {result.error}")
        return 1


def cmd_coverage_collect(args):
    """Collect coverage information."""
    from harness.compiler.coverage import CoverageCollector

    binary_path = Path(args.binary)
    output_dir = Path(args.output) if args.output else binary_path.parent

    print(f"Collecting coverage for: {binary_path}")
    print(f"Output directory: {output_dir}")
    print()

    collector = CoverageCollector(
        binary_path=str(binary_path),
        output_dir=str(output_dir),
        profdata_path=args.profdata
    )

    result = collector.collect()

    if result.success:
        print(f"✓ Coverage collected")
        print(f"  Summary: {result.summary_path}")
        if result.report_path:
            print(f"  Report: {result.report_path}")
        return 0
    else:
        print(f"✗ Failed: {result.error}")
        return 1


# ============================================================================
# Pipeline Commands (End-to-end)
# ============================================================================

def cmd_pipeline_run(args):
    """Run end-to-end testing pipeline."""
    import json
    from harness.routing.policies import RoutingStrategy

    st_path = Path(args.st_path)
    output_dir = Path(args.output) if args.output else st_path.parent / "output"

    if not st_path.exists():
        print(f"Error: ST file not found: {st_path}")
        return 1

    print(f"Running pipeline for: {st_path.name}")
    print(f"Output directory: {output_dir}")
    print()

    # Step 1: Generate harness
    print("Step 1: Generating harness...")
    from harness.compiler.generator.pipeline import HarnessPipeline
    pipeline = HarnessPipeline(debug=args.debug)
    harness_result = pipeline.synthesize(st_path, output_dir, force_rebuild=args.force)

    if not harness_result.success:
        print(f"✗ Harness generation failed: {harness_result.error}")
        return 1

    print(f"✓ Harness generated: {harness_result.harness_path}")

    # Find schema path
    schema_path = output_dir / "input_schema_v2.json"
    if not schema_path.exists():
        # Try alternative location
        alt_schema = st_path.parent.parent / "input" / "input_schema_v2.json"
        if alt_schema.exists():
            schema_path = alt_schema
        else:
            print(f"✗ Schema file not found")
            return 1

    # Step 2: Compile harness
    print("\nStep 2: Compiling harness...")
    from harness.compiler.executor import STExecutor
    from harness.compiler.st_compiler_only import MatIECCompiler
    import shutil
    import os

    executor = STExecutor(root_dir=str(PROJECT_ROOT), debug=args.debug)

    # Compile ST to C in the output directory to get POUS.h and POUS.c
    matiec_compiler = MatIECCompiler(debug=args.debug)
    compile_result = matiec_compiler.compile_st_to_c(
        st_file=str(st_path),
        output_dir=str(output_dir),
        preprocess=True
    )

    if not compile_result.success:
        print(f"✗ MatIEC compilation failed: {compile_result.error}")
        return 1

    # Apply header patches to generated C files (required for POUS.c)
    from harness.compiler.utils import patch_pous_setvar_time_to_dint
    patch_pous_setvar_time_to_dint(str(output_dir))

    # Add required headers to generated C files
    patch_headers = """#include "iec_types.h"
#include "iec_types_all.h"
#include "iec_std_lib.h"
#include "iec_std_FB.h"
#include "accessor.h"
#include "POUS.h"
"""
    for c_file in output_dir.glob("*.c"):
        if c_file.name == "harness.c":
            continue
        content = c_file.read_text(encoding='utf-8')
        if '#include "iec_std_lib.h"' not in content:
            c_file.write_text(patch_headers + "\n" + content, encoding='utf-8')

    # Get MatIEC library path from environment or iec2c location
    matiec_c_lib_dir = os.environ.get("MATIEC_C_LIB_DIR")
    matiec_include_dirs = [str(output_dir)]  # Add output_dir for POUS.h

    if matiec_c_lib_dir:
        matiec_include_dirs.append(matiec_c_lib_dir)
    else:
        iec2c = shutil.which("iec2c")
        if iec2c:
            matiec_bin_dir = Path(iec2c).parent
            matiec_lib = matiec_bin_dir.parent / "lib" / "C"
            if matiec_lib.exists():
                matiec_include_dirs.append(str(matiec_lib))
                matiec_c_lib_dir = str(matiec_lib)
            else:
                # Try sibling lib directory
                matiec_lib = matiec_bin_dir.parent / "lib" / "C"
                if matiec_lib.exists():
                    matiec_include_dirs.append(str(matiec_lib))
                    matiec_c_lib_dir = str(matiec_lib)

    # Find all C files to compile (POUS.c + harness.c + MatIEC lib files)
    c_files = []
    for f in output_dir.glob("*.c"):
        if f.name != "harness.c":  # Will add harness separately
            c_files.append(str(f))
    c_files.append(str(harness_result.harness_path))

    # Add MatIEC library C files (required for __INIT_VAR, TRUE, FALSE, etc.)
    if matiec_c_lib_dir and Path(matiec_c_lib_dir).exists():
        for file in Path(matiec_c_lib_dir).glob("*.c"):
            if "iec_std_lib" in file.name or "accessor" in file.name:
                c_files.append(str(file))

    output_binary = str(output_dir / "plc_harness")

    if args.debug:
        print(f"  MATIEC_C_LIB_DIR: {matiec_c_lib_dir}")
        print(f"  Include dirs: {matiec_include_dirs}")
        print(f"  C files: {c_files}")

    compile_ok = executor.compile_c_to_binary(
        source_files=c_files,
        output_binary=output_binary,
        include_dirs=matiec_include_dirs,
        libraries=[],
        coverage_mode=False
    )

    if not compile_ok:
        print(f"✗ Compilation failed")
        return 1

    print(f"✓ Binary compiled: {output_binary}")

    # Step 3: Generate test cases
    print(f"\nStep 3: Generating test cases (strategy: {args.strategy})...")

    # Load schema for test generation
    with open(schema_path) as f:
        schema = json.load(f)

    # Generate random test cases
    from tools.fuzzers.random.generator import RandomCaseGenerator
    from core.data_types.exp_types import ExpUnifiedIR

    rng = RandomCaseGenerator(seed=42)
    num_cases = 30
    num_cycles = 8

    test_cases = []
    for i in range(num_cases):
        sparse_timeline = {}
        for cycle in range(num_cycles):
            case = rng.generate_case(st_path.read_text(encoding='utf-8'), schema)
            if case:
                sparse_timeline[cycle] = case
        if sparse_timeline:
            test_cases.append(ExpUnifiedIR(
                exp_id=f"demo_case_{i}",
                target_st_path=str(st_path),
                schema_path=str(schema_path),
                tester_type="random_demo",
                total_cycles=len(sparse_timeline),
                sparse_timeline=sparse_timeline
            ))

    print(f"✓ Generated {len(test_cases)} test cases")

    # Step 4: Execute tests and collect coverage
    print("\nStep 4: Executing tests with coverage collection...")
    from harness.compiler.st_coverage_collector import STCoverageCollector

    collector = STCoverageCollector(
        root_dir=str(PROJECT_ROOT),
        debug=args.debug,
        default_output_format="StoredTestCase",
        llvm_version=18
    )

    try:
        result = collector.execute_with_multiple_coverage(
            st_code_input=str(st_path),
            harness_input=str(harness_result.harness_path),
            input_data_list=test_cases[:50],
            benchmark_case=st_path.stem,
            reuse_compilation=True,
            output_format="StoredTestCase"
        )
    except Exception as e:
        print(f"✗ Execution failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1

    # Step 5: Report results
    print("\nStep 5: Results")
    print("=" * 50)

    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    # Extract coverage information
    coverage_percent = 0.0
    for line in stdout.split('\n'):
        if 'coverage' in line.lower() or 'Coverage' in line:
            print(f"  {line}")

    # Check for errors
    if stderr and 'ASSERTION' in stderr:
        print(f"\n  Assertion violations detected:")
        for line in stderr.split('\n'):
            if 'ASSERTION' in line:
                print(f"    {line.strip()}")

    print(f"\n✓ Pipeline complete!")
    print(f"  Test cases executed: {len(test_cases)}")
    print(f"  Results in: {output_dir}")

    return 0


def cmd_pipeline_demo(args):
    """Run pipeline demo with sample task."""
    # Use 211_StackMin as a simple, reliable demo task
    bench_root = Path(os.environ.get(
        "PLCHAT_BENCHMARK_ROOT",
        str(PROJECT_ROOT / "benchmark" / "benchmark_260113")))
    sample_st = bench_root / "benchmark_raw" / "211_StackMin" / "plc_st_files" / "211_StackMin.st"

    if not sample_st.exists():
        print(f"Error: Demo ST file not found: {sample_st}")
        return 1

    print(f"Running demo with: {sample_st.name}")
    print()

    # Create output directory
    output_dir = PROJECT_ROOT / "temp" / "demo_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    args.st_path = str(sample_st)
    args.output = str(output_dir)
    args.debug = True
    args.force = False
    args.strategy = "random"

    return cmd_pipeline_run(args)
