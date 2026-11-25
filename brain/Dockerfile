# ---------------------------------------------------------------------------
# Haunted Honeypot — Brain service (API + analyzer)
#
# Build context is the repository root (see deploy/docker-compose.yml):
#   docker build -f brain/Dockerfile -t haunted-brain .
#
# brain/pyproject.toml maps the `brain` package to its own directory
# (package-dir brain = "."), so the whole brain/ directory is copied to
# /build/brain and installed from there. The result is a regular install in
# site-packages, so `import brain` and `uvicorn brain.main:create_app --factory`
# both work from any working directory.
# Only runtime dependencies are installed (no dev extras).
# ---------------------------------------------------------------------------

FROM python:3.12-slim

# Non-root user (uid 1000); the container never runs as root.
RUN groupadd --gid 1000 brainuser \
    && useradd --uid 1000 --gid brainuser --no-create-home --shell /bin/false brainuser

WORKDIR /build
COPY brain/ ./brain/
RUN pip install --no-cache-dir ./brain \
    && rm -rf /build

# Database directory; the named volume inherits this ownership.
# The log directory is mounted read-only from the trap_logs volume.
ENV BRAIN_LOG_DIR=/data/logs \
    BRAIN_DATABASE_PATH=/data/db/brain.db \
    BRAIN_HOST=0.0.0.0 \
    BRAIN_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /data/db /data/logs && chown -R brainuser:brainuser /data

WORKDIR /app
USER brainuser

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn brain.main:create_app --factory --host \"$BRAIN_HOST\" --port \"$BRAIN_PORT\""]
