from flask import Flask, request, jsonify
import uuid
from datetime import datetime, timezone, timedelta
import json
import jsonschema
from chat import get_response   # ← importa directamente del History-Bot
import logging

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === CONFIG OFP ===
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"
HISTORY_SERVICE_URL = "http://assistant_history:5003/receive"
HISTORY_SPEAKER_URI = "tag:history-bot.local,2026:hist001"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
    logger.info("Schema OFP cargado correctamente desde %s", SCHEMA_PATH)
except Exception as e:
    logger.critical("No se pudo cargar el schema OFP: %s", e)
    raise RuntimeError(f"Schema OFP no encontrado: {e}")

def validate_envelope(data, context=""):
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
        logger.debug(f"Envelope válido ({context})")
    except jsonschema.exceptions.ValidationError as e:
        logger.error(f"ERROR VALIDACIÓN OFP ({context}): {e.message}")
        logger.error(f"Path: {list(e.path)}")
        logger.error(f"Valor que falla: {e.instance}")
        logger.error(f"Envelope que falló:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
        raise ValueError(f"Envelope OFP inválido: {str(e)}")

def create_response_envelope(events, conversation_id=None):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": HISTORY_SPEAKER_URI},
            "events": events
        }
    }

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    logger.info("Solicitud de manifest recibida")
    manifest_data = {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": HISTORY_SERVICE_URL, "speakerUri": HISTORY_SPEAKER_URI},
                        "role": "Asistente de Historia",
                        "name": "HistoryBot",
                        "description": "Asistente educativo especializado en Historia (basado en intents fijos). Soporta delegación.",
                        "keywords": ["historia", "guerras", "revoluciones", "figuras historicas"],
                        "languages": ["en"],
                        "modalities": ["text"],
                        "capabilities": ["utterance", "knowledge", "delegation-accept"]
                    }
                }
            }]
        }
    }
    return jsonify(manifest_data)

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json(silent=True) or {}
        logger.debug("Envelope recibido: %s", json.dumps(data, ensure_ascii=False, indent=2))

        validate_envelope(data, context="entrada recibida")

        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        logger.info("Procesando %d eventos en conversación %s", len(events), conversation_id)

        responses = []
        query_to_process = None

        for event in events:
            event_type = event.get('eventType')
            logger.debug("Procesando evento: %s", event_type)

            if event_type == 'getManifests':
                logger.info("Solicitud de manifests detectada")
                return jsonify(publish_manifest().get_json())

            elif event_type == 'utterance':
                try:
                    dialog = event.get('parameters', {}).get('dialogEvent', {})
                    text_features = dialog.get('features', {}).get('text', {})
                    tokens = text_features.get('tokens', [])
                    if tokens:
                        query_to_process = tokens[0].get('value', '').strip()
                        logger.info("Mensaje del usuario recibido: %s", query_to_process)
                    else:
                        logger.warning("No se encontraron tokens en utterance")
                except Exception as parse_err:
                    logger.error("Error parseando utterance: %s", parse_err)
                    responses.append({"eventType": "error", "parameters": {"message": "Formato de utterance inválido"}})
                    continue

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {
                        "reason": "Aceptado por HistoryBot para subtarea histórica",
                        "accepted": True
                    }
                })
                logger.info("Delegación aceptada por HistoryBot")

            elif event_type == 'transfer_control':
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control aceptado por HistoryBot"}
                })

            elif event_type == 'yieldFloor':
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso conversacional recibido por HistoryBot"}
                })

            else:
                logger.debug("Evento no manejado: %s → ack", event_type)
                responses.append({"eventType": "ack"})

        # Procesar la query SOLO si existe
        if query_to_process:
            if not query_to_process.strip():
                logger.warning("Mensaje vacío recibido")
                reply = "No recibí ninguna pregunta histórica."
            else:
                try:
                    bot_reply = get_response(query_to_process)
                    logger.debug("Respuesta del History-Bot: %s", bot_reply)

                    if not bot_reply or not isinstance(bot_reply, str) or bot_reply.strip() == "":
                        bot_reply = "Lo siento, no tengo información sobre ese tema en mi base de datos."
                        logger.warning("Respuesta vacía → fallback")

                    # Filtro opcional
                    if "física" in query_to_process.lower() or "matemática" in query_to_process.lower():
                        bot_reply = "Esta pregunta parece ser de física o matemáticas, no de historia. " + bot_reply

                    reply = bot_reply

                except Exception as bot_err:
                    logger.exception("Error en get_response: %s", bot_err)
                    reply = "Ocurrió un error interno al procesar tu pregunta histórica."

            now = datetime.now(timezone.utc)
            start_iso = now.isoformat().replace('+00:00', 'Z')
            end_iso = (now + timedelta(seconds=2)).isoformat().replace('+00:00', 'Z')

            responses.append({
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": HISTORY_SPEAKER_URI,
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
            })

            # yieldFloor SOLO si hubo respuesta útil (y SIN parámetros)
            if reply and "no tengo información" not in reply.lower() and "error" not in reply.lower():
                responses.append({
                    "eventType": "yieldFloor",
                    "parameters": {}   # ← CORREGIDO: vacío, sin "message"
                })

        # Envelope final
        final_envelope = create_response_envelope(responses, conversation_id)
        logger.debug("Enviando respuesta OFP: %s", json.dumps(final_envelope, indent=2, ensure_ascii=False))

        validate_envelope(final_envelope, context="respuesta enviada")
        return jsonify(final_envelope)

    except ValueError as ve:
        logger.error("Error de validación: %s", str(ve))
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(ve)}}]
            }
        }), 400

    except Exception as e:
        logger.exception("Error crítico en /receive: %s", str(e))
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": "Error interno del asistente de historia"}}]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)