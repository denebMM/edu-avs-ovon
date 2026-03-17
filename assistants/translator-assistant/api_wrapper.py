from flask import Flask, request, jsonify
import ollama
import json
from datetime import datetime, timedelta
import uuid
import jsonschema
import os
import logging

# Logging para depuración en Docker
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ────────────────────────────────────────────────
# CONFIGURACIÓN
# ────────────────────────────────────────────────
OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

TRANSLATOR_SERVICE_URL = "http://assistant_translator:5010/receive"
TRANSLATOR_SPEAKER_URI = "tag:translator.local,2026:trans001"

SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    raise RuntimeError(f"Error cargando schema OFP: {e}")

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
                        "service": {"url": TRANSLATOR_SERVICE_URL, "speakerUri": TRANSLATOR_SPEAKER_URI},
                        "role": "Traductor y asistente lingüístico multilingüe",
                        "name": "LingoNaut Translator",
                        "description": "Traduce texto, corrige gramática, explica expresiones y enseña idiomas. Soporta delegación.",
                        "keywords": ["traducción", "idiomas", "translate", "gramática", "aprendizaje idiomas"],
                        "languages": ["es", "en", "fr", "de", "ja", "zh", "ru", "it", "pt"],
                        "modalities": ["text"],
                        "capabilities": ["translation", "grammar-correction", "language-detection", "natural-phrasing", "delegation-accept"]
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

        responses = []
        query_to_process = None

        for event in events:
            event_type = event.get('eventType')

            if event_type == 'getManifests':
                resp = get_manifest()
                if conversation_id:
                    resp['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(resp)

            elif event_type == 'utterance':
                try:
                    dialog = event['parameters']['dialogEvent']
                    tokens = dialog['features']['text']['tokens']
                    query_to_process = tokens[0]['value'] if tokens else ""
                    logger.info(f"[TRANSLATOR] Query recibida: {query_to_process}")
                except Exception as ex:
                    logger.error(f"Error extrayendo utterance: {ex}")
                    responses.append({"eventType": "error", "parameters": {"message": "Error al extraer texto del utterance"}})
                    continue

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {
                        "reason": "Aceptado por Translator para subtarea de traducción/idiomas",
                        "accepted": True
                    }
                })
                logger.info("[TRANSLATOR] Delegación aceptada")

            elif event_type == 'transfer_control':
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control aceptado por Translator"}
                })

            elif event_type == 'yieldFloor':
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso conversacional recibido por Translator"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        # Procesar query si existe (AHORA AL MISMO NIVEL DE INDENTACIÓN QUE EL FOR)
        if query_to_process:
            # Prompt limpio y sin variables no definidas
            prompt = f"""Eres un traductor preciso y literal. Tu única tarea es traducir el texto exactamente al idioma solicitado.

            Reglas estrictas:
            - Traduce SOLO el texto proporcionado.
            - Mantén el significado, estructura, pasos y detalles originales al 100 %.
            - NO expliques, NO reformules, NO añadas comentarios educativos ni "pasos".
            - NO detectes idioma ni hagas nada más que traducir.
            - Si no es una instrucción clara de traducción, responde SOLO: "Solo traduzco texto."

            Texto completo a traducir:
            {query_to_process}"""

            try:
                stream = ollama_client.chat(
                    model='llama3.1:8b',
                    messages=[{'role': 'user', 'content': prompt}],
                    stream=True,
                    options={
                        "temperature": 0.0,
                        "num_predict": 1024,
                        "num_gpu": -1,
                        "num_thread": 0
                    }
                )

                reply = ""
                for chunk in stream:
                    if 'message' in chunk and 'content' in chunk['message']:
                        reply += chunk['message']['content']

                reply = reply.strip() or "No pude procesar la traducción."

            except Exception as ollama_err:
                logger.error(f"[TRANSLATOR] Error Ollama: {ollama_err}")
                reply = "Error al procesar la consulta lingüística."

            # Generación de eventos de respuesta
            now = datetime.utcnow()
            start_iso = now.isoformat() + "Z"
            end_iso = (now + timedelta(seconds=2)).isoformat() + "Z"

            response_event = {
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": TRANSLATOR_SPEAKER_URI,
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

            # yieldFloor si respuesta válida
            if reply and "no es de mi área" not in reply.lower() and "error" not in reply.lower():
                responses.append({
                    "eventType": "yieldFloor",
                    "parameters": {}
                })

        # Respuesta final (SIEMPRE dentro del try principal)
        response_payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": TRANSLATOR_SPEAKER_URI},
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
        logger.exception(f"[TRANSLATOR] ERROR GENERAL: {str(e)}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(e)}}]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=False)