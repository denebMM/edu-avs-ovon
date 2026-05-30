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

# =====================================================================
# NUEVO PROMPT MAESTRO DE FÍSICA (BLINDADO CONTRA RAG VACÍO)
# =====================================================================
PROMPT_TEMPLATE = """
Eres un asistente experto en Física para estudiantes de secundaria (9º y 10º grado).
Tu único propósito es responder a la pregunta de física del estudiante.

REGLAS CRÍTICAS DE RESPUESTA:
1. FOCO EN LA PREGUNTA: Tu tarea es responder a la pregunta de física planteada. IGNORA aportes de otros agentes o texto que no sea de tu materia.
2. USO DEL CONTEXTO (OPCIONAL): Revisa el 'Contexto extraído del libro'. Si te sirve, úsalo y tradúcelo al español si es necesario.
3. PREVALENCIA DEL CONOCIMIENTO: Si el contexto está vacío, no tiene sentido o no menciona el tema de la pregunta, IGNÓRALO COMPLETAMENTE.
4. RESPUESTA OBLIGATORIA: Nunca te niegues a responder ni digas "El libro no lo menciona". Usa tus conocimientos internos de física para responder de forma sencilla y muestra los cálculos detalladamente si es necesario.
5. IDIOMA Y TONO: Responde ÚNICAMENTE en español, manteniendo un tono educativo y motivador.

Contexto extraído del libro:
{context}

Pregunta del estudiante:
{question}

Respuesta de Física en español:
"""
# =====================================================================

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
        context_texts = []
        results = []
        
        try:
            try:
                # Intento para versiones recientes de langchain_ollama / langchain_community
                emb_fn = OllamaEmbeddings(
                    model=EMBEDDING_MODEL,
                    base_url="http://ollama:11434",
                    client_kwargs={"timeout": 450.0} 
                )
            except TypeError:
                # Respaldo de seguridad si rechaza client_kwargs
                emb_fn = OllamaEmbeddings(
                    model=EMBEDDING_MODEL,
                    base_url="http://ollama:11434",
                    timeout=450.0
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

        except Exception as e_chroma:
            # ¡EL BLINDAJE FINAL!
            # Si Chroma o los embeddings fallan, atrapamos el error y dejamos el contexto vacío.
            logger.error(f"Fallo en Vector DB (Ignorando RAG): {e_chroma}")
            context_texts = []

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
            GENERATE_API_URL,          
            json=payload,
            timeout=450                
        )
        response.raise_for_status()

        response_text = response.json().get('response', '').strip()

        # Actualizar resumen (opcional)
        summary += f"Q: {prompt[:150]}...\nR: {response_text[:300]}...\n"

        return {
            "response": response_text,
            "sources": [doc.metadata.get("id") for doc, _ in results] if results else []
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