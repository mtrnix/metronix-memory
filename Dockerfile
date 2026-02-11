# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install ".[connectors,channels]"

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN groupadd --gid 1000 metatron && \
    useradd --uid 1000 --gid metatron --shell /bin/bash metatron

COPY --from=builder /install /usr/local
COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .

RUN chown -R metatron:metatron /app
USER metatron

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

ENTRYPOINT ["uvicorn", "metatron.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
