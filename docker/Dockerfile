# PLCHaT Artifact Docker Image
# Minimal reproducible environment for PLCHaT

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    clang-18 \
    llvm-18 \
    python3.8 \
    python3-pip \
    git \
    cmake \
    perl \
    libgmp-dev \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.8 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Install MatIEC (IEC 61131-3 compiler)
RUN git clone https://github.com/beremiz/matiec /tmp/matiec && \
    cd /tmp/matiec && ./configure && make && make install && \
    cd / && rm -rf /tmp/matiec

# Set up work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy core project files (exclude benchmark, experiments for now)
COPY harness/ ./harness/
COPY tools/ ./tools/
COPY core/ ./core/
COPY scripts/ ./scripts/
COPY config.py .
COPY constants.py .

# Create necessary directories
RUN mkdir -p /app/results \
    /app/logs \
    /app/temp

# Set environment variables
ENV PYTHONPATH=/app:$PYTHONPATH
ENV CC=clang-18
ENV CXX=clang++-18

# Health check
RUN echo "#!/bin/bash" > /app/health_check.sh && \
    echo "which iec2c && echo 'MatIEC: OK' || echo 'MatIEC: FAILED'" >> /app/health_check.sh && \
    echo "python -c 'import pydantic, z3, yaml' && echo 'Python deps: OK' || echo 'Python deps: FAILED'" >> /app/health_check.sh && \
    echo "clang-18 --version && echo 'Clang-18: OK' || echo 'Clang-18: FAILED'" >> /app/health_check.sh && \
    chmod +x /app/health_check.sh

# Default command - show help
CMD ["python", "-c", "from harness.compiler import executor; print('PLCHaT Harness loaded successfully')"]
