# Dockerfile for SWE-agent PLC baseline testing
# Contains MatIEC (ST->C compiler) and clang-18
#
# Usage:
#   docker build -t sweagent-plc:latest -f Dockerfile /path/to/matiec
#
# This Dockerfile requires the MatIEC source directory as build context

FROM python:3.11

# Install basic dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    wget \
    cmake \
    bison \
    flex \
    && rm -rf /var/lib/apt/lists/*

# Install clang-18
RUN apt-get update && apt-get install -y \
    clang-18 \
    libc++-18-dev \
    libc++abi-18-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy local MatIEC installation
# This requires building the context from the MatIEC source directory
COPY . /usr/local/matiec/

# Install MatIEC binaries and libraries
RUN ln -s /usr/local/matiec/iec2c /usr/local/bin/iec2c && \
    ln -s /usr/local/matiec/iec2iec /usr/local/bin/iec2iec && \
    mkdir -p /usr/local/lib/matiec && \
    cp -r /usr/local/matiec/lib/* /usr/local/lib/matiec/ && \
    ldconfig

# Set up environment
ENV PATH="/usr/local/bin:${PATH}"
ENV MATIEC_PATH="/usr/local/lib/matiec"
ENV MATIEC_RUNTIME="/usr/local/matiec/lib/C"

# Add plc_compile wrapper for compiling MatIEC-generated C code
RUN printf '#!/bin/bash\n\
# plc_compile - compile MatIEC-generated C code with correct runtime includes\n\
# Usage: plc_compile [clang-flags] <source.c> -o <output>\n\
set -e\n\
RUNTIME_DIR=/usr/local/matiec/lib/C\n\
exec clang-18 -fprofile-instr-generate -fcoverage-mapping \\\n\
  -I "${RUNTIME_DIR}" \\\n\
  -include iec_types_all.h \\\n\
  -include iec_std_lib.h \\\n\
  -include POUS.h \\\n\
  "$@"\n\
' > /usr/local/bin/plc_compile && chmod +x /usr/local/bin/plc_compile

# Verify installation
RUN iec2c --version || echo "iec2c installed at $(which iec2c)"
RUN clang-18 --version
RUN plc_compile --version 2>&1 || true

# Set working directory
WORKDIR /root

CMD ["/bin/bash"]
