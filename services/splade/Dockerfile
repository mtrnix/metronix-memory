FROM python:3.12-slim

# Slow or flaky networks: pip's default 15s read timeout with no retries
# fails the whole build on one stalled download.
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY main.py .

# HuggingFace token for authenticated downloads (higher rate limits).
# Pass via --build-arg HF_TOKEN. Falls back to anonymous if not set.
ARG HF_TOKEN
ENV HF_TOKEN=$HF_TOKEN

# Pre-download model at build time.
# Heredoc avoids shell backslash-continuation issues with Python compound statements.
RUN python3 <<'PYEOF'
from transformers import AutoModelForMaskedLM, AutoTokenizer
AutoTokenizer.from_pretrained('naver/splade-cocondenser-ensembledistil')
AutoModelForMaskedLM.from_pretrained('naver/splade-cocondenser-ensembledistil')
PYEOF

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=30s \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
