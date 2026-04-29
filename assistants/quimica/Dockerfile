FROM python:3.10-slim

WORKDIR /app

# Instalar todas las dependencias necesarias para ambos scripts
RUN pip install flask PyPDF2 requests jsonschema

# Copiamos todo el contenido de la carpeta (bot, wrapper y PDFs)
COPY . .

