from flask import Flask, request, jsonify
import ollama
import os
from datetime import datetime, timedelta
import uuid
from typing import Dict, Any, Optional
import jsonschema 
import json
import logging

from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Logging para depuración en Docker
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Configuración del agente ──
OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

PHYSICS_SERVICE_URL = "http://assistant_physics:5002/receive"
PHYSICS_SPEAKER_URI = "tag:physics-assistant.local,2026:phys001"

# ── RAG config ──
CHUNK_SIZE = 512
CHUNK_OVERLAP_PERCENTAGE = 0.10
EMBEDDING_MODEL = "bge-large:335m"
PDF_PATH = "/app/Data/PhysicsBook.pdf"
VECTOR_DB_PATH = "/app/Data/vectorDB"
SECONDARY_MODEL = "llama3.2:3b"                 

# ── Inicialización del vectorstore ──
def init_vectorstore() -> Optional[Chroma]:
    try:
        logger.info("[PHYSICS] Cargando PDF y creando vectorstore...")
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
        logger.info("[PHYSICS] Vectorstore creado correctamente")
        return vectorstore
    except Exception as e:
        logger.error(f"[PHYSICS] Error al crear vectorstore: {e}. Continuando sin RAG.")
        return None

vectorstore = init_vectorstore()

# ── Schema OFP ──
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"No se encontró el schema OFP en: {SCHEMA_PATH}")
except json.JSONDecodeError:
    raise ValueError("El archivo de schema OFP está corrupto o mal formado.")

def validate_envelope(data, context=""):
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
        logger.info(f"Envelope válido ({context})")
    except jsonschema.exceptions.ValidationError as e:
        logger.error(f"ERROR VALIDACIÓN OFP ({context}): {e.message}")
        logger.error(f"Path: {list(e.path)}")
        logger.error(f"Valor que falla: {e.instance}")
        if hasattr(e, 'schema_path'):
            logger.error(f"Schema path: {list(e.schema_path)}")
        logger.error(f"Envelope que falló:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
        raise ValueError(f"Invalid OFP envelope: {str(e)}")

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": PHYSICS_SERVICE_URL, "speakerUri": PHYSICS_SPEAKER_URI},
                        "role": "Especialista en Física escolar",
                        "name": "PhysicsExplainer",
                        "description": "Explica conceptos de física (grados 9-10). Usa RAG de libro NCTB. Soporta delegación.",
                        "keywords": ["física", "movimiento", "fuerzas", "gravedad", "energía", "electricidad", "óptica"],
                        "languages": ["es", "en"],
                        "modalities": ["text"],
                        "capabilities": ["explanation", "problem-solving", "rag-enhanced", "delegation-accept"]
                    }
                }
            }]
        }
    }

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify(get_manifest())

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json() or {}
        validate_envelope(data, context="entrada recibida")

        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        if not events:
            return jsonify({
                "openFloor": {
                    "schema": {"version": "1.1.0"},
                    "events": [{"eventType": "error", "parameters": {"message": "No events found"}}]
                }
            }), 400

        responses = []
        query_to_process = None

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
                    query_to_process = tokens[0]['value'] if tokens else ""
                    logger.info(f"[PHYSICS] Query recibida: {query_to_process}")
                except Exception as ex:
                    logger.error(f"Error extrayendo utterance: {ex}")
                    responses.append({"eventType": "error", "parameters": {"message": "Error al extraer texto del utterance"}})
                    continue

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {
                        "reason": "Aceptado por Physics para subtarea de física escolar",
                        "accepted": True
                    }
                })
                logger.info("[PHYSICS] Delegación aceptada")

            elif event_type == 'transfer_control':
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control aceptado por Physics"}
                })

            elif event_type == 'yieldFloor':
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso conversacional recibido por Physics"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        # ── Procesar la query SOLO si existe ──
        if query_to_process:
            logger.info(f"[PHYSICS] Procesando pregunta: {query_to_process}")

            context = ""
            if vectorstore:
                try:
                    docs = vectorstore.similarity_search(query_to_process, k=3)
                    context = "\n\n".join([doc.page_content for doc in docs])
                    logger.info(f"[PHYSICS] Contexto RAG: {len(docs)} docs recuperados")
                except Exception as rag_err:
                    logger.error(f"[PHYSICS] Error RAG: {rag_err}")
                    context = "(No se pudo recuperar contexto del libro)"

            prompt = f"""Eres un experto en física escolar (grados 9-10). 
Usa el siguiente contexto del libro cuando sea relevante.
Si la pregunta NO es sobre física (movimiento, fuerzas, energía, gravedad, electricidad, óptica, termodinámica, etc.), responde SOLO:
"Esta consulta no es de mi área (física escolar). Puedo ayudarte con conceptos de física, cálculos básicos y explicaciones."

Contexto:
{context}

Pregunta: {query_to_process}

Responde en español, de forma clara, educativa y paso a paso si hay cálculos. Usa ejemplos cotidianos cuando sea útil. No añadas saludos ni texto innecesario."""

            try:
                stream = ollama_client.chat(
                    model=SECONDARY_MODEL,
                    messages=[{'role': 'user', 'content': prompt}],
                    stream=True,
                    options={
                        "temperature": 0.2,
                        "timeout": 180,
                        "num_gpu": -1,
                        "num_thread": 4,
                        "num_predict": 800
                    }
                )

                reply = ""
                for chunk in stream:
                    if 'message' in chunk and 'content' in chunk['message']:
                        reply += chunk['message']['content']

                reply = reply.strip() or "No se pudo generar respuesta completa."

            except Exception as ollama_err:
                logger.error(f"[PHYSICS] Error Ollama: {ollama_err}")
                reply = f"Error al generar respuesta: {str(ollama_err)}"

            # Span con diferencia de tiempo
            now = datetime.utcnow()
            start_iso = now.isoformat() + "Z"
            end_iso = (now + timedelta(seconds=2)).isoformat() + "Z"

            response_event = {
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": PHYSICS_SPEAKER_URI,
                        "span": {
                            "startTime": start_iso,
                            "endTime": end_iso
                        },
                        "features": {
                            "text": {
                                "mimeType": "text/plain",
                                "tokens": [{"value": reply}]
                            }
                        }
                    }
                }
            }
            responses.append(response_event)

            # yieldFloor SOLO si hubo respuesta útil (y SIN parámetros)
            if reply and "no es de mi área" not in reply.lower() and "error" not in reply.lower():
                responses.append({
                    "eventType": "yieldFloor",
                    "parameters": {}   # ← CORREGIDO: vacío, como exige el schema
                })

        # Envelope final
        response_payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": PHYSICS_SPEAKER_URI},
                "events": responses
            }
        }

        validate_envelope(response_payload, context="respuesta enviada")
        return jsonify(response_payload)

    except ValueError as ve:
        logger.error(f"Error de validación: {ve}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(ve)}}]
            }
        }), 400
    except Exception as e:
        logger.exception(f"[PHYSICS] ERROR GENERAL: {str(e)}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(e)}}]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)