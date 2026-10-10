# PLCHaT: A Unified Agentic Harness for Automated Testing of PLC Programs

PLCHaT is a domain-specific agentic harness that bridges agent actions with PLC runtime semantics. It provides cycle-aware execution interfaces, standardized engine routing, and intent-aligned observation modules that enable testing agents to operate on IEC 61131-3 PLC programs without rebuilding custom runtimes.

## Purpose

This repository provides the harness compiler, testing engines, and the end-to-end testing pipeline:

1. **Harness Compiler**: Structured Text (ST) to C transpiler with instrumentation
2. **Testing Tools**: AFL++ (coverage-guided fuzzing), Random Fuzzer, Dynamic Symbolic Execution (DSE), LLM-Guided Testing
3. **Tool Router**: Multi-strategy routing for test engine selection
4. **Benchmark**: companion dataset repository (49 ST programs, 318 mutants)

## Testing Pipeline

PLCHaT separates the testing infrastructure (the **agentic harness**) from the testing driver (the **agent**). The harness alone is an execution environment; a valid testing pipeline is an agent running on the harness.

This **Agentic harness** consists of four components:

1. **Action**: parses testing intents and routes them to tools
2. **Tools**: orchestrated test generation engines - random fuzzer, mutation fuzzing (AFL++), dynamic symbolic execution (DSE with Z3), LLM-guided generation - with a router that matches program characteristics to engines
3. **Runtime**: compiles ST to C (MatIEC), synthesizes an instrumented cycle-aware driver (Clang), and executes test payloads per scan cycle with optional coverage instrumentation
4. **Observation**: generated oracles (assertions) checked per scan cycle; long execution traces compressed into source-mapped diagnostic feedback

The harness exposes uniform execution and observation interfaces for agent interaction.

**Agent**. A testing agent drives the loop: select tools, execute on the runtime, observe feedback, iterate within a time budget. This repository provides one agent implementation (LLM-based, `agents/`): planner / generator / evaluator / router roles, with selectable routing strategies (see Usage).

The `--pipeline` and `--full` commands run this agent-on-harness loop end to end; `--demo` runs it on a sample task.

## Dataset Setup

The benchmark programs are distributed in the companion repository [PLCHaT-dataset](https://github.com/liuliuliu401/PLCHaT-dataset):

```bash
git clone https://github.com/liuliuliu401/PLCHaT-dataset benchmark/benchmark_260113
```

The default dataset location is `benchmark/benchmark_260113/` (relative to the repository root), containing `benchmark_raw/` (49 reference programs) and `benchmark_mutated/` (45 tasks, 318 mutants).

To use a dataset at another location, set `PLCHAT_BENCHMARK_ROOT`:

```bash
export PLCHAT_BENCHMARK_ROOT=/path/to/PLCHaT-dataset
```

## Installation

Installation is manual: it installs system packages and builds MatIEC from source. This repository does not automate these steps.

### Requirements

- OS: Ubuntu 20.04+ or similar
- Python: 3.8+
- Disk: 10GB free space
- RAM: 4GB minimum

### Steps

```bash
# 1. Install system dependencies
sudo apt-get update
sudo apt-get install -y clang-18 python3.8 python3-pip git build-essential flex bison

# 2. Install MatIEC compiler (IEC 61131-3 compiler)

# Option A: Automated installation (recommended)
sudo ./scripts/install_matiec.sh

# Option B: Manual installation
git clone https://github.com/beremiz/matiec /tmp/matiec
cd /tmp/matiec && ./configure --prefix=/usr/local/lib/matiec && make && sudo make install

# Set MatIEC path
export MATIEC_PATH=/usr/local/lib/matiec

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Set LLM API key (for LLM-guided features)
export DEEPSEEK_API_KEY="your-api-key"

# 5. Verify installation
python main.py -v
python main.py --matiec-check
```

## Usage

All commands are option-style flags on a single entry point. `python main.py --help` lists the full command surface.

### System and MatIEC

```bash
python main.py -v                     # Verify installation
python main.py -i                     # Show system information
python main.py --matiec-check         # Check MatIEC installation status
python main.py --matiec-guide         # Show MatIEC installation guide
python main.py --cache-status         # Show cache status
python main.py --cache-clean --all    # Clean all caches
```

### Harness Generation

Generate a test harness from an ST source file:

```bash
python main.py --generate benchmark/benchmark_260113/benchmark_raw/211_StackMin/plc_st_files/211_StackMin.st -o output/211_StackMin
```

This produces `harness.c`, `input_schema_v2.json`, and `input.txt` in the output directory.

### End-to-End Pipeline

```bash
# Run pipeline on an ST file (strategies: random, llm, fixed, mab)
python main.py --pipeline <st_file> -o <output_dir> -s random

# Run with the sample task
python main.py --demo

# Run the complete RQ3 chain on a benchmark task
python main.py --full 211_StackMin --mode full --assertions

# List available benchmark tasks
python main.py --list-tasks
```

### Coverage

```bash
# Collect coverage from a compiled binary
python main.py --coverage <binary_path> -o <output_dir>
```

## Configuration

Environment variables (LLM API keys, MatIEC path, dataset location), configuration files, and pre-configured model profiles are documented in [config/README.md](config/README.md).

## Directory Structure

```
├── main.py                    # CLI entry point
├── run.py                     # Experiment runner (demo and RQ modes)
├── requirements.txt           # Python dependencies
├── cli/                       # CLI command implementations
├── config/                    # Configuration files (see config/README.md)
├── harness/                   # Core harness
│   ├── compiler/              # ST to C compiler
│   ├── test_analysis/         # Test analysis and assertion generation
│   ├── routing/               # Tool routing
│   └── oracle/                # Violation detection
├── tools/                     # Testing tools
│   ├── fuzzers/               # AFL++, Random, DSE
│   └── solvers/               # Z3 solver
├── agents/                    # LLM agents (generator, prompts, router)
├── core/                      # Data types, protocols, evaluation
├── experiments/               # RQ1/RQ2/RQ3 experiment scripts
├── scripts/                   # Installation and helper scripts
├── benchmark/                 # Dataset checkout (see Dataset Setup)
└── temp/                      # Temporary files and cache
```

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## License

Apache License 2.0 - see the [LICENSE](LICENSE) file.

## Acknowledgments

This work uses the following open-source components:

- MatIEC: IEC 61131-3 compiler (https://github.com/beremiz/matiec)
- AFL++: Coverage-guided fuzzing (https://github.com/AFLplusplus/AFLplusplus)
- Z3: SMT solver (https://github.com/Z3Prover/z3)
