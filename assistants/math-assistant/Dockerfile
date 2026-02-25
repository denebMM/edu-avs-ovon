FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir flask requests ollama  jsonschema transformers
COPY . .

CMD ["python", "api_wrapper.py"]