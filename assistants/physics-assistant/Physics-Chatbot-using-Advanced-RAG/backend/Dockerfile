FROM python:3.10-slim

WORKDIR /app

# Instalamos dependencias de sistema necesarias para PDF y Base de Datos
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Instalamos TODO: lo de RAG (app.py) y lo de OFP (api_wrapper.py)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir flask flask-cors jsonschema requests

COPY . .

# Quitamos el CMD de aquí para decidirlo en el docker-compose