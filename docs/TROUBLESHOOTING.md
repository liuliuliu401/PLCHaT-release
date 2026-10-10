# Troubleshooting

Common issues and solutions. For installation steps, see the [README](README.md).

## `iec2c: command not found`

```bash
# Check MatIEC status
python main.py --matiec-check

# Install MatIEC
sudo ./scripts/install_matiec.sh

# Set environment variable
export MATIEC_PATH=/usr/local/lib/matiec
```

## `clang-18: command not found`

```bash
sudo apt-get install clang-18
# or use the system clang
export CC=clang
```

## `MATIEC_PATH not set`

Add to `~/.bashrc`:

```bash
export MATIEC_PATH=/usr/local/lib/matiec
```

## LLM API timeout

Check your API key and network connection. See [config/README.md](config/README.md) for API key configuration.

## Harness generation fails with compilation error

```bash
# Check MatIEC installation
python main.py --matiec-check

# Verify ST file syntax
cat your_file.st
```
