"""
PLCHaT ST Compiler Only - Independent Compilation Mode

Compile-only function: input file path, returns raw output and success status
Enhanced version: supports MatIEC standard library, input preprocessing, structured output

Note: This compiler does not generate binary or executable code
Only verify syntax at ST and C levels.
"""

import subprocess
import sys
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


# PLCHaT imports
from harness.compiler.utils import Logger, LEVEL
from harness.compiler.cache_manager import CacheManager



# ==================== Data Classes for Structured Output ====================

@dataclass
class CompilationError:
    """structured compilation error representation"""
    line: int
    column: int
    file: str
    message: str
    error_code: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "column": self.column,
            "file": self.file,
            "message": self.message,
            "error_code": self.error_code
        }


@dataclass
class CompilationWarning:
    """Structured compilation warning representation"""
    line: int
    file: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "file": self.file,
            "message": self.message
        }


@dataclass
class MatiecCompilationResult:
    """MatIEC compilation result, including structured output"""
    success: bool
    stage: str  # "preprocess", "st_to_c", "c_syntax_check", "complete"
    output: str = ""
    error: Optional[str] = None
    errors: List[Dict] = field(default_factory=list)
    warnings: List[Dict] = field(default_factory=list)
    generated_files: List[str] = field(default_factory=list)


# ==================== MatIEC Compiler Class ====================

class MatIECCompiler:
    """
MatIEC compiler, supports preprocessing and syntax checking

Function:
- ST code preprocessing (iec2iec equivalent)
- ST to C compilation (iec2c)
- C syntax validation (no binary generation)
- IEC 61131-3 standard library support
- Structured error parsing

Note: This compiler does not generate binary or executable code
Only verify syntax at ST and C levels
    """

    def __init__(
        self,
        matiec_path: Optional[str] = None,
        stdlib_path: Optional[str] = None,
        logger: Optional[Logger] = None,
        debug: bool = False
    ):
        """
Initialize MatIEC compiler

        Args:
matiec_path: MatIEC installation path (None for auto-detection)
stdlib_path: C standard library path (None for auto-detection)
logger: logger
debug: enable debug logging
        """
        self.debug = debug
        self.logger = logger or Logger("/tmp/plchat", "st_compiler_only.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.matiec_path = matiec_path
        self.stdlib_path = stdlib_path

        # Automatically detect path
        if not self.matiec_path:
            success, path = self._find_matiec_path()
            if success:
                self.matiec_path = path

        if not self.stdlib_path:
            self.stdlib_path = self._find_matiec_stdlib()

    # ==================== Path Discovery ====================

    def _find_matiec_path(self) -> Tuple[bool, str]:
        """Find the installation path of MatIEC compiler"""
        # try iec2c binary
        iec2c_bin = shutil.which("iec2c")
        if iec2c_bin:
            return True, str(Path(iec2c_bin).parent)

        # Try environment variable
        matiec_path = os.getenv('MATIEC_PATH')
        if matiec_path and os.path.exists(matiec_path):
            return True, matiec_path

        return False, "MatIEC compiler (iec2c) not found in PATH and MATIEC_PATH not configured"

    def _find_matiec_stdlib(self) -> Optional[str]:
        """
Find MatIEC standard library directory

Return the lib directory containing ieclib.txt (for iec2iec)
or C library directory (for iec2c C compilation)

        Prefer to use environment variables
        """
        stdlib_dir = os.getenv('MATIEC_C_LIB_DIR')
        if stdlib_dir and os.path.exists(stdlib_dir):
            return stdlib_dir

        if not self.matiec_path:
            return None

        # iec2iec needs lib directory and ieclib.txt
        # iec2c needs the lib/C directory and header files
        possible_paths = [
            os.path.join(self.matiec_path, "lib"),
            os.path.join(self.matiec_path, "lib", "C"),
            os.path.join(self.matiec_path, "..", "lib"),
            os.path.join(self.matiec_path, "..", "lib", "C"),
            "/usr/local/lib/matiec/lib",
            "/usr/local/lib/matiec/lib/C",
            "/usr/lib/matiec/lib",
            "/usr/lib/matiec/lib/C",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        return None

    def check_installation(self) -> Tuple[bool, str]:
        """
Check MatIEC installation status

        Returns:
            Tuple of (is_installed, message)
        """
        if not self.matiec_path:
            return False, "MatIEC compiler path not found"

        iec2c_bin = os.path.join(self.matiec_path, "iec2c")
        if not os.path.exists(iec2c_bin):
            return False, f"iec2c not found at {iec2c_bin}"

        stdlib_status = "with stdlib" if self.stdlib_path else "without stdlib"
        return True, f"MatIEC found at {self.matiec_path} ({stdlib_status})"

    # ==================== Input Preprocessing ====================

    def preprocess_st_code(
        self,
        st_code_path: str,
        output_path: Optional[str] = None
    ) -> Tuple[bool, str, str]:
        """
Preprocess ST code to be compatible with MatIEC

MatIEC compiler is sensitive to comment format:
- Remove all (* ... *) multiline comments
Remove all // ... single-line comments
- Normalize line endings (CRLF -> LF)
- Remove UTF-8 BOM (if present)

        Args:
st_code_path: Original ST file path
output_path: Preprocessing file path (automatically generated if not specified)

        Returns:
            Tuple of (success, output_path, error_message)
        """
        try:
            with open(st_code_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()

            # Normalize line endings
            content = content.replace('\r\n', '\n').replace('\r', '\n')

            # Remove multi-line comments (* ... *)
            content = re.sub(r'\(\*.*?\*\)', '', content, flags=re.DOTALL)

            # Remove single-line comments //
            content = re.sub(r'//.*', '', content)

            # Clean up extra whitespace
            lines = content.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped:
                    cleaned_lines.append(line)
                elif cleaned_lines and cleaned_lines[-1].strip() != '':
                    cleaned_lines.append('')

            cleaned_content = '\n'.join(cleaned_lines)

            # Generate output path - Use CacheManager to ensure never contaminating source directory
            if output_path is None:
                output_path = CacheManager.get_cleaned_st_path(Path(st_code_path))

            # Security check: ensure not in benchmark directory
            if CacheManager.is_benchmark_path(Path(output_path)):
                raise ValueError(f"Refusing to write cleaned file to benchmark directory: {output_path}")

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)

            if self.debug:
                self.logger.debug_print(f"Preprocessed: {st_code_path} -> {output_path}")

            return True, output_path, ""

        except Exception as e:
            return False, "", f"Preprocessing failed: {str(e)}"

    def preprocess_st_code_in_memory(self, st_code: str) -> str:
        """# Preprocess ST code from memory"""
        content = st_code.replace('\r\n', '\n').replace('\r', '\n')
        content = re.sub(r'\(\*.*?\*\)', '', content, flags=re.DOTALL)
        content = re.sub(r'//.*', '', content)
        return content

    # ==================== Error Parsing ====================

    def parse_errors(self, output: str, source_file: str) -> List[CompilationError]:
        """Parse MatIEC error output into structured format."""
        errors = []
        patterns = [
            (r'(\d+):(\d+)-(\d+):(\d+):\s*error:\s*(.+)', "full"),
            (r'([^:]+):(\d+):(\d+):\s*error:\s*(.+)', "file_line_col"),
            (r'error:\s*(.+)', "simple"),
        ]

        for line in output.split('\n'):
            line = line.strip()
            if 'error' not in line.lower():
                continue

            for pattern, pattern_type in patterns:
                match = re.search(pattern, line)
                if match:
                    if pattern_type == "full":
                        errors.append(CompilationError(
                            line=int(match.group(1)),
                            column=int(match.group(2)),
                            file=source_file,
                            message=match.group(5).strip(),
                            error_code="syntax_error"
                        ))
                    elif pattern_type == "file_line_col":
                        errors.append(CompilationError(
                            line=int(match.group(2)),
                            column=int(match.group(3)),
                            file=match.group(1),
                            message=match.group(4).strip(),
                            error_code="syntax_error"
                        ))
                    elif pattern_type == "simple":
                        errors.append(CompilationError(
                            line=0, column=0, file=source_file,
                            message=match.group(1).strip(),
                            error_code="general_error"
                        ))
                    break

        return errors

    def parse_warnings(self, output: str, source_file: str) -> List[CompilationWarning]:
        """Parse MatIEC warning output into structured format"""
        warnings = []
        pattern = r'(\d+):(\d+):\s*warning:\s*(.+)'

        for line in output.split('\n'):
            match = re.search(pattern, line)
            if match:
                warnings.append(CompilationWarning(
                    line=int(match.group(1)),
                    file=source_file,
                    message=match.group(3).strip()
                ))

        return warnings

    # ==================== Compilation Stages ====================

    def compile_st_to_c(
        self,
        st_file: str,
        output_dir: str,
        preprocess: bool = True
    ) -> MatiecCompilationResult:
        """
# Use MatIEC iec2c to compile ST code to C

        Args:
ST source file path
output_dir: Output directory for generated C files
preprocess: whether to preprocess ST code

        Returns:
MatiecCompilationResult contains compilation status
        """
        result = MatiecCompilationResult(success=False, stage="st_to_c")

        if not self.matiec_path:
            result.error = "MatIEC path not configured"
            return result

        # Convert to absolute path to avoid issues when changing working directory
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Preprocessing (if needed) - always write to output directory, do not pollute source directory
        if preprocess:
            # Calculate the path of the cleaned file in the output directory
            base_name = os.path.basename(st_file).replace('.st', '.cleaned.st')
            preprocess_output = os.path.join(output_dir, base_name)
            success, preprocess_path, error = self.preprocess_st_code(st_file, preprocess_output)
            if not success:
                result.stage = "preprocess"
                result.error = error
                return result
            st_file = preprocess_path
            result.generated_files.append(preprocess_path)

        # Run iec2c
        original_pwd = os.getcwd()
        try:
            os.chdir(self.matiec_path)

            cmd = ["./iec2c", "-T", output_dir, st_file]
            if self.debug:
                self.logger.debug_print(f"Running: {' '.join(cmd)}")

            compile_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            raw_output = compile_result.stdout + compile_result.stderr
            result.output = raw_output

            # Parse errors and warnings
            source_file = os.path.basename(st_file)
            errors = self.parse_errors(raw_output, source_file)
            warnings = self.parse_warnings(raw_output, source_file)

            result.errors = [e.to_dict() for e in errors]
            result.warnings = [w.to_dict() for w in warnings]

            if compile_result.returncode != 0:
                result.error = raw_output if raw_output else "ST to C compilation failed"
                return result

            # Track the generated C file
            for file in os.listdir(output_dir):
                if file.endswith('.c'):
                    result.generated_files.append(os.path.join(output_dir, file))

            result.success = True
            result.stage = "st_to_c_complete"

        except subprocess.TimeoutExpired:
            result.error = "Compilation timed out"
        except Exception as e:
            result.error = f"ST to C compilation error: {str(e)}"
        finally:
            os.chdir(original_pwd)

        return result

    def check_st_syntax(
        self,
        st_file: str,
        output_dir: Optional[str] = None,
        include_stdlib: bool = True
    ) -> MatiecCompilationResult:
        """
Use iec2iec to check ST syntax (ST to ST preprocessing + validation)

This pattern:
- Use iec2iec tool for ST syntax validation
- Link standard library (if include_stdlib=True)
- Do not generate C code
- Do not invoke gcc/clang for C syntax checking
- Remove all comments before checking (iec2iec does not support //)

        Args:
# ST source file path
Preprocessing output directory (optional)
include_stdlib: whether to include the standard library

        Returns:
# MatiecCompilationResult contains syntax check status
        """
        result = MatiecCompilationResult(success=False, stage="st_syntax_check")

        if not self.matiec_path:
            result.error = "MatIEC path not configured"
            return result

        # Create output directory
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="matiec_syntax_check_")
        os.makedirs(output_dir, exist_ok=True)

        # Key: Preprocessing to remove all comments
        # iec2iec does not support // single-line comments!
        preprocessed_output = os.path.join(output_dir, os.path.basename(st_file).replace('.st', '.cleaned.st'))
        preprocess_success, preprocessed_file, preprocess_error = self.preprocess_st_code(st_file, preprocessed_output)
        if not preprocess_success:
            result.stage = "preprocess"
            result.error = f"Preprocessing failed: {preprocess_error}"
            return result

        # Use preprocessed file for iec2iec
        st_file_to_check = preprocessed_file

        # Build iec2iec command
        iec2iec_bin = os.path.join(self.matiec_path, "iec2iec")
        if not os.path.exists(iec2iec_bin):
            result.error = f"iec2iec not found at {iec2iec_bin}"
            return result

        cmd = [iec2iec_bin, "-f", "-T", output_dir]

        # Add standard library include path (if available)
        if include_stdlib and self.stdlib_path:
            cmd.extend(["-I", self.stdlib_path])

        # Add preprocessed input file
        cmd.append(st_file_to_check)

        original_pwd = os.getcwd()
        try:
            os.chdir(self.matiec_path)

            if self.debug:
                self.logger.debug_print(f"Running iec2iec: {' '.join(cmd)}")

            compile_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            raw_output = compile_result.stdout + compile_result.stderr
            result.output = raw_output

            # Parse errors and warnings
            source_file = os.path.basename(st_file)
            errors = self.parse_errors(raw_output, source_file)
            warnings = self.parse_warnings(raw_output, source_file)

            result.errors = [e.to_dict() for e in errors]
            result.warnings = [w.to_dict() for w in warnings]

            if compile_result.returncode != 0:
                result.error = raw_output if raw_output else "ST syntax check failed"
                return result

            # Track the generated preprocessed ST file
            for file in os.listdir(output_dir):
                if file.endswith('.st'):
                    result.generated_files.append(os.path.join(output_dir, file))

            result.success = True
            result.stage = "st_syntax_check_complete"

        except subprocess.TimeoutExpired:
            result.error = "Syntax check timed out"
        except Exception as e:
            result.error = f"ST syntax check error: {str(e)}"
        finally:
            os.chdir(original_pwd)

        return result

    def compile_st_to_st(
        self,
        st_file: str,
        output_path: Optional[str] = None
    ) -> Tuple[bool, str, str]:
        """
Preprocess/standardize ST code (iec2iec equivalent)

Execute:
- Remove comments (* ... *) and // ...
Line ending normalization
- Whitespace cleanup

        Args:
st_file: input ST file path
output_path: Output ST file path (auto-generated if not specified)

        Returns:
            Tuple of (success, output_path, error_message)
        """
        return self.preprocess_st_code(st_file, output_path)

    def check_c_syntax(
        self,
        c_files: List[str],
        include_dirs: List[str]
    ) -> Tuple[bool, str]:
        """
Check C syntax without generating binary

Use the -fsyntax-only flag to only verify syntax.

        Args:
c_files: List of C source files to check
include_dirs: include directories

        Returns:
            Tuple of (success, output_or_error)
        """
        compilers = ["gcc", "clang", "gcc-18", "clang-18"]

        for compiler in compilers:
            if not shutil.which(compiler):
                continue

            cmd = [compiler, "-fsyntax-only", "-w"]
            for inc_dir in include_dirs:
                cmd.extend(["-I", inc_dir])
            cmd.extend(c_files)

            if self.debug:
                self.logger.debug_print(f"Checking C syntax with: {compiler}")
                self.logger.debug_print(f"Command: {' '.join(cmd)}")

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    return True, ""
                else:
                    error_msg = result.stderr or result.stdout
                    if not error_msg:
                        error_msg = f"Syntax check failed with code {result.returncode}"
                    return False, error_msg
            except subprocess.TimeoutExpired:
                return False, "Syntax check timed out"
            except Exception as e:
                continue

        return False, "C syntax check failed: no suitable compiler found"

    def compile_full(
        self,
        st_file: str,
        output_dir: Optional[str] = None,
        link_stdlib: bool = True
    ) -> MatiecCompilationResult:
        """
Compilation pipeline: ST → C → C syntax check

        Args:
st_file: ST source file path
output directory (auto-generated if not specified)
link_stdlib: Whether to link the standard library for C syntax checking

        Returns:
MatiecCompilationResult contains compilation status
        """
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="matiec_compile_")

        result = MatiecCompilationResult(success=False, stage="unknown")

        # Stage 1: ST to C
        st_result = self.compile_st_to_c(st_file, output_dir, preprocess=True)
        result.generated_files.extend(st_result.generated_files)
        result.errors = st_result.errors
        result.warnings = st_result.warnings

        if not st_result.success:
            result.stage = st_result.stage
            result.error = st_result.error
            result.output = st_result.output
            return result

        # Phase 2: C syntax check (if linking with standard library is requested)
        if link_stdlib:
            if not self.stdlib_path:
                result.stage = "c_syntax_check"
                result.error = "Standard library not found. Set MATIEC_C_LIB_DIR."
                return result

            # Collect C files
            generated_c_files = [
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if f.endswith('.c')
            ]

            lib_c_files = []
            if self.stdlib_path:
                for f in os.listdir(self.stdlib_path):
                    if f.endswith('.c') and ('iec_std_lib' in f or 'accessor' in f):
                        lib_c_files.append(os.path.join(self.stdlib_path, f))

            # Apply header file patch
            self._apply_header_patches(generated_c_files)

            # Only check C syntax (do not generate binary)
            source_files = generated_c_files + lib_c_files
            include_dirs = [self.stdlib_path, output_dir]

            syntax_ok, syntax_error = self.check_c_syntax(source_files, include_dirs)

            if not syntax_ok:
                result.stage = "c_syntax_check"
                result.error = syntax_error
                return result

            result.success = True
            result.stage = "syntax_check_complete"
            return result

        # Do not link standard library - ST to C is sufficient
        result.success = True
        result.stage = "st_to_c_complete"
        return result

    def _apply_header_patches(self, c_files: List[str]) -> None:
        """Apply necessary header file patches to the generated C file"""
        patch_headers = """#include "iec_types.h"
#include "iec_types_all.h"
#include "iec_std_lib.h"
#include "iec_std_FB.h"
#include "accessor.h"
"""

        for c_file in c_files:
            try:
                with open(c_file, 'r') as f:
                    content = f.read()

                # Skip patched files
                if '#include "iec_std_lib.h"' in content:
                    continue

                # Check the corresponding .h file
                base_name = os.path.splitext(os.path.basename(c_file))[0]
                c_dir = os.path.dirname(c_file)
                h_file = os.path.join(c_dir, f"{base_name}.h")

                # Build the final content with correct includes
                final_content = patch_headers + "\n"

                # If it exists, include the corresponding header file
                if os.path.exists(h_file):
                    final_content += f'#include "{base_name}.h"\n\n'

                final_content += content

                with open(c_file, 'w') as f:
                    f.write(final_content)

            except Exception as e:
                if self.debug:
                    self.logger.debug_print(f"Failed to patch {c_file}: {e}")


# ==================== Legacy Compiler Functions ====================

def matiec_compiler(
    file_dir: str,
    output_dir: Optional[str] = None,
    mode: str = "syntax_check",
    logger: Optional[Logger] = None,
    **kwargs
) -> Dict[str, Any]:
    """
MatIEC compiler wrapper function

    Args:
file_dir: Path to the ST file to be compiled
output_dir: intermediate file directory
mode: compilation mode
"syntax_check": Use iec2iec for ST syntax validation (default)
- "st_to_c": Converts ST to C using iec2c (without C compilation)
"full": ST → C → C syntax check (no binary generation)

    Returns:
# Dictionary containing compilation results
    """
    compiler = MatIECCompiler(logger=logger)

    if mode == "syntax_check":
        # Default mode: Use iec2iec for ST syntax verification
        # Do not generate C code, do not call gcc/clang
        result = compiler.check_st_syntax(file_dir, output_dir, include_stdlib=True)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "stage": result.stage,
            "errors": result.errors,
            "warnings": result.warnings,
            "generated_files": result.generated_files
        }

    elif mode == "st_to_c":
        # Only ST to C conversion
        preprocess = kwargs.get("preprocess", True)
        result = compiler.compile_st_to_c(file_dir, output_dir or tempfile.mkdtemp(), preprocess)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "stage": result.stage,
            "errors": result.errors,
            "warnings": result.warnings,
            "generated_files": result.generated_files
        }

    elif mode == "full":
        # Full compilation and C syntax check (no binary generation)
        link_stdlib = kwargs.get("link_stdlib", True)
        result = compiler.compile_full(file_dir, output_dir, link_stdlib)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "stage": result.stage,
            "errors": result.errors,
            "warnings": result.warnings,
            "generated_files": result.generated_files
        }

    else:
        return {
            "success": False,
            "output": "",
            "error": f"Unknown mode: {mode}. Valid modes: syntax_check, st_to_c, full",
            "stage": "unknown",
            "errors": [],
            "warnings": [],
            "generated_files": []
        }


def check_st_file(
    file_path: str,
    mode: str = "syntax_check",
    logger: Optional[Logger] = None
) -> bool:
    """
Use matiec_compiler to check a single ST file

    Args:
file_path: The ST file path to check
mode: compilation mode (syntax_check, st_to_c, full)
logger: logger

    Returns:
        True if check passed, False otherwise
    """
    if not os.path.exists(file_path):
        logger.error_print(f"File not found: {file_path}") if logger else print(f"❌ File not found: {file_path}")
        return False

    result = matiec_compiler(file_path, mode=mode, logger=logger)

    if result["success"]:
        if logger:
            logger.success_print(f"✅ Syntax check PASSED: {file_path}")
            logger.debug_print(f"   Stage: {result['stage']}")
        else:
            print(f"✅ Syntax check PASSED: {file_path}")
            print(f"   Stage: {result['stage']}")
        return True
    else:
        if logger:
            logger.error_print(f"❌ Syntax check FAILED: {file_path}")
            logger.debug_print(f"   Stage: {result['stage']}")
            logger.debug_print(f"   Error: {result['error']}")
        else:
            print(f"❌ Syntax check FAILED: {file_path}")
            print(f"   Stage: {result['stage']}")
            print(f"   Error: {result['error']}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="PLCHaT ST Compiler Only - Check ST code syntax"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to the ST file to check"
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["syntax_check", "st_to_c", "full"],
        default="syntax_check",
        help="Compilation mode (default: syntax_check)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        help="Output directory for generated files"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    if not args.file:
        parser.error("the following arguments are required: file")

    logger = Logger("/tmp/plchat", "st_compiler_only.log",
                   level=LEVEL.DEBUG if args.verbose else LEVEL.INFO)

    # Set output directory
    output_dir = args.output_dir
    if output_dir is None and args.mode in ["st_to_c", "full"]:
        output_dir = tempfile.mkdtemp(prefix="matiec_output_")

    result = matiec_compiler(
        args.file,
        output_dir=output_dir,
        mode=args.mode,
        logger=logger
    )

    # Output result
    print("\n" + "=" * 60)
    print("Compilation Result")
    print("=" * 60)
    print(f"Status: {'✅ SUCCESS' if result['success'] else '❌ FAILED'}")
    print(f"Stage: {result['stage']}")
    print(f"Mode: {args.mode}")

    if result['success']:
        if result['generated_files']:
            print(f"\nGenerated files ({len(result['generated_files'])}):")
            for f in result['generated_files']:
                print(f"  - {f}")
    else:
        print(f"\nError: {result['error']}")
        if result['errors']:
            print(f"\nErrors ({len(result['errors'])}):")
            for err in result['errors'][:5]:
                print(f"  - Line {err.get('line', '?')}: {err.get('message', 'Unknown error')}")
        if result['warnings']:
            print(f"\nWarnings ({len(result['warnings'])}):")
            for warn in result['warnings'][:5]:
                print(f"  - Line {warn.get('line', '?')}: {warn.get('message', 'Unknown warning')}")

    print("=" * 60)
