import requests
from langchain.prompts import ChatPromptTemplate
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

from config.config import (
    EMBEDDING_MODEL, 
    GENERATE_API_URL, 
    PDF_PATH, 
    VECTOR_DB_PATH, 
    SECONDARY_MODEL
)

from services.pdf_chunk_service import get_chunk  
from services.vector_db_service import feed_vector_db  
from services.query_enhancement import query_enhncement
from utils.logger import setup_logger

# Configuración del logger
logger = setup_logger("response_generator")

summary = ""

# Prompt principal para respuestas de física
PROMPT_TEMPLATE = """
Eres un asistente de física para estudiantes de 9º y 10º grado. 
Tu objetivo es proporcionar explicaciones claras, concisas y adecuadas para su edad.

**Contexto extraído del libro:**
{context}

**Pregunta del estudiante:**
{question}

**REGLAS CRÍTICAS DE RESPUESTA:**
1. Responde ÚNICAMENTE en español. Está prohibido responder en inglés.
2. Explica los conceptos de forma sencilla.
3. Si la pregunta requiere cálculos, muestra los pasos detalladamente.
4. Si el contexto del libro está en inglés, tradúcelo y explícalo en español.
5. Mantén un tono educativo y motivador.

Respuesta en español:
"""

def load_books():
    """Load and chunk the PDF (optional - call only when needed)."""
    chunked_pages = get_chunk(PDF_PATH)
    print("<<-- Pages chunked -->>")
    feed_vector_db(chunked_pages)
    print("<<-- Pages fed to vector db -->>")


def get_response(data: dict) -> dict:
    """Generate a response based on the user's prompt."""
    global summary

    try:
        prompt = data.get('prompt') or data.get('message') or ""
        if not prompt:
            return {"response": "No recibí ninguna pregunta válida."}

        # === Embeddings y Vector DB ===
        emb_fn = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url="http://ollama:11434"
        )

        collection = Chroma(
            collection_name="PhysicsBook",
            embedding_function=emb_fn,
            persist_directory=VECTOR_DB_PATH,
        )

        # Búsqueda inicial de contexto
        results = collection.similarity_search_with_score(prompt, k=4)
        context_texts = [doc.page_content for doc, _ in results]

        # Intentar mejorar la pregunta (con protección)
        try:
            enhanced = query_enhncement(prompt, context_texts)
            if enhanced and isinstance(enhanced, list):
                for q in enhanced:
                    if q and isinstance(q, str):
                        res = collection.similarity_search_with_score(q, k=2)
                        context_texts.extend([doc.page_content for doc, _ in res])
        except Exception as e:
            logger.warning(f"query_enhncement falló: {e}. Usando solo búsqueda inicial.")

        # Contexto final
        full_context = "\n\n---\n\n".join(list(set(context_texts)))  # eliminar duplicados

        # Prompt final
        final_prompt = PROMPT_TEMPLATE.format(
            context=full_context,
            question=prompt
        )

        # === Llamada a Ollama para generar respuesta ===
        payload = {
            "model": data.get('model', SECONDARY_MODEL),
            "prompt": final_prompt,
            "stream": False,
            "options": {"temperature": 0.7}
        }

        response = requests.post(
            GENERATE_API_URL,          # Debe ser "http://ollama:11434/api/generate"
            json=payload,
            timeout=90
        )
        response.raise_for_status()

        response_text = response.json().get('response', '').strip()

        # Actualizar resumen (opcional)
        summary += f"Q: {prompt[:150]}...\nR: {response_text[:300]}...\n"

        return {
            "response": response_text,
            "sources": [doc.metadata.get("id") for doc, _ in results]
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión con Ollama: {e}")
        return {"response": "No pude conectar con el modelo de lenguaje en este momento."}
    except Exception as e:
        logger.error(f"Error grave en get_response: {e}", exc_info=True)
        return {"response": "Lo siento, ocurrió un error interno en el motor de física. Inténtalo de nuevo."}


if __name__ == "__main__":
    data = {
        "prompt": "who is bose?",
        "model": "gemma2:2b"
    }
    response = get_response(data)
    print(response)