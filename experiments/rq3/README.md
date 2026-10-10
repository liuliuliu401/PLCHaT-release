# RQ3: Component Ablation Studies

## Overview

The RQ3 experiments evaluate the impact of each PLCHaT component on testing effectiveness, focusing on:

- Fault detection effectiveness (mutation kill rate)
- Coverage metrics (branch/line coverage)
- Token efficiency (input/output tokens per iteration)
- Assertion generation and trigger rate

## Experiment Configuration

| Configuration | Description | enable_distillation | enable_truncation | enable_oracle | enable_metrics |
|-----|------|-------------------|------------------|--------------|---------------|
| **C1** | Full Framework (distill + oracle) | ✅ | ❌ | ✅ | ✅ |
| **C2** | w/o Distill (naive truncation) | ❌ | ✅ | ✅ | ✅ |
| **C3** | w/o Trace Distillation (raw trace) | ❌ | ❌ | ✅ | ✅ |
| **C4** | w/o Active Oracle in feedback | ✅ | ❌ | ❌ | ✅ |
| **C0** | No inter-round feedback | ❌ | ❌ | ❌ | ❌ |
| **E_raw** | Raw output (no oracle/metrics) | ❌ | ❌ | ❌ | ❌ |

## Usage

### Fast Mode

```bash
# Test 3 tasks with the C1 configuration
python -m experiments.run rq3 --config C1 --fast

# Test 3 tasks with the C4 configuration
python -m experiments.run rq3 --config C4 --fast
```

### Full Experiment

```bash
# Run all tasks
python -m experiments.run rq3 --config C1

# Run specific tasks
python -m experiments.run rq3 --config C1 --tasks 211_StackMin 212_FindMinMaxValues

# Limit the number of mutations per task
python -m experiments.run rq3 --config C1 --max-mutations 10
```

## Result Output

### Result Files

- Location: `output/rq3_results/run_{config}_{timestamp}/results.csv`
- Format: CSV file with the following columns:
  - Config: configuration ID
  - Task: task ID
  - Mutation: mutation ID (if applicable)
  - Killed: killed mutations / total
  - Valid: valid mutations / total
  - BranchCov: branch coverage
  - LineCov: line coverage
  - TokIn/it: input tokens per iteration
  - TokOut/it: output tokens per iteration
  - AssertTriggered: number of triggered assertions
  - Duration(s): runtime (seconds)
  - Status: status
  - Note: note

### Log Files

- Location: `output/rq3_results/run_{config}_{timestamp}/logs/rq3_{config}.log`

## Code Structure

```
experiments/rq3/
├── __init__.py       # Module initialization
├── config.py         # AblationConfig configuration class
└── runner.py         # RQ3Runner experiment runner
```

## Implementation Notes

The current version is a simplified implementation of the RQ3 experiment, focused on:
1. Providing clear configuration definitions (C0-C4, E_raw)
2. Supporting the basic experiment run flow
3. Recording key metrics (coverage, token usage, assertion triggers)

The full experiment implementation (including Generator agent integration) can be found in the original PLCHaT project:
`experiments/rq3/rq3_runner_v3.py`

## Migration Status

- ✅ Configuration definitions (C0-C4, E_raw)
- ✅ Basic experiment runner
- ✅ Unified entry-point integration
- ⏳ Generator agent integration (pending)
- ⏳ Full feedback mechanism implementation (pending)

## References

- Paper definition: `docs/paper/chapters/04_experiments.tex`
- Original implementation: `experiments/rq3/`
- Data table: `docs/paper/figures/04_tab_rq3_ablation.tex`
