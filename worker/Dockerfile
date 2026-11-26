
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --default-timeout=300 --retries=10 --no-cache-dir -r requirements.txt

COPY fila.py .
COPY main.py .
COPY rastreamento.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
