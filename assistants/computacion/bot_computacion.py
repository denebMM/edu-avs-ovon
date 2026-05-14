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
COLLECTION_NAME = "asistente_computacion"

client = QdrantClient(host=QDRANT_HOST, port=6333)

def cargar_pdf(nombre):
    texto = ""
    try:
        with open(nombre, "rb") as f:
            lector = PyPDF2.PdfReader(f)
            for pagina in lector.pages:
                contenido = pagina.extract_text()
                if contenido: texto += contenido + "\n"
    except Exception as e:
        print(f"Error al cargar el PDF: {e}")
    return texto

def crear_fragmentos(texto, tamano=600):
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

def inicializar_base_datos():
    """Crea la colección e indexa el PDF solo si es la primera vez."""
    try:
        colecciones = client.get_collections().collections
        if any(c.name == COLLECTION_NAME for c in colecciones):
            print(f"--- [INFO] Colección '{COLLECTION_NAME}' ya existe. ---")
            return

        print(f"--- [SISTEMA] Indexando libro de Computación... ---")
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

        pdf_texto = cargar_pdf("informatica.pdf")
        fragmentos = crear_fragmentos(pdf_texto)
        
        for i, texto in enumerate(fragmentos):
            vector = obtener_embedding(texto)
            if vector:
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[{"id": i, "vector": vector, "payload": {"texto": texto}}]
                )
        print(f"--- [ÉXITO] Computación indexada correctamente en Qdrant. ---")
    except Exception as e:
        print(f"--- [ERROR] Falló inicialización: {e} ---")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    datos = request.json
    pregunta = datos.get("pregunta", "")
    
    emb_pregunta = obtener_embedding(pregunta)
    # Búsqueda con umbral de similitud del 40% (0.40)
    search_result = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=emb_pregunta,
        limit=5,
        score_threshold=0.40
    )
    
    contexto = "\n".join([hit.payload["texto"] for hit in search_result])
    
    if not contexto.strip():
        return jsonify({"respuesta": "Lo siento, la información para responder a esta pregunta no se encuentra en el documento proporcionado."})

    prompt = f"""Eres un asistente experto en Informática basado estrictamente en documentos. 
Usa ÚNICAMENTE el siguiente 'Contexto del libro' para responder a la pregunta. 
Si la respuesta no se puede deducir del contexto, di exactamente: 'Lo siento, no tengo esa información en mi base de datos.'
No inventes información ni utilices conocimientos externos.

Contexto del libro:
{contexto}

Pregunta: {pregunta}
Respuesta:"""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "llama3.1", "prompt": prompt, "stream": False},
            timeout=120
        )
        return jsonify({"respuesta": response.json()["response"]})
    except Exception as e:
        return jsonify({"respuesta": f"Error en IA: {str(e)}"})

if __name__ == '__main__':
    inicializar_base_datos()
    app.run(host='0.0.0.0', port=5000)