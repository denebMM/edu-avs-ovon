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

# ¡Cambios aquí!
MATHBUDDY_SERVICE_URL = "http://assistant_mathbuddy_basico:5012/receive"  # Puerto diferente
MATHBUDDY_SPEAKER_URI = "tag:mathbuddy-basico.local,2026:mb002"          # URI diferente

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
                        "role": "Tutor de Matemáticas Básicas",
                        "name": "MathBuddy Básico",
                        "description": "Tutor IA para matemáticas desde 1° de primaria hasta 1° de secundaria (sumas, restas, fracciones, porcentajes, ecuaciones simples, geometría básica).",
                        "keywords": ["matemáticas básicas", "primaria", "secundaria baja", "tutor"],
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
                        "reason": "Aceptado por MathBuddy Básico para subtarea matemática simple",
                        "accepted": True
                    }
                })
                logger.info("Delegación aceptada")

            elif event_type == 'transfer_control':
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control aceptado por MathBuddy Básico"}
                })

            elif event_type == 'yieldFloor':
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso recibido por MathBuddy Básico"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        # Procesar query si existe (¡esto debe estar indentado!)
        if query_to_process:
            prompt = f"""REGLAS ESTRÍCTAS (lee primero y obedece siempre):
            - SOLO respondes preguntas PURAS de matemáticas de nivel básico (1° primaria hasta 1° secundaria): sumas, restas, multiplicaciones, divisiones, fracciones simples, porcentajes, decimales, proporciones, ecuaciones de primer grado, perímetro, área básica, geometría elemental (triángulos, cuadrados, círculos).
            - SI la pregunta incluye temas avanzados (álgebra intermedia, funciones, trigonometría, derivadas, límites, integrales, logaritmos, ecuaciones cuadráticas, matrices) → responde SOLO esta frase y nada más:
            "Esta consulta es demasiado avanzada para mí (MathBuddy Básico). Puedo ayudarte con matemáticas de primaria y secundaria baja. Intenta con MathBuddy Avanzado o reformula la pregunta."
            - SI la pregunta incluye "traduce", "traducción", "al inglés", "al francés" o cualquier cambio de idioma → responde SOLO esta frase y nada más:
            "Esta consulta no es de mi área (matemáticas básicas). Puedo ayudarte con sumas, restas, fracciones, porcentajes y geometría simple."
            - NO traduzcas NUNCA, ni siquiera partes de la pregunta.
            - NO respondas nada extra si no es matemática básica.

            Pregunta: {query_to_process}

            Responde SIEMPRE en español, muy claro, sencillo y paso a paso. Usa ejemplos cotidianos (frutas, juguetes, dinero) para niños y adolescentes. Sin saludos ni texto innecesario. Usa lenguaje amable y motivador."""

            try:
                stream = ollama_client.chat(
                    model='llama3.2:3b',
                    messages=[{'role': 'user', 'content': prompt}],
                    stream=True,
                    options={
                        "temperature": 0.4,
                        "num_predict": 1000,
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
                reply = "Error al procesar la pregunta matemática básica."

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
            if reply and "no es de mi área" not in reply.lower() and "demasiado avanzada" not in reply.lower():
                responses.append({
                    "eventType": "yieldFloor",
                    "parameters": {}
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
        logger.exception("Error general en MathBuddy Básico")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{"eventType": "error", "parameters": {"message": str(e)}}]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5012, debug=False)