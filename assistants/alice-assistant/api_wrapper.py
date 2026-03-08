from flask import Flask, request, jsonify
import uuid
from datetime import datetime, timedelta
import jsonschema
import json
import os
import glob
from pyaiml21 import Kernel  # intérprete AIML
import logging

# Logging para depuración en Docker
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Configuración OFP ────────────────────────────────────────
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"
ALICE_SERVICE_URL = "http://assistant_alice:5005/receive"
ALICE_SPEAKER_URI = "tag:alice.local,2026:alice001"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
    logger.info("[ALICE] Schema OFP cargado correctamente")
except Exception as e:
    logger.critical(f"[ALICE] No se pudo cargar schema OFP: {e}")
    OFP_SCHEMA = {}

def validate_envelope(data, context=""):
    if not OFP_SCHEMA:
        logger.warning(f"[ALICE] Schema no cargado, saltando validación ({context})")
        return
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
        logger.info(f"[ALICE] Envelope válido ({context})")
    except jsonschema.exceptions.ValidationError as e:
        logger.error(f"[ALICE] ERROR VALIDACIÓN OFP ({context}): {e.message}")
        logger.error(f"Path: {list(e.path)}")
        logger.error(f"Valor que falla: {e.instance}")
        if hasattr(e, 'schema_path'):
            logger.error(f"Schema path: {list(e.schema_path)}")
        logger.error(f"Envelope que falló:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
        raise ValueError(f"Invalid OFP envelope: {str(e)}")

def create_openfloor_envelope(events, conversation_id=None):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": ALICE_SPEAKER_URI},
            "events": events
        }
    }

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": ALICE_SERVICE_URL, "speakerUri": ALICE_SPEAKER_URI},
                        "role": "Chatbot conversacional clásico",
                        "name": "ALICE",
                        "description": "Clásico chatbot ALICE basado en AIML. Ideal para conversación general y small-talk. Soporta delegación.",
                        "keywords": ["alice", "aiml", "chatbot", "conversación", "small-talk"],
                        "languages": ["en"],
                        "modalities": ["text"],
                        "capabilities": ["conversation", "small-talk", "delegation-accept"]
                    }
                }
            }]
        }
    }

# ── Kernel AIML ───────────────────────────────────────────────
alice_kernel = Kernel()

aiml_directory = "aiml_files"
aiml_files = glob.glob(f"{aiml_directory}/*.aiml")

logger.info(f"[ALICE STARTUP] Archivos AIML encontrados: {len(aiml_files)}")
for filepath in sorted(aiml_files):
    logger.info(f"[ALICE] Cargando: {filepath}")
    try:
        alice_kernel.learn(filepath)
    except Exception as e:
        logger.error(f"[ALICE] ERROR al cargar {filepath}: {str(e)}")

# Pruebas rápidas al inicio
test_phrases = ["HELLO", "WHAT IS YOUR NAME", "HOW ARE YOU"]
for phrase in test_phrases:
    reply = alice_kernel.respond(phrase, "startup_test")
    logger.info(f"[ALICE STARTUP TEST] '{phrase}' → '{reply}'")

logger.info("[ALICE STARTUP] Kernel AIML listo.")

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
        conversation_id = openfloor.get('conversation', {}).get('id') or str(uuid.uuid4())

        responses = []
        query_to_process = None

        for event in events:
            event_type = event.get('eventType')

            if event_type == 'getManifests':
                manifest_resp = get_manifest()
                if conversation_id:
                    manifest_resp['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(manifest_resp)

            elif event_type == 'utterance':
                try:
                    tokens = event.get("parameters", {}).get("dialogEvent", {}).get("features", {}).get("text", {}).get("tokens", [])
                    if tokens:
                        query_to_process = tokens[0].get("value", "").strip()
                        logger.info(f"[ALICE] Query recibida: {query_to_process}")
                except Exception as ex:
                    logger.error(f"[ALICE] Error extrayendo utterance: {ex}")
                    responses.append({"eventType": "error", "parameters": {"message": "Error al extraer texto del utterance"}})
                    continue

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {
                        "reason": "ALICE acepta la delegación para conversación general",
                        "accepted": True
                    }
                })
                logger.info("[ALICE] Delegación aceptada")

            elif event_type == 'transfer_control':
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control aceptado por ALICE"}
                })

            elif event_type == 'yieldFloor':
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso conversacional recibido por ALICE"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        # ── Procesar la query SOLO si existe ──
        if query_to_process:
            if not query_to_process.strip():
                reply = "No entendí... ¿puedes repetirlo?"
            else:
                try:
                    alice_reply = alice_kernel.respond(query_to_process.upper(), conversation_id)

                    if not alice_reply or alice_reply.strip().lower() in ["", "unknown", "*"]:
                        alice_reply = "Hmm... interesante. ¿Puedes decirlo de otra forma?"
                except Exception as e:
                    logger.error(f"[ALICE] respond falló: {str(e)}")
                    alice_reply = "Ups, algo salió mal en mi cerebro AIML..."

            now = datetime.utcnow()
            start_iso = now.isoformat() + "Z"
            end_iso = (now + timedelta(seconds=2)).isoformat() + "Z"

            reply_event = {
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": ALICE_SPEAKER_URI,
                        "span": {
                            "startTime": start_iso,
                            "endTime": end_iso
                        },
                        "features": {
                            "text": {
                                "mimeType": "text/plain",
                                "tokens": [{"value": alice_reply}]
                            }
                        }
                    }
                }
            }
            responses.append(reply_event)

            # yieldFloor SOLO si hubo respuesta útil (y SIN parámetros)
            if alice_reply and "no entendí" not in alice_reply.lower() and "ups" not in alice_reply.lower():
                responses.append({
                    "eventType": "yieldFloor",
                    "parameters": {}   # ← CORREGIDO: vacío, sin "message"
                })

        # ── Envelope final ──
        response_payload = create_openfloor_envelope(responses, conversation_id)
        validate_envelope(response_payload, context="respuesta enviada")

        return jsonify(response_payload)

    except ValueError as ve:
        logger.error(f"[ALICE] Error de validación: {ve}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(ve)}}]
            }
        }), 400
    except Exception as e:
        logger.exception(f"[ALICE] ERROR CRÍTICO: {str(e)}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(e)}}]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=False)