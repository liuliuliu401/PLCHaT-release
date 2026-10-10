# Configuration

PLCHaT is configured through environment variables and YAML files in this directory. Environment variables take precedence over YAML values.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `DASHSCOPE_API_KEY` | Provider-specific LLM API keys | - |
| `PLCHAT_LLM_API_KEY` | API key override for any provider | - |
| `PLCHAT_MODEL` / `PLCHAT_LLM_PROVIDER` / `PLCHAT_LLM_BASE_URL` | Override model / provider / base URL | values from `default.yaml` |
| `MATIEC_PATH` | MatIEC installation root | `/usr/local/lib/matiec` |
| `CC` | C compiler for harness builds | `clang-18` |
| `PLCHAT_BENCHMARK_ROOT` | Benchmark dataset location | `<repo>/benchmark/benchmark_260113` |

`PLCHAT_BENCHMARK_ROOT` is honored by the `main.py` CLI commands (`--demo`, `--full`, `--list-tasks`). The experiment runners under `experiments/` use the repository-relative default location.

## Configuration files

- `default.yaml` - all defaults: LLM settings, model profiles, agent assignments, execution environment (MatIEC/clang paths, scan cycle, timeouts), experiment directories, caches, tool budgets, benchmark settings, logging
- `local.yaml.example` - template for local overrides; copy to `config/local.yaml` and edit
- `constants.py` - bit-exact IEC 61131-3 type limits and model pricing constants

## Model profiles

Pre-configured profiles in `default.yaml` (`model_profiles`):

| Profile | Provider | Model | API key environment variable |
|---|---|---|---|
| `deepseek` (default) | deepseek | deepseek-chat | `DEEPSEEK_API_KEY` |
| `deepseek_v3` | deepseek | deepseek-v3 | `DEEPSEEK_API_KEY` |
| `openai` | openai | gpt-4o-mini | `OPENAI_API_KEY` |
| `openai_gpt4` | openai | gpt-4o | `OPENAI_API_KEY` |
| `qwen_cloud` | qwen | qwen-plus | `DASHSCOPE_API_KEY` |
| `local_qwen_14b` | local | qwen3-14B-local | - (local endpoint) |
| `local_qwen_32b` | local | qwen3-32b-local | - (local endpoint) |

Local profiles expect an OpenAI-compatible endpoint on localhost (see `default.yaml` for ports).
