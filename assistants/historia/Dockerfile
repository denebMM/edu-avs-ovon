FROM python:3.10-slim

WORKDIR /app

# Instalar todas las dependencias necesarias para Backend y Wrapper
RUN pip install flask requests PyPDF2 jsonschema qdrant-client==1.9.1

# Copiamos todo el contenido (bot, wrapper y PDFs de historia)
COPY . .

# El comando se define en el docker-compose