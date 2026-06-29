# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    ".[connectors,channels,benchmarker]"

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

# Disable Python stdout/stderr block buffering — without this, INFO-level
# logs sit in a ~4KB stdout buffer and never reach `docker logs` until the
# buffer fills or the process exits.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 1000 metronix && \
    useradd --uid 1000 --gid metronix --shell /bin/bash --create-home metronix

COPY --from=builder /install /usr/local
COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .

# Pre-create writable subtrees the app needs at runtime. When `/app/data` is
# backed by a named volume the volume inherits ownership from this directory
# on first mount, so the non-root `metronix` user can write to it. Existing
# root-owned volumes still need a one-off `chown` on upgrade.
RUN mkdir -p /app/data/snapshots
RUN chown -R metronix:metronix /app
USER metronix

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

ENTRYPOINT ["uvicorn", "metronix.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
