# Bio-MCP FastQC Server
FROM quay.io/biocontainers/fastqc:0.12.1--hdfd78af_0

# Install MultiQC and Python dependencies
USER root
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install MultiQC and MCP dependencies
RUN pip install --no-cache-dir \
    multiqc==1.19 \
    mcp>=1.1.0 \
    pydantic>=2.0.0 \
    pydantic-settings>=2.0.0 \
    httpx>=0.25.0 \
    uvloop>=0.19.0

# Create bio-mcp user
RUN useradd -m -s /bin/bash bio-mcp && \
    chown -R bio-mcp:bio-mcp /opt/venv

# Switch to bio-mcp user
USER bio-mcp
WORKDIR /home/bio-mcp

# Copy source code
COPY --chown=bio-mcp:bio-mcp src/ ./src/
COPY --chown=bio-mcp:bio-mcp pyproject.toml ./

# Install the package
RUN pip install -e .

# Verify tools are available
RUN fastqc --version && multiqc --version

# Environment variables
ENV PYTHONPATH="/home/bio-mcp"
ENV BIO_MCP_TEMP_DIR="/tmp"
ENV BIO_MCP_MAX_FILE_SIZE="10000000000"
ENV BIO_MCP_TIMEOUT="1800"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import src.server; print('FastQC MCP server is healthy')"

# Default command
CMD ["python", "-m", "src.server"]