FROM python:3.10-slim

WORKDIR /app

# Instalar todas las dependencias necesarias para ambos scripts (Backend y Wrapper)
# Se añade qdrant-client para permitir la persistencia de datos
RUN pip install flask requests PyPDF2 jsonschema qdrant-client==1.9.1

# Copiamos todo el contenido de la carpeta (bot, wrapper y PDFs)
COPY . .

# No ponemos CMD aquí porque lo definimos en el docker-compose
# para que cada contenedor sepa qué archivo ejecutar.