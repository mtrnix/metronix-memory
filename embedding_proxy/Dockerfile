FROM python:3.12-slim

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
