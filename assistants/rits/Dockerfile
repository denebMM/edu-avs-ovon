FROM python:3.10-slim

# Instala SWI-Prolog y git
RUN apt-get update && apt-get install -y \
    swi-prolog \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia dependencias primero (mejor cache de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código de la app
COPY rits_wrapper.py .

# ✅ COPIAR archivos Prolog (esto arregla tu error)
COPY rits_fractions.pl .


EXPOSE 5003

CMD ["python", "rits_wrapper.py"]
