FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY main.py .

# Pre-download model at build time
RUN python -c "from transformers import AutoModelForMaskedLM, AutoTokenizer; \
    AutoTokenizer.from_pretrained('naver/splade-cocondenser-ensembledistil'); \
    AutoModelForMaskedLM.from_pretrained('naver/splade-cocondenser-ensembledistil')"

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=30s \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health').raise_for_status()"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
