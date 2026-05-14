from flask import Flask, request, jsonify
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import PyPDF2
import requests
import os

app = Flask(__name__)

# --- CONFIGURACIÓN ---
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://ollama:11434")
EMBED_MODEL = "mxbai-embed-large"
QDRANT_HOST = "qdrant" 
COLLECTION_NAME = "asistente_programacion"

client = QdrantClient(host=QDRANT_HOST, port=6333)

def cargar_pdfs(archivos):
    texto = ""
    for nombre in archivos:
        try:
            with open(nombre, "rb") as f:
                lector = PyPDF2.PdfReader(f)
                for pagina in lector.pages:
                    contenido = pagina.extract_text()
                    if contenido: texto += contenido + "\n"
        except Exception as e:
            print(f"Error al cargar PDF '{nombre}': {e}")
    return texto

def crear_fragmentos(texto, tamano=700):
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

def obtener_embedding(texto):
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings", 
            json={"model": EMBED_MODEL, "prompt": texto}, 
            timeout=60
        )
        return response.json()["embedding"] 
    except Exception:
        return []

# --- INICIALIZACIÓN PERSISTENTE ---
def inicializar_base_datos():
    try:
        colecciones = client.get_collections().collections
        if any(c.name == COLLECTION_NAME for c in colecciones):
            print(f"--- [INFO] Colección '{COLLECTION_NAME}' lista. ---")
            return

        print(f"--- [SISTEMA] Indexando manuales de Programación... ---")
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

        pdf_texto = cargar_pdfs(["programacion.pdf"])
        fragmentos = crear_fragmentos(pdf_texto)
        
        for i, texto in enumerate(fragmentos):
            vector = obtener_embedding(texto)
            if vector:
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[{"id": i, "vector": vector, "payload": {"texto": texto}}]
                )
        print(f"--- [ÉXITO] Manuales de C++ indexados en Qdrant. ---")
    except Exception as e:
        print(f"--- [ERROR] Falló inicialización: {e} ---")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    
    emb_pregunta = obtener_embedding(pregunta)
    # Búsqueda con umbral del 40% (0.40)
    search_result = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=emb_pregunta,
        limit=5,
        score_threshold=0.40
    )
    
    contexto = "\n".join([hit.payload["texto"] for hit in search_result])
    
    if not contexto.strip():
        return jsonify({"respuesta": "Lo siento, la información para responder a esta pregunta no se encuentra en mis manuales de programación."})

    prompt = f"""Eres un profesor experto en programación, especialmente en C++, basado estrictamente en documentos.
Usa ÚNICAMENTE el siguiente 'Contexto' para responder y proporciona ejemplos de código claros si el contexto los incluye o permite deducirlos.
Si la respuesta no se puede deducir del contexto, di exactamente: 'Lo siento, no tengo esa información en mi base de datos.'
No inventes información, no inventes funciones que no existan en el texto, ni utilices conocimientos externos.

Contexto:
{contexto}

Pregunta: {pregunta}
Respuesta técnica:"""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "llama3.1", "prompt": prompt, "stream": False},
            timeout=120
        )
        return jsonify({"respuesta": response.json()["response"]})
    except Exception as e:
        return jsonify({"respuesta": f"Error conectando con Ollama: {e}"})

if __name__ == '__main__':
    inicializar_base_datos()
    app.run(host='0.0.0.0', port=5000)