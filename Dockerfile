# =============================================================================
# RevitNavisResearcher MCP Server — Dockerfile
# Multi-stage: small final image based on python:3.12-slim
# Runs as non-root user for security
# =============================================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy & install dependencies (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Final stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

WORKDIR /app

# Install runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* && \
    # Create non-root user
    groupadd -r revitnavis && \
    useradd -r -g revitnavis -d /app -s /sbin/nologin revitnavis

# Copy Python env from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application files
COPY mcp_server.py .
COPY mcp_config.yaml .
COPY .env .env
COPY revit_codebase.db .

# Ownership for non-root user
RUN chown -R revitnavis:revitnavis /app

# Switch to non-root user
USER revitnavis

# Port for SSE transport (optional, stdio is default)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost',8000)); s.close(); exit(0)" || exit 1

# Default: run in SSE mode for Docker (HTTP on port 8000)
# Override to "stdio" for CLI / kilo integration
ENV MCP_TRANSPORT=sse
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

ENTRYPOINT ["python", "mcp_server.py"]
