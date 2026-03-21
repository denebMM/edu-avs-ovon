FROM python:3.11-slim

# Directorio de trabajo (igual que tus otros asistentes)
WORKDIR /app

# Copia requirements primero → maximiza cache en rebuilds
COPY requirements.txt .

# Instala dependencias del proyecto original + las necesarias para OFP/Ollama
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        flask \
        ollama \
        jsonschema \
        langchain \
        langchain-community \
        # Agrega aquí otras dependencias específicas de MathBuddyBot si las necesita
        # Ejemplo: sympy (para cálculos simbólicos), numpy, etc.
        sympy \
        numpy

# Copia todo el código del proyecto (incluyendo api_wrapper.py)
COPY . .


CMD ["python", "api_wrapper.py"]