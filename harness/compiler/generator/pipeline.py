"""
Harness Pipeline - Unified Entry

Complete ST to Harness suite automation pipeline:
1. Call MatIEC compiler (preprocessing + enhanced library)
2. Parse ST source code to obtain variable classification
3. Parse POUS.h to get MatIEC structure information
4. Generate harness.c
5. Generate input_schema_v2.json
6. Generate input.txt
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

# Safe import method
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.st_compiler_only import MatIECCompiler
from harness.compiler.generator.interface_extractor import InterfaceExtractor
from harness.compiler.generator.harness_gen import HarnessGenerator
from harness.compiler.generator.schema_gen import SchemaGenerator
from harness.compiler.generator.seed_gen import SeedGenerator
from harness.compiler.utils import Logger, LEVEL

# Temporary directory configuration - use unified /temp/ directory
from config.temp_dirs import get_compile_temp_dir, get_unique_temp_path


@dataclass
class PipelineResult:
    """Pipeline execution result"""
    success: bool
    st_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    harness_path: Optional[Path] = None
    schema_path: Optional[Path] = None
    seed_path: Optional[Path] = None
    pou_info: Optional[Dict] = None
    error: Optional[str] = None
    warnings: list = field(default_factory=list)
    compilation_log: str = ""


class HarnessPipeline:
    """
ST → Harness suite automation pipeline

Complete workflow:
ST source code → [MatIEC compilation] → POUS.h + POUS.c → [parsing] → POUInfo → [generation] → {harness.c, schema.json, input.txt}
    """

    def __init__(
        self,
        matiec_path: Optional[str] = None,
        debug: bool = False,
        logger: Optional[Logger] = None
    ):
        """
Initialize pipeline

        Args:
matiec_path: MatIEC installation path (None for auto-detection)
debug: debug mode
logger: log recorder
        """
        self.debug = debug
        self.logger = logger or Logger("/tmp/plchat_pipeline", "pipeline.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)

        # Initialize MatIEC compiler
        self.matiec_compiler = MatIECCompiler(
            matiec_path=matiec_path,
            logger=self.logger,
            debug=debug
        )

        # Check MatIEC installation
        ok, msg = self.matiec_compiler.check_installation()
        if not ok:
            self.logger.error_print(f"MatIEC not available: {msg}")
            raise RuntimeError(f"MatIEC not available: {msg}")

        # Initialize generator components
        self.interface_extractor = InterfaceExtractor(debug=debug)
        self.harness_generator = HarnessGenerator()
        self.schema_generator = SchemaGenerator()
        self.seed_generator = SeedGenerator()

    def synthesize(
        self,
        st_path: Path,
        output_dir: Path,
        force_rebuild: bool = False
    ) -> PipelineResult:
        """
# Execute the full synthesis process.

        Args:
st_path: ST source file path
output_dir: Output directory
force_rebuild: Force recompile

        Returns:
PipelineResult object
        """
        result = PipelineResult(success=False, st_path=st_path, output_dir=output_dir)

        try:
            self.logger.info_print(f"Starting synthesis for: {st_path}")

            # Create output directory
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: MatIEC compile (ST → POUS.c + POUS.h)
            self.logger.info_print("Step 1: Compiling ST with MatIEC...")

            # Use a unified temporary directory, do not create temporary files in the benchmark directory
            import uuid
            compile_temp_dir = get_compile_temp_dir() / f"compile_{st_path.stem}_{uuid.uuid4().hex[:8]}"
            compile_temp_dir.mkdir(parents=True, exist_ok=True)

            compile_result = self.matiec_compiler.compile_st_to_c(
                st_file=str(st_path),
                output_dir=str(compile_temp_dir),
                preprocess=True
            )

            if not compile_result.success:
                result.error = f"MatIEC compilation failed: {compile_result.error}"
                result.compilation_log = compile_result.output or ""
                return result

            result.compilation_log = compile_result.output or ""
            pous_h_path = compile_temp_dir / "POUS.h"

            if not pous_h_path.exists():
                result.error = "POUS.h not found after compilation"
                return result

            self.logger.info_print("  ✓ MatIEC compilation successful")

            # Step 2: Extract interface information
            self.logger.info_print("Step 2: Extracting interface information...")
            pou_info = self.interface_extractor.extract(st_path, pous_h_path)
            result.pou_info = {
                "kind": pou_info.kind,
                "name": pou_info.name,
                "pou_name_upper": pou_info.pou_name_upper,
                "input_count": len(pou_info.inputs),
                "output_count": len(pou_info.outputs)
            }
            self.logger.info_print(f"  ✓ POU: {pou_info.name} ({len(pou_info.inputs)} inputs, {len(pou_info.outputs)} outputs)")

            # Step 3: Generate harness.c
            self.logger.info_print("Step 3: Generating harness.c...")
            harness_path = output_dir / "harness.c"
            if not self.harness_generator.generate_to_file(pou_info, harness_path):
                result.error = "Failed to generate harness.c"
                return result
            result.harness_path = harness_path
            self.logger.info_print(f"  ✓ Generated: {harness_path}")

            # Step 4: Generate input_schema_v2.json
            self.logger.info_print("Step 4: Generating input_schema_v2.json...")
            schema_path = output_dir / "input_schema_v2.json"
            if not self.schema_generator.generate_to_file(pou_info, schema_path):
                result.error = "Failed to generate schema"
                return result
            result.schema_path = schema_path
            self.logger.info_print(f"  ✓ Generated: {schema_path}")

            # Step 5: Generate input.txt
            self.logger.info_print("Step 5: Generating input.txt...")
            seed_path = output_dir / "input.txt"

            # Read schema for seed generation
            import json
            with open(schema_path) as f:
                schema = json.load(f)

            if not self.seed_generator.generate_to_file(schema, seed_path, num_seeds=20):
                result.error = "Failed to generate seeds"
                return result
            result.seed_path = seed_path
            self.logger.info_print(f"  ✓ Generated: {seed_path}")

            result.success = True
            self.logger.info_print("✓ Synthesis complete!")
            return result

        except Exception as e:
            result.error = f"Synthesis failed: {str(e)}"
            self.logger.error_print(result.error)
            return result


# CLI interface
def main():
    import argparse

    parser = argparse.ArgumentParser(description="PLCHaT Harness Generator")
    parser.add_argument("st_path", type=Path, help="ST source file path")
    parser.add_argument("output_dir", type=Path, help="Output directory")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--force", action="store_true", help="Force rebuild")

    args = parser.parse_args()

    pipeline = HarnessPipeline(debug=args.debug)
    result = pipeline.synthesize(args.st_path, args.output_dir, args.force)

    if result.success:
        print(f"✓ Success! Generated files in: {args.output_dir}")
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


if __name__ == "__main__":
    sys.exit(main())
