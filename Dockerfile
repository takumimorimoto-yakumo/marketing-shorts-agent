# syntax=docker/dockerfile:1

# ── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir hatchling

# Copy project metadata first for layer caching
COPY pyproject.toml ./
COPY src/ ./src/
COPY config/ ./config/

# Build wheel
RUN pip wheel --no-cache-dir --wheel-dir /dist .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install runtime dependencies from wheel
COPY --from=builder /dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

# Copy config templates
COPY config/templates/ /app/config/templates/

# Copy renderer-stub (needed when RENDERER_URL is not set)
COPY renderer_stub/ /app/renderer_stub/
RUN pip install --no-cache-dir fastapi uvicorn[standard]

# Switch to non-root
USER appuser

# Default: run renderer-stub on port 8080
# Override CMD to run the pipeline orchestrator or another entry point
EXPOSE 8080

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO \
    DRY_RUN=true

CMD ["uvicorn", "renderer_stub.app:app", "--host", "0.0.0.0", "--port", "8080"]
