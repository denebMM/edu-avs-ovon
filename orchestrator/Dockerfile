FROM python:3.10-slim

WORKDIR /app

# 1. Copiamos solo el requirements
COPY requirements.txt .

# 2. Instalamos con reintentos y timeouts más largos para evitar cortes
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=1000 -r requirements.txt && \
    pip install --no-cache-dir flask requests ollama

# 3. El resto de los archivos
COPY . .

EXPOSE 5000

CMD ["python", "orchestrator.py"]