FROM python:3.12-slim

# Slow or flaky networks: pip's default 15s read timeout with no retries
# fails the whole build on one stalled download.
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY main.py .

# Expose порт
EXPOSE 8001

# Запуск
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
