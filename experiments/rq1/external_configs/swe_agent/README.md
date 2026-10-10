# SWE-Agent PLC Baseline Configuration

This directory contains custom configuration for running SWE-agent as a baseline for RQ1 experiments.

## Files

- `plc_harness.yaml`: SWE-agent configuration for PLC test harness generation
- `Dockerfile`: Docker image with MatIEC and clang-18 for SWE-agent execution
- `problem_statement.md`: Task description for SWE-agent

## Setup

1. **Provide SWE-agent path**:
   ```bash
   python -m experiments.run rq1 --baseline swe-agent \
       --external-lib swe-agent=/path/to/swe-agent
   ```

2. **Copy configuration** (automatic on first run):
   The `plc_harness.yaml` will be copied to `<swe-agent>/config/` directory

3. **Build Docker image** (if using container):
   ```bash
   cd /path/to/matiec
   docker build -t sweagent-plc:latest \
       -f /path/to/PLCHaT-release/experiments/rq1/external_configs/swe_agent/Dockerfile .
   ```

## Running

```bash
# Table 1 (Pipeline quality)
python -m experiments.run rq1 --baseline swe-agent --table1

# With specific tasks
python -m experiments.run rq1 --baseline swe-agent --table1 --tasks 211_StackMin 216_RandomNumber

# Fast mode (3 tasks)
python -m experiments.run rq1 --baseline swe-agent --table1 --fast
```

## Requirements

- SWE-agent installation
- MatIEC (ST to C compiler)
- Docker (if using container mode)
- Local LLM API (http://localhost:8002/v1 by default)
