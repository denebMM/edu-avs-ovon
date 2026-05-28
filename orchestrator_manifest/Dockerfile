FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir flask requests ollama

COPY . .

EXPOSE 5000
CMD ["python", "orchestrator_manifest.py"]