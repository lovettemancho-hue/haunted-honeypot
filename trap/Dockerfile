# ---------------------------------------------------------------------------
# Haunted Honeypot — Trap service
#
# Build:   docker build -t haunted-trap ./trap
# Run via: docker compose up trap
#
# Production image installs ONLY runtime dependencies (pip install .).
# For the test / CI environment, install dev extras instead:
#   pip install ".[dev]"
# DO NOT install dev extras in the production image.
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS base

# ---------------------------------------------------------------------------
# System setup
# ---------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (uid 1000) so the container never runs as root.
RUN groupadd --gid 1000 trapuser \
    && useradd --uid 1000 --gid trapuser --no-create-home --shell /bin/false trapuser

WORKDIR /app

# ---------------------------------------------------------------------------
# Install runtime dependencies only.
# Dev extras (hypothesis, pytest, pytest-asyncio) are intentionally excluded
# from the production image — use `pip install ".[dev]"` in CI/test only.
# ---------------------------------------------------------------------------
COPY pyproject.toml ./
# Copy the package source so setuptools can resolve the package metadata.
COPY trap/ ./trap/

RUN pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------
# Host key and log directories are mounted as named Docker volumes at runtime.
# /tmp is provided via tmpfs (read-only root filesystem override in compose).
ENV TRAP_PORT=2222 \
    TRAP_HOST_KEY_PATH=/data/keys/host_ed25519 \
    TRAP_LOG_DIR=/data/logs \
    TRAP_CREDENTIAL_FILE=/app/trap/credentials_default.txt

EXPOSE 2222

# Drop to non-root user for all subsequent operations.
USER trapuser

# ---------------------------------------------------------------------------
# The read-only root filesystem is enforced at runtime by docker-compose
# (read_only: true). The tmpfs mounts in docker-compose.yml provide writable
# /tmp and runtime scratch space without touching the real filesystem.
# ---------------------------------------------------------------------------
CMD ["python", "-m", "trap"]
