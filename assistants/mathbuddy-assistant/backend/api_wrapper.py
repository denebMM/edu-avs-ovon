from flask import Flask, request, jsonify
import ollama
import json
from datetime import datetime, timedelta
import uuid
import jsonschema
from pathlib import Path
import logging

# Logging para depurar
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

MATHBUDDY_SERVICE_URL = "http://assistant_mathbuddy:5011/receive"
MATHBUDDY_SPEAKER_URI = "tag:mathbuddy.local,2026:mb001"

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
        logger.error(f"Envelope que falló:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
        raise ValueError(f"Invalid OFP envelope: {e}")

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": MATHBUDDY_SERVICE_URL, "speakerUri": MATHBUDDY_SPEAKER_URI},
                        "role": "Tutor de Matemáticas",
                        "name": "MathBuddy",
                        "description": "Tutor IA para matemáticas desde aritmética básica hasta Cálculo 1.",
                        "keywords": ["matemáticas", "álgebra", "cálculo", "tutor"],
                        "languages": ["es"],
                        "modalities": ["text"],
                        "capabilities": ["step-by-step", "problem-solving", "delegation-accept"]
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
                    logger.info(f"Query recibida: {query_to_process}")
                except Exception as ex:
                    logger.error(f"Error extrayendo utterance: {ex}")
                    responses.append({"eventType": "error", "parameters": {"message": "Error en formato utterance"}})
                    continue

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {
                        "reason": "Aceptado por MathBuddy para subtarea matemática",
                        "accepted": True
                    }
                })
                logger.info("Delegación aceptada")

            elif event_type == 'transfer_control':
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control aceptado por MathBuddy"}
                })

            elif event_type == 'yieldFloor':
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso recibido por MathBuddy"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

           # Procesar query si existe
        if query_to_process:
            prompt = f"""REGLAS ESTRÍCTAS (lee primero y obedece siempre):
                - SOLO respondes preguntas PURAS de matemáticas (3° secundaria a Cálculo 1).
                - SI la pregunta incluye "traduce", "traducción", "al inglés", "al francés", "explícala en otro idioma" o CUALQUIER mención a idioma diferente del español → responde SOLO esta frase y nada más:
                "Esta consulta no es de mi área (matemáticas de 3° de secundaria hasta Cálculo 1). Puedo ayudarte con resolución de problemas, demostraciones y explicaciones paso a paso."
                - NO traduzcas NUNCA, ni siquiera partes de la pregunta.
                - NO respondas nada extra si no es matemática pura.

                Pregunta: {query_to_process}

                Responde SIEMPRE en español, claro, educativo y paso a paso. Usa ejemplos cotidianos si ayuda. Sin saludos ni texto innecesario."""

            try:
                stream = ollama_client.chat(
                    model='llama3.1:8b',
                    messages=[{'role': 'user', 'content': prompt}],
                    stream=True,
                    options={
                        "temperature": 0.3,
                        "num_predict": 1200,
                        "num_gpu": -1
                    }
                )

                reply = ""
                for chunk in stream:
                    if 'message' in chunk and 'content' in chunk['message']:
                        reply += chunk['message']['content']

                reply = reply.strip() or "No pude resolver."

            except Exception as ollama_err:
                logger.error(f"Error Ollama: {ollama_err}")
                reply = "Error al procesar la pregunta matemática."

            now = datetime.utcnow()
            start_iso = now.isoformat() + "Z"
            end_iso = (now + timedelta(seconds=2)).isoformat() + "Z"

            response_event = {
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": MATHBUDDY_SPEAKER_URI,
                        "span": {"startTime": start_iso, "endTime": end_iso},
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

            # Solo agregar yieldFloor si realmente respondimos
            if reply and "no es de mi área" not in reply.lower():
                responses.append({
                    "eventType": "yieldFloor",
                    "parameters": {}   # vacío, sin "message"
                })

        # Respuesta final
        response_payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": MATHBUDDY_SPEAKER_URI},
                "events": responses
            }
        }

        validate_envelope(response_payload, context="respuesta que enviamos")
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
        logger.exception("Error general en MathBuddy")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(e)}}]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5011, debug=False)