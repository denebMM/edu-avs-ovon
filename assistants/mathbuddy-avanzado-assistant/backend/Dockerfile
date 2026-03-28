# Dockerfile (para usar en backend y wrapper)
FROM python:3.11-slim

WORKDIR /app

# Copia requirements primero (cache de Docker)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copia todo el código
COPY . .

EXPOSE 8080

# Por defecto usaremos uvicorn (para el backend)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]