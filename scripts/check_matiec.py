#!/usr/bin/env python3
"""
MatIEC Installation Check Script

Checks if MatIEC (IEC 61131-3 compiler) is properly installed and configured.

Usage:
    python scripts/check_matiec.py

Exit codes:
    0: All checks passed
    1: Some checks failed
"""

import os
import sys
import shutil
from pathlib import Path
import subprocess

def print_header(text):
    """Print section header."""
    print(f"\n{text}")
    print("=" * len(text))


def print_ok(msg):
    """Print OK message."""
    print(f"  ✓ {msg}")


def print_fail(msg):
    """Print FAIL message."""
    print(f"  ✗ {msg}")


def print_warn(msg):
    """Print WARN message."""
    print(f"  ⚠ {msg}")


def check_matiec_installation():
    """Check MatIEC installation."""
    issues = []

    print_header("MatIEC Installation Check")

    # Check 1: MATIEC_PATH environment variable
    matiec_path = os.getenv("MATIEC_PATH")
    if matiec_path:
        print_ok(f"MATIEC_PATH set: {matiec_path}")
    else:
        print_warn("MATIEC_PATH not set")
        issues.append("Set MATIEC_PATH environment variable")

    # Check 2: iec2c in PATH
    iec2c_in_path = shutil.which("iec2c")
    if iec2c_in_path:
        print_ok(f"iec2c in PATH: {iec2c_in_path}")
    else:
        print_fail("iec2c not found in PATH")
        issues.append("Install MatIEC or add to PATH")

    # Check 3: Locate iec2c binary
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
        print_ok(f"iec2c binary found: {iec2c_found}")

        # Try to get version
        try:
            result = subprocess.run(
                [str(iec2c_found), "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.split("\n")[0]
                print_ok(f"iec2c version: {version}")
        except Exception:
            print_warn("Could not determine iec2c version")
    else:
        print_fail("iec2c binary not found")
        issues.append("iec2c binary not found")

    # Check 4: Standard library files
    stdlib_locations = []

    if matiec_path:
        stdlib_locations.append(Path(matiec_path) / "lib" / "ieclib.txt")
        stdlib_locations.append(Path(matiec_path) / "lib" / "C")

    stdlib_locations.extend([
        Path("/usr/local/lib/matiec/lib/ieclib.txt"),
        Path("/usr/local/lib/matiec/lib/C"),
    ])

    stdlib_found = False
    for loc in stdlib_locations:
        if loc.exists():
            stdlib_found = True
            print_ok(f"Standard library found: {loc.parent}")
            break

    if not stdlib_found:
        print_warn("Standard library not found")
        issues.append("Standard library files not found")

    return issues


def print_installation_guide():
    """Print installation instructions."""
    print_header("Installation Instructions")

    print("""
To install MatIEC, choose one of the following methods:

Method 1: Automated Installation (Recommended)
  Run the provided installation script:

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

  Add to your ~/.bashrc or ~/.zshrc for persistence:

    echo 'export MATIEC_PATH=/usr/local/lib/matiec' >> ~/.bashrc

  Verify installation:

    python main.py -v
    python scripts/check_matiec.py
""")


def main():
    """Main entry point."""
    import subprocess

    print("PLCHaT - MatIEC Installation Check")
    print("=" * 40)

    issues = check_matiec_installation()

    print_header("Summary")

    if not issues:
        print("✓ All checks passed! MatIEC is properly installed.")
        return 0
    else:
        print("✗ Some checks failed:")
        for issue in issues:
            print(f"  - {issue}")

        print_installation_guide()
        return 1


if __name__ == "__main__":
    sys.exit(main())
