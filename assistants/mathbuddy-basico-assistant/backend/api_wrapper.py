# api_wrapper.py → MathBuddy Básico (Wrapper OFP) - Versión corregida
from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta
import logging
import jsonschema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIG ====================
MATHBUDDY_INTERNAL_URL = "http://mathbuddy-basico-backend:8080"
MATHBUDDY_SPEAKER_URI = "tag:mathbuddy-basico.local,2026:mb002"
MATHBUDDY_API_KEY = os.getenv("MATHBUDDY_API_KEY", "mathbuddy-secret-key-2026")

SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

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
        logger.info(f"Envelope válido ({context})")
    except Exception as e:
        logger.error(f"ERROR VALIDACIÓN ({context}): {e}")
        raise ValueError(f"Invalid OFP envelope: {e}")

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {
                            "url": "http://mathbuddy-basico-wrapper:5012/receive",
                            "speakerUri": MATHBUDDY_SPEAKER_URI
                        },
                        "role": "Tutor de Matemáticas Básicas",
                        "name": "MathBuddy Básico",
                        "description": "Tutor IA para matemáticas desde 1° de primaria hasta 2° de secundaria (aritmética, fracciones, porcentajes, ecuaciones simples y geometría básica).",
                        "keywords": ["matemáticas básicas", "primaria", "secundaria baja"],
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
        validate_envelope(data, "entrada recibida")

        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        responses = []
        query_to_process = None

        # 1. Procesar todos los eventos
        for event in events:
            event_type = event.get('eventType')

            if event_type == 'getManifests':
                resp = get_manifest()
                if conversation_id:
                    resp['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(resp)

            elif event_type == 'utterance':
                try:
                    tokens = event['parameters']['dialogEvent']['features']['text']['tokens']
                    query_to_process = tokens[0]['value'] if tokens else ""
                    logger.info(f"Query recibida: {query_to_process[:150]}...")
                except Exception as ex:
                    logger.error(f"Error extrayendo utterance: {ex}")

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"accepted": True, "reason": "MathBuddy Básico acepta subtarea básica"}
                })

            elif event_type in ['transfer_control', 'yieldFloor']:
                responses.append({"eventType": "ack", "parameters": {}})

        # 2. Si hay una pregunta, procesarla
        if query_to_process:
            enriched_query = f"""Eres MathBuddy Básico. Responde SIEMPRE siguiendo estas reglas estrictas:

            ÁREA DE EXPERTICIA:
            - Solo matemáticas básicas: primaria y hasta 2° de secundaria (sumas, restas, multiplicación, división, fracciones simples, porcentajes, proporciones, ecuaciones de primer grado, perímetros y áreas básicas).

            REGLAS DE COLABORACIÓN:
            - Si la pregunta es SOLO avanzada (derivadas, integrales, límites, trigonometría, etc.) → responde EXACTAMENTE:
            "Esta consulta es demasiado avanzada para mí (MathBuddy Básico). Intenta con MathBuddy Avanzado."

            - Si la pregunta es MIXTA → resuelve SOLO la parte básica y termina con exactamente esta línea:
            "[BASE LISTA: He preparado los cálculos básicos para el análisis avanzado]"

            - Si ves "[Aporte de physics]" o "[Aporte de mathbuddy_avanzado]" → úsalo y haz solo la parte básica.

            Formato:
            - NO saludes, NO des la bienvenida y NO uses frases como "¡Hola!" o "Claro, te ayudo".
            - Usa SIEMPRE español educativo y motivador.
            - Explica paso a paso, claro y sencillo.
            - Usa ejemplos cotidianos (dulces, frutas, juguetes).
            - Usa KaTeX para fórmulas.

            Pregunta: {query_to_process}

            Respuesta:"""

            # Llamada al backend real
            try:
                resp = requests.post(
                    f"{MATHBUDDY_INTERNAL_URL}/chat",
                    json={
                        "message": enriched_query,
                        "session_id": conversation_id or "default-basico-session"
                    },
                    headers={"X-API-Key": MATHBUDDY_API_KEY},
                    timeout=60
                )
                resp.raise_for_status()
                reply = resp.json().get("response", "No pude generar respuesta.")
            except Exception as e:
                logger.error(f"Error llamando al backend básico: {e}")
                reply = "Lo siento, el tutor básico no está disponible en este momento."

            # Respuesta al orquestador
            now = datetime.utcnow()
            response_event = {
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": MATHBUDDY_SPEAKER_URI,
                        "span": {
                            "startTime": now.isoformat() + "Z",
                            "endTime": (now + timedelta(seconds=3)).isoformat() + "Z"
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

            # YieldFloor solo si no rechazó por ser avanzado
            if "demasiado avanzada" not in reply.lower():
                responses.append({"eventType": "yieldFloor", "parameters": {}})

        # 3. Respuesta final
        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": MATHBUDDY_SPEAKER_URI},
                "events": responses
            }
        }

        validate_envelope(payload, "respuesta enviada")
        return jsonify(payload)

    except ValueError as ve:
        return jsonify({"openFloor": {"schema": {"version": "1.1.0"}, "events": [{"eventType": "error", "parameters": {"message": str(ve)}}]}}), 400
    except Exception as e:
        logger.exception("Error general en wrapper MathBuddy Básico")
        return jsonify({"openFloor": {"schema": {"version": "1.1.0"}, "events": [{"eventType": "error", "parameters": {"message": "Error interno"}}]}}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5012)