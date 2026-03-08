FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia lingonaut-python + wrapper
COPY . .

# Instala dependencias (ajusta si usas environment.yml)
RUN pip install --no-cache-dir \
    flask \
    ollama \
    jsonschema \
    # Dependencias de lingonaut-python (agrega las que necesites)
    openai-whisper  
# Si usas conda → puedes copiar environment.yml y activarlo, pero slim es más ligero

EXPOSE 5010

CMD ["python", "api_wrapper.py"]