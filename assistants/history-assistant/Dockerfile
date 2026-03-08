FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema para nltk + torch (si no las tenías)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# Instalar requirements (incluye nltk, torch, etc.)
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import nltk; \
    nltk.download('punkt', quiet=True); \
    nltk.download('punkt_tab', quiet=True)"

EXPOSE 5003

CMD ["python", "api_wrapper.py"] 