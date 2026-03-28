FROM python:3.10-slim

WORKDIR /app

# Copiar archivos
COPY . /app

# Instalamos gunicorn dentro del contenedor (aquí no dará el error de "externally-managed")
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    ollama \
    pydantic \
    requests \
    jsonschema \
    flask \
    gunicorn

EXPOSE 5010

# Este CMD se usará si no se especifica otro en el docker-compose
CMD ["python", "api_wrapper.py"]