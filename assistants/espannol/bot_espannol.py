from flask import Flask, request, jsonify
import PyPDF2
import requests
import numpy as np
import time
from sentence_transformers import SentenceTransformer

app = Flask(__name__)

# 1. Carga del modelo semántico (Standard para RAG local)
print("Cargando modelo semántico para Lengua Española...")
modelo_emb = SentenceTransformer('all-MiniLM-L6-v2')

def cargar_pdf(nombre):
    texto = ""
    try:
        with open(nombre, "rb") as f:
            lector = PyPDF2.PdfReader(f)
            for pagina in lector.pages:
                contenido = pagina.extract_text()
                if contenido: texto += contenido + "\n"
    except Exception as e:
        print(f"Error al cargar PDF: {e}")
    return texto

# 2. Fragmentación inteligente (Chunking)
def crear_fragmentos(texto, tamano=500):
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    fragmentos, actual = [], ""
    for linea in lineas:
        if len(actual) + len(linea) < tamano:
            actual += " " + linea
        else:
            fragmentos.append(actual.strip())
            actual = linea
    if actual: fragmentos.append(actual.strip())
    return fragmentos

# 3. Búsqueda Vectorial (Similitud de Coseno)
def recuperar_contexto_semantico(pregunta, fragmentos, embeddings_db):
    emb_pregunta = modelo_emb.encode(pregunta)
    similitudes = np.dot(embeddings_db, emb_pregunta) / (
        np.linalg.norm(embeddings_db, axis=1) * np.linalg.norm(emb_pregunta) + 1e-10
    )
    top_indices = np.argsort(similitudes)[::-1][:5]
    return "\n".join([fragmentos[i] for i in top_indices])

def generar_con_ollama(pregunta, contexto):
    prompt = f"""Eres un profesor experto en Lengua Española y Literatura.
Usa el contexto proporcionado para responder de forma educativa.

Contexto:
{contexto}

Pregunta: {pregunta}"""
    try:
        response = requests.post(
            "http://ollama:11434/api/generate",
            json={"model": "llama3.1", "prompt": prompt, "stream": False},
            timeout=120
        )
        return response.json()["response"]
    except Exception as e:
        return f"Error de conexión con Ollama: {e}"

# PROCESAMIENTO INICIAL (Una sola vez)
print(" Procesando libro de Español...")
LIBRO_DATA = cargar_pdf("espannol.pdf")
FRAGMENTOS = crear_fragmentos(LIBRO_DATA)
EMBEDDINGS_DB = modelo_emb.encode(FRAGMENTOS)
print(f"Sistema listo: {len(FRAGMENTOS)} fragmentos analizados.")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    contexto = recuperar_contexto_semantico(pregunta, FRAGMENTOS, EMBEDDINGS_DB)
    respuesta = generar_con_ollama(pregunta, contexto)
    return jsonify({"respuesta": respuesta})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)