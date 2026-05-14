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
COLLECTION_NAME = "asistente_algebra"

# Conexión local a Qdrant
client = QdrantClient(host=QDRANT_HOST, port=6333)

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

def obtener_embedding_ollama(texto):
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings", 
            json={"model": EMBED_MODEL, "prompt": texto}, 
            timeout=60
        )
        return response.json()["embedding"]
    except Exception:
        return []

# --- FUNCIÓN DE AUTO-INDEXACIÓN PERSISTENTE ---
def inicializar_base_datos():
    try:
        # Verificar si la colección ya existe para no repetir el trabajo
        colecciones = client.get_collections().collections
        if any(c.name == COLLECTION_NAME for c in colecciones):
            print(f"--- [INFO] Colección '{COLLECTION_NAME}' detectada. Saltando indexación. ---")
            return

        print(f"--- [SISTEMA] Indexando '{COLLECTION_NAME}' por primera vez... ---")
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

        pdf_texto = cargar_pdf(["algebra.pdf"])
        fragmentos = crear_fragmentos(pdf_texto)
        
        print(f"--- [PROCESO] Generando embeddings para {len(fragmentos)} fragmentos... ---")
        for i, texto in enumerate(fragmentos):
            vector = obtener_embedding_ollama(texto)
            if vector:
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[{
                        "id": i, 
                        "vector": vector, 
                        "payload": {"texto": texto}
                    }]
                )
        print("--- [ÉXITO] Indexación completada y persistida en disco. ---")
    except Exception as e:
        print(f"--- [ERROR] Falló la inicialización: {e} ---")

# --- RUTA DE PREGUNTAS ---
@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    
    # 1. Recuperación en Qdrant
    emb_pregunta = obtener_embedding_ollama(pregunta)
    search_result = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=emb_pregunta,
        limit=5
    )
    
    # Extraer el texto de los resultados
    contexto = "\n".join([hit.payload["texto"] for hit in search_result])
    
    # [CORRECCIÓN CLAVE]: Validar si el contexto llegó vacío
    if not contexto.strip():
        return jsonify({"respuesta": "Lo siento, la información para responder a esta pregunta no se encuentra en el documento proporcionado."})

    # [CORRECCIÓN CLAVE]: Prompt altamente restrictivo para tesis
    prompt = f"""Eres un profesor experto en álgebra basado estrictamente en documentos. 
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
        response.raise_for_status()
        respuesta_final = response.json().get("response", "Error al procesar la respuesta.")
    except Exception as e:
        respuesta_final = f"Error conectando con el motor de IA: {str(e)}"
    
    return jsonify({"respuesta": respuesta_final})

if __name__ == '__main__':
    # Asegurar que los datos estén listos antes de aceptar peticiones
    inicializar_base_datos()
    app.run(host='0.0.0.0', port=5000)