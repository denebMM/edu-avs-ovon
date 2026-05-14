FROM python:3.10-slim
WORKDIR /app
# Añadimos qdrant-client aquí
RUN pip install flask requests PyPDF2 jsonschema qdrant-client==1.9.1 
COPY . .