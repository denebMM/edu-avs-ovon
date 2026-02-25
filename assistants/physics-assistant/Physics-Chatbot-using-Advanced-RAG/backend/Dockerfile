FROM python:3.10-slim

WORKDIR /app

# Copia requirements primero → mejor cache
COPY requirements.txt .

# Instala dependencias del repo original + extras para OVON/RabbitMQ
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir jsonschema flask  # flask si usas endpoint HTTP fallback

# Copia todo el código (incluyendo api_wrapper.py con handler OVON)
COPY . .

# Si el RAG necesita persistencia (vectorDB, mongo data, etc.)
# VOLUME ["/app/Data/vectorDB"]   # opcional, mejor manejarlo en compose

CMD ["python", "api_wrapper.py"]