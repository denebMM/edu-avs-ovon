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
COLLECTION_NAME = "asistente_espanol"

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
            timeout=400
        )
        return response.json()["embedding"] 
    except Exception:
        return []

def inicializar_base_datos():
    """Indexa los dos PDFs solo si la colección no existe."""
    try:
        colecciones = client.get_collections().collections
        if any(c.name == COLLECTION_NAME for c in colecciones):
            print(f"--- [INFO] Colección '{COLLECTION_NAME}' detectada. ---")
            return

        print(f"--- [SISTEMA] Indexando libros de Español (RAE y Gramática)... ---")
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

        pdf_texto = cargar_pdfs(["gramatica_espannol.pdf", "RAEgramatica.pdf"])
        fragmentos = crear_fragmentos(pdf_texto)
        
        for i, texto in enumerate(fragmentos):
            vector = obtener_embedding(texto)
            if vector:
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[{"id": i, "vector": vector, "payload": {"texto": texto}}]
                )
        print(f"--- [ÉXITO] {len(fragmentos)} fragmentos de Español guardados. ---")
    except Exception as e:
        print(f"--- [ERROR] Falló inicialización: {e} ---")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    
    emb_pregunta = obtener_embedding(pregunta)
    search_result = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=emb_pregunta,
        limit=5,
        score_threshold=0.40
    )
    
    contexto = "\n".join([hit.payload["texto"] for hit in search_result])
    
    # --- CORRECCIÓN: ELIMINAMOS EL BLOQUEO ---
    if not contexto.strip():
        print("--- [AVISO] Contexto vacío. La IA usará su conocimiento general. ---")
        contexto = "No hay información en los libros para esto."
    # ----------------------------------------

    prompt = f"""Eres un profesor experto y con autoridad absoluta en LENGUA ESPAÑOLA Y LITERATURA.
Tu único propósito es responder a la pregunta del usuario.

REGLAS ESTRICTAS DE RESPUESTA:
1. ANÁLISIS DE DOMINIO Y APORTES: Lee la 'Pregunta'. Es posible que incluya texto etiquetado como "[Aporte de...]". IGNORA esos aportes. Analiza ÚNICAMENTE lo que se te pide resolver a ti. ¿La tarea trata de Lengua Española, gramática, ORTOGRAFÍA (como el uso de tildes o acentos), sintaxis o literatura? 
   - SI ES SÍ: Continúa al paso 2.
   - SI ES NO: Responde exactamente "no está relacionado" y termina.

2. USO DEL CONTEXTO (OPCIONAL): Revisa el 'Contexto' proporcionado por los libros. 
   - Si el contexto te sirve para responder, úsalo.
   - Si el contexto está vacío, no tiene sentido o habla de otra materia, IGNÓRALO COMPLETAMENTE.

3. RESPUESTA EXPERTA (OBLIGATORIA): Si llegaste a este paso, TIENES QUE RESPONDER la pregunta usando tu propio conocimiento interno sobre Español. Bajo ninguna circunstancia puedes negarte a responder si la pregunta es sobre tu materia. Nunca digas "El contexto no menciona...", simplemente responde de forma directa y clara.

Contexto proporcionado por la base de datos:
{contexto}

Pregunta del usuario: {pregunta}
Tu Respuesta Experta en Español:"""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "gemma2:2b", "prompt": prompt, "stream": False},
            timeout=400
        )
        return jsonify({"respuesta": response.json()["response"]})
    except Exception as e:
        return jsonify({"respuesta": f"Error de conexion con Ollama: {e}"})
        
if __name__ == '__main__':
    inicializar_base_datos()
    app.run(host='0.0.0.0', port=5000)