from flask import Flask, request, jsonify
import PyPDF2
import requests
import numpy as np
from sentence_transformers import SentenceTransformer

app = Flask(__name__)

# 1. Cargamos el modelo de Embeddings (se hace una sola vez al iniciar)
print("_Cargando modelo de lenguaje (Embeddings)...")
modelo_semantico = SentenceTransformer('all-MiniLM-L6-v2')

def cargar_pdf(nombres):
    texto = ""
    for nombre in nombres:
        try:
            with open(nombre, "rb") as f:
                lector = PyPDF2.PdfReader(f)
                for pagina in lector.pages:
                    contenido = pagina.extract_text()
                    if contenido: texto += contenido + "\n"
        except Exception as e:
            print(f"Error cargando {nombre}: {e}")
    return texto

# 2. Nueva función para crear fragmentos (Chunks) con sentido
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

# 3. Nueva función de búsqueda semántica (Matemática vectorial)
def recuperar_contexto_semantico(pregunta, fragmentos, embeddings_db):
    # Convertimos la pregunta en un vector
    emb_pregunta = modelo_semantico.encode(pregunta)
    
    # Calculamos la similitud de coseno entre la pregunta y todos los fragmentos
    similitudes = np.dot(embeddings_db, emb_pregunta) / (
        np.linalg.norm(embeddings_db, axis=1) * np.linalg.norm(emb_pregunta) + 1e-10
    )
    
    # Tomamos los 5 fragmentos más parecidos
    top_indices = np.argsort(similitudes)[::-1][:5]
    return "\n".join([fragmentos[i] for i in top_indices])

# --- PROCESAMIENTO INICIAL ---
print(" Cargando libros de álgebra...")
TEXTO_COMPLETO = cargar_pdf(["algebra.pdf", "algebra1.pdf"])
FRAGMENTOS = crear_fragmentos(TEXTO_COMPLETO)

print(f"Generando base de datos vectorial para {len(FRAGMENTOS)} fragmentos...")
EMBEDDINGS_DB = modelo_semantico.encode(FRAGMENTOS)
print("__Sistema listo.")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    
    # Búsqueda inteligente en lugar de búsqueda por palabras
    contexto = recuperar_contexto_semantico(pregunta, FRAGMENTOS, EMBEDDINGS_DB)
    
    prompt = f"""Eres un profesor experto en álgebra.
Usa exclusivamente el siguiente contexto para responder.

Contexto:
{contexto}

Pregunta: {pregunta}
Respuesta:"""
    
    try:
        response = requests.post(
            "http://ollama:11434/api/generate",
            json={
                "model": "llama3.1",
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        respuesta_ia = response.json().get("response", "Error procesando respuesta")
    except Exception as e:
        respuesta_ia = f"Error conectando con Ollama: {str(e)}"

    return jsonify({"respuesta": respuesta_ia})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)