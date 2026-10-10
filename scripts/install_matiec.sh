#!/usr/bin/env bash
#
# PLCHaT - MatIEC Installation Script
#
# This script installs the MatIEC IEC 61131-3 compiler required by PLCHaT.
#
# Usage:
#   ./scripts/install_matiec.sh [install_dir]
#
# Arguments:
#   install_dir: Installation directory (default: /usr/local/lib/matiec)
#
# Environment Variables:
#   MATIEC_INSTALL_DIR: Override installation directory
#

set -e

# Default installation directory
DEFAULT_INSTALL_DIR="/usr/local/lib/matiec"
INSTALL_DIR="${MATIEC_INSTALL_DIR:-${1:-$DEFAULT_INSTALL_DIR}}"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root (for default installation)
if [ "$INSTALL_DIR" = "$DEFAULT_INSTALL_DIR" ] && [ "$EUID" -ne 0 ]; then
    log_warn "Installing to $DEFAULT_INSTALL_DIR requires root privileges."
    log_warn "Please run with sudo, or specify a user directory:"
    log_warn "  sudo $0"
    log_warn "  or"
    log_warn "  $0 ~/matiec"
    exit 1
fi

log_info "Installing MatIEC to: $INSTALL_DIR"

# Check dependencies
log_info "Checking dependencies..."

MISSING_DEPS=()

for cmd in git make gcc flex bison; do
    if ! command -v $cmd &> /dev/null; then
        MISSING_DEPS+=($cmd)
    fi
done

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    log_error "Missing dependencies: ${MISSING_DEPS[*]}"
    log_error "Please install them first:"
    log_error "  sudo apt-get install build-essential flex bison"
    exit 1
fi

log_info "Dependencies OK."

# Clone MatIEC repository
TEMP_DIR=$(mktemp -d)
log_info "Cloning MatIEC repository..."

git clone https://github.com/beremiz/matiec "$TEMP_DIR/matiec" > /dev/null 2>&1

if [ ! -d "$TEMP_DIR/matiec" ]; then
    log_error "Failed to clone MatIEC repository"
    rm -rf "$TEMP_DIR"
    exit 1
fi

cd "$TEMP_DIR/matiec"

# Configure and build
log_info "Configuring MatIEC..."
./configure --prefix="$INSTALL_DIR" > /dev/null 2>&1

log_info "Building MatIEC (this may take a few minutes)..."
make > /dev/null 2>&1

if [ $? -ne 0 ]; then
    log_error "Build failed"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Install
log_info "Installing to $INSTALL_DIR..."
make install > /dev/null 2>&1

# Create symlink for iec2c in /usr/local/bin (if installing to default location)
if [ "$INSTALL_DIR" = "$DEFAULT_INSTALL_DIR" ]; then
    log_info "Creating symlink for iec2c in /usr/local/bin..."
    ln -sf "$INSTALL_DIR/bin/iec2c" /usr/local/bin/iec2c
fi

# Cleanup
rm -rf "$TEMP_DIR"

# Verify installation
log_info "Verifying installation..."

if [ -f "$INSTALL_DIR/bin/iec2c" ]; then
    log_info "✓ iec2c found at: $INSTALL_DIR/bin/iec2c"
    VERSION=$("$INSTALL_DIR/bin/iec2c" --version 2>&1 | head -1)
    log_info "  Version: $VERSION"
else
    log_error "iec2c not found at expected location"
    exit 1
fi

# Print installation summary
echo ""
log_info "MatIEC installed successfully!"
echo ""
echo "Installation location: $INSTALL_DIR"
echo ""
echo "To use PLCHaT with MatIEC, set the environment variable:"
echo "  export MATIEC_PATH=$INSTALL_DIR"
echo ""
echo "Or add to your ~/.bashrc or ~/.zshrc:"
echo "  echo 'export MATIEC_PATH=$INSTALL_DIR' >> ~/.bashrc"
