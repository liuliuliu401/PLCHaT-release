# Harness Generator Implementation Summary

## Completed Modules

### 1. ST Parser (`st_parser.py`)
- Extracts variable classifications from ST source using regular expressions
- Supports VAR_INPUT/OUTPUT/IN_OUT/TEMP/CONSTANT blocks
- Supports array type parsing (ARRAY[lo..hi] OF TYPE)

### 2. POUS.h Parser (`pou_parser.py`)
- Parses MatIEC-generated POUS.h files
- Extracts array type definitions (__DECLARE_ARRAY_TYPE)
- Extracts variable declarations (__DECLARE_VAR)
- Produces a list of VarDecl

### 3. Interface Extractor (`interface_extractor.py`)
- Merges ST and POUS.h parsing results
- Combines them by variable-name matching
- Produces a complete POUInfo object

### 4. Harness Generator (`harness_gen.py`)
- Generates harness.c via Jinja2 templates
- Automatically expands array variables
- Supports all IEC 61131-3 basic types

### 5. Schema Generator (`schema_gen.py`)
- Generates the input_schema_v2.json data contract
- Conforms to ExpUnifiedIR validation requirements
- Correctly handles array expansion and st_binding mapping

### 6. Seed Generator (`seed_gen.py`)
- Generates the initial input.txt seeds
- Includes zero, one, boundary, and random values
- Supports boundary value definitions for IEC types

### 7. Unified Pipeline (`pipeline.py`)
- Complete ST -> harness suite automation flow
- Integrates the MatIEC compiler (preprocessing + enhanced library import)
- Error handling and logging
- CLI: `python -m harness.compiler.generator.pipeline <st_path> <output_dir>`

## Module Structure

```
harness/compiler/generator/
├── __init__.py              # Data type definitions (VarDecl, POUInfo, GenerationResult)
├── st_parser.py             # ST source parser
├── pou_parser.py            # POUS.h parser
├── interface_extractor.py   # Interface extractor (merges ST and POUS.h)
├── harness_gen.py           # harness.c generator
├── schema_gen.py           # Schema generator
├── seed_gen.py             # Seed generator
├── pipeline.py             # Unified pipeline entry point
└── templates/
    └── harness.c.j2        # Jinja2 template
```

## Usage

### CLI
```bash
python -m harness.compiler.generator.pipeline <st_file> <output_dir>
```

### Python API
```python
from harness.compiler.generator.pipeline import HarnessPipeline
from pathlib import Path

pipeline = HarnessPipeline(debug=True)
result = pipeline.synthesize(
    st_path=Path("program.st"),
    output_dir=Path("output/")
)

if result.success:
    print(f"Generated: {result.harness_path}")
    print(f"Generated: {result.schema_path}")
    print(f"Generated: {result.seed_path}")
```

## Generated Output

For an input ST file, the output directory contains:
```
output_dir/
├── harness.c              # C test driver
├── input_schema_v2.json   # Data contract
├── input.txt              # Initial seeds
└── temp_compile/          # MatIEC compile output
    ├── POUS.c
    ├── POUS.h
    └── ...
```

## Pending Features

### LLM Fallback Strategy
When generation fails, use an LLM to automatically repair harness.c:
- Syntax error fixes
- Type mismatch fixes
- Array index error fixes

## Test Results

Benchmarks tested:
- ✓ 213_MultiPumpCtrl (5 inputs, 1 output, 2 arrays)
- ✓ 212_FindMinMaxValues (1 array input, 4 scalar outputs)

Generated files compile and are correctly formatted.
