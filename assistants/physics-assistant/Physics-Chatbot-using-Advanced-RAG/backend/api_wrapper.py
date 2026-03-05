from flask import Flask, request, jsonify
import ollama
import os
from datetime import datetime
import uuid
from typing import Dict, Any, Optional
import jsonschema 
import json

from langchain_community.vectorstores import Chroma
#from langchain_community.embeddings import OllamaEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

app = Flask(__name__)

OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

# ── Configuración del agente ──
PHYSICS_SERVICE_URL = "http://assistant_physics:5002/receive"
PHYSICS_SPEAKER_URI = "tag:physics-assistant.local,2026:phys001"

# ── RAG config (mantengo tus valores) ──
CHUNK_SIZE = 512
CHUNK_OVERLAP_PERCENTAGE = 0.10
EMBEDDING_MODEL = "bge-large:335m"
PDF_PATH = "/app/Data/PhysicsBook.pdf"
VECTOR_DB_PATH = "/app/Data/vectorDB"
SECONDARY_MODEL = "llama3.2:3b"                 

# ── Inicialización del vectorstore (se ejecuta una vez al inicio) ──
def init_vectorstore() -> Optional[Chroma]:
    try:
        print("[PHYSICS v3] Cargando PDF y creando vectorstore...")
        loader = PyPDFLoader(PDF_PATH)
        documents = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=int(CHUNK_SIZE * CHUNK_OVERLAP_PERCENTAGE)
        )
        chunks = text_splitter.split_documents(documents)
        embeddings = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url="http://ollama:11434"
            )
        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=VECTOR_DB_PATH
        )
        print("[PHYSICS v3] Vectorstore creado correctamente")
        return vectorstore
    except Exception as e:
        print(f"[PHYSICS v3] Error al crear vectorstore: {e}. Continuando sin RAG.")
        return None

vectorstore = init_vectorstore()

# Schema OFP v1.1.0 oficial (copiado dehttps://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/1.1.0/conversation-envelope-schema.json)
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"
# Carga el schema oficial una sola vez al inicio del módulo
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"No se encontró el schema OFP en: {SCHEMA_PATH}. Descárgalo de GitHub.")
except json.JSONDecodeError:
    raise ValueError("El archivo de schema OFP está corrupto o mal formado.")

def validate_envelope(data):
    """Valida un envelope contra el schema oficial OVON/OFP v1.1.0"""
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
    except jsonschema.exceptions.ValidationError as validation_error:
        raise ValueError(f"Envelope OFP inválido: {str(validation_error)}")
    

def get_manifest():
    """Devuelve el manifest conforme al schema Assistant Manifest"""
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {
                            "url": PHYSICS_SERVICE_URL,
                            "speakerUri": PHYSICS_SPEAKER_URI
                        },
                        "role": "Especialista en Física",
                        "name": "PhysicsExplainer",
                        "description": "Explica conceptos de física, mecánica, termodinámica, electromagnetismo, etc. Usa contexto de libro cuando sea posible. Responde en español.",
                        "keywords": ["física", "mecánica", "movimiento", "gravedad", "energía", "leyes", "proyectiles", "cuántica"],
                        "languages": ["es", "en"],
                        "modalities": ["text"],
                        "capabilities": ["explanation", "problem-solving", "rag-enhanced"]
                    }
                }
            }]
        }
    }

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    """Endpoint dedicado para publicación del manifest (recomendado por OFP)"""
    return jsonify(get_manifest())

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json() or {}
        validate_envelope(data)  # Validación estricta contra schema oficial
        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        if not events:
            return jsonify({"error": "No events found"}), 400

        responses = []

        for event in events:
            event_type = event.get('eventType')

            if event_type == 'getManifests':
                manifest_response = get_manifest()
                if conversation_id:
                    manifest_response['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(manifest_response)

            elif event_type == 'utterance':
                try:
                    dialog_event = event['parameters']['dialogEvent']
                    tokens = dialog_event['features']['text']['tokens']
                    query = tokens[0]['value'] if tokens else ""
                    print(f"[PHYSICS v3] Pregunta recibida: {query}")

                    if not query:
                        reply = "No se recibió texto en la utterance."
                    else:
                        # ── RAG ── (mantengo todo lo tuyo)
                        context = ""
                        if vectorstore:
                            try:
                                docs = vectorstore.similarity_search(query, k=3)
                                context = "\n\n".join([doc.page_content for doc in docs])
                                print(f"[PHYSICS v3] Contexto RAG: {len(docs)} documentos recuperados")
                            except Exception as rag_err:
                                print(f"[PHYSICS v3] Error RAG: {rag_err}")
                                context = "(No se pudo recuperar contexto del libro)"

                        prompt = f"""Eres un experto en física. Usa el siguiente contexto del libro (si está disponible) para dar respuestas precisas y educativas en español.
Contexto:
{context}

Pregunta: {query}

Responde de forma clara, con ejemplos cotidianos cuando sea útil, y explica paso a paso si es un cálculo o derivación. No añadas saludos ni texto innecesario."""

                        try:
                            stream = ollama_client.chat(
                                model=SECONDARY_MODEL,
                                messages=[{'role': 'user', 'content': prompt}],
                                stream=True,
                                options={
                                        "temperature": 0.2,
                                        "timeout": 180,
                                        "num_gpu": -1,           # ← Fuerza GPU completa
                                        "num_thread": 4,         # ← Balance CPU
                                        "num_predict": 800       # ← Límite razonable
                                    }
                            )

                            reply = ""
                            for chunk in stream:
                                if 'message' in chunk and 'content' in chunk['message']:
                                    content = chunk['message']['content']
                                    reply += content
                                    print(content, end='', flush=True)

                            reply = reply.strip() or "No se pudo generar respuesta completa."
                            print(f"\n[PHYSICS v3] Respuesta final: {reply}")

                        except Exception as ollama_err:
                            print(f"[PHYSICS v3] Error Ollama: {ollama_err}")
                            reply = f"Error al generar respuesta con el modelo: {str(ollama_err)}"

                    # ── Respuesta utterance 100% compliant ──
                    now_iso = datetime.utcnow().isoformat() + "Z"
                    response_event = {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": PHYSICS_SPEAKER_URI,
                                "span": {
                                    "startTime": now_iso,
                                    "endTime": now_iso  # En producción mide tiempo real
                                },
                                "features": {
                                    "text": {
                                        "mimeType": "text/plain",  # Obligatorio
                                        "tokens": [{"value": reply}]
                                    }
                                }
                            }
                        }
                    }
                    responses.append(response_event)

                except (KeyError, IndexError) as parse_err:
                    print(f"[PHYSICS v3] Error parseando utterance: {parse_err}")
                    responses.append({
                        "eventType": "error",
                        "parameters": {"message": "Formato de utterance inválido"}
                    })

            elif event_type == 'request_delegation':
                # Respuesta compliant a request_delegation
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"reason": "Aceptado para física"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        # ── Envelope de respuesta 100% compliant ──
        response_payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {
                    "speakerUri": PHYSICS_SPEAKER_URI
                },
                "events": responses
            }
        }

        validate_envelope(response_payload)  # Valida lo que envías
        return jsonify(response_payload)

    except ValueError as ve:
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{
                    "eventType": "error",
                    "parameters": {"message": str(ve)}
                }]
            }
        }), 400
    except Exception as e:
        print(f"[PHYSICS v3] ERROR GENERAL: {str(e)}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{
                    "eventType": "error",
                    "parameters": {"message": str(e)}
                }]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)