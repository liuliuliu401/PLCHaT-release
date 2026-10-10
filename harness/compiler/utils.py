"""
PLCHaT Harness Utilities

Common utility functions for the harness execution environment.
"""

import os
import sys
from enum import Enum
from datetime import datetime
from typing import Optional

# Rich console import for enhanced console output
try:
    from rich.console import Console
    console = Console()
    RICH_AVAILABLE = True
except ImportError:
    console = None
    RICH_AVAILABLE = False


class LEVEL(Enum):
    """Logging levels for the Harness."""
    DEBUG = 1
    TRACE = 2
    VERBOSE = 3
    INFO = 4
    WARNING = 5
    ERROR = 6
    SUCCESS = 7


class Logger:
    """Logger for harness execution with file and console output."""

    def __init__(
        self,
        folder: str,
        file_name: str,
        level: LEVEL = LEVEL.INFO,
        console_output: bool = True,
        timestamp_format: str = "%Y-%m-%d %H:%M:%S"
    ):
        """
        Initialize Logger.

        Args:
            folder: Directory to store log files
            file_name: Name of the log file
            level: Minimum logging level to record
            console_output: Whether to also print messages to console
            timestamp_format: Format string for timestamps
        """
        self.folder = folder
        self.file_name = file_name
        self.file_path = os.path.join(folder, file_name)
        self.level = level
        self.console_output = console_output
        self.timestamp_format = timestamp_format

        # Ensure folder exists
        try:
            os.makedirs(folder, exist_ok=True)
            # Test write permissions
            test_file = os.path.join(folder, ".logger_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except (OSError, PermissionError) as e:
            print(f"ERROR: Cannot create or write to log directory '{folder}': {e}")
            sys.exit(1)

    def _should_log(self, level: LEVEL) -> bool:
        """Check if message should be logged based on current level."""
        return level.value >= self.level.value

    def _format_message(self, message: str, level: LEVEL) -> str:
        """Format message with timestamp and level."""
        timestamp = datetime.now().strftime(self.timestamp_format)
        return f"[{timestamp}] [{level.name:>7}] {message}"

    def _write_to_file(self, formatted_message: str) -> bool:
        """Write message to log file with error handling."""
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(f"{formatted_message}\n")
                f.flush()
            return True
        except (OSError, IOError) as e:
            print(f"ERROR: Failed to write to log file '{self.file_path}': {e}")
            return False

    def _write_to_console(self, message: str, style: str) -> None:
        """Write message to console using Rich styling."""
        if RICH_AVAILABLE and console:
            console.print(f"[{style}]{message}[/{style}]")
        else:
            print(message)

    def log(self, message: str, level: LEVEL = LEVEL.INFO) -> bool:
        """
        Main logging method.

        Args:
            message: Message to log
            level: Logging level for this message

        Returns:
            bool: True if successfully logged, False otherwise
        """
        if not self._should_log(level):
            return True

        formatted_message = self._format_message(message, level)
        success = self._write_to_file(formatted_message)

        return success

    # ST Compiler style print methods
    def debug_print(self, message: str, style: str = "dim") -> bool:
        """Print debug message with Rich styling."""
        if not self._should_log(LEVEL.DEBUG):
            return True
        success = self.log(message, LEVEL.DEBUG)
        if self.console_output:
            self._write_to_console(message, style)
        return success

    def info_print(self, message: str, style: str = "bold") -> bool:
        """Print info message with Rich styling."""
        if not self._should_log(LEVEL.INFO):
            return True
        success = self.log(message, LEVEL.INFO)
        if self.console_output:
            self._write_to_console(message, style)
        return success

    def success_print(self, message: str, style: str = "bold green") -> bool:
        """Print success message with Rich styling."""
        if not self._should_log(LEVEL.SUCCESS):
            return True
        success = self.log(message, LEVEL.SUCCESS)
        if self.console_output:
            self._write_to_console(message, style)
        return success

    def error_print(self, message: str, style: str = "bold red") -> bool:
        """Print error message with Rich styling."""
        if not self._should_log(LEVEL.ERROR):
            return True
        success = self.log(message, LEVEL.ERROR)
        if self.console_output:
            self._write_to_console(message, style)
        return success

    def warning_print(self, message: str, style: str = "bold yellow") -> bool:
        """Print warning message with Rich styling."""
        if not self._should_log(LEVEL.WARNING):
            return True
        success = self.log(message, LEVEL.WARNING)
        if self.console_output:
            self._write_to_console(message, style)
        return success

    # Convenience methods
    def debug(self, message: str) -> bool:
        """Log debug message."""
        return self.log(message, LEVEL.DEBUG)

    def trace(self, message: str) -> bool:
        """Log trace message."""
        return self.log(message, LEVEL.TRACE)

    def verbose(self, message: str) -> bool:
        """Log verbose message."""
        return self.log(message, LEVEL.VERBOSE)

    def info(self, message: str) -> bool:
        """Log info message."""
        return self.log(message, LEVEL.INFO)

    def warning(self, message: str) -> bool:
        """Log warning message."""
        return self.log(message, LEVEL.WARNING)

    def error(self, message: str) -> bool:
        """Log error message."""
        return self.log(message, LEVEL.ERROR)

    def success(self, message: str) -> bool:
        """Log success message."""
        return self.log(message, LEVEL.SUCCESS)

    def set_level(self, level: LEVEL) -> None:
        """Change the logging level."""
        self.level = level
        self.info(f"Logging level changed to {level.name}")

    def get_log_file_path(self) -> str:
        """Get the full path to the log file."""
        return self.file_path

    def get_log_size(self) -> int:
        """Get the size of the log file in bytes."""
        try:
            return os.path.getsize(self.file_path)
        except OSError:
            return 0


import re

def patch_pous_setvar_time_to_dint(output_dir: str) -> bool:
    """Post-process POUS.c: work around MatIEC __SET_VAR macro expansion
       bug where direct TIME_TO_DINT(...) inside __SET_VAR is silently
       discarded due to a macro interaction. Stores TIME_TO_DINT result
       in a temp DINT variable before assigning through __SET_VAR.

       Returns True if a patch was applied.
    """
    for root, _, files in os.walk(output_dir):
        for fname in files:
            if not (fname.endswith('.c') and 'POUS' in fname):
                continue
            path = os.path.join(root, fname)
            with open(path, 'r') as f:
                content = f.read()

            pat = re.compile(
                r'__SET_VAR\(data__->,TEMP_REMAINSEC,,TIME_TO_DINT\(\s*'
                r'\(BOOL\)__BOOL_LITERAL\(TRUE\),\s*'
                r'NULL,\s*'
                r'\(TIME\)__time_sub\(__GET_VAR\(data__->STAT_DELAYTIME,\), __GET_VAR\(data__->T_FSM\.ET,\)\)\)\);'
            )
            new = (
                '{ DINT _tdint = TIME_TO_DINT('
                '(BOOL)__BOOL_LITERAL(TRUE),'
                'NULL,'
                '(TIME)__time_sub(__GET_VAR(data__->STAT_DELAYTIME,), __GET_VAR(data__->T_FSM.ET,)));'
                '__SET_VAR(data__->,TEMP_REMAINSEC,,_tdint); }'
            )
            new_content, n = pat.subn(new, content)
            if n > 0:
                with open(path, 'w') as f:
                    f.write(new_content)
                return True
    return False
