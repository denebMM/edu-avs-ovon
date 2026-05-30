# api_wrapper.py  (en la carpeta wrapper/)
from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta
import logging
import jsonschema
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIG ====================
MATHBUDDY_INTERNAL_URL = "http://mathbuddy-avanzado-backend:8080"  # nombre del servicio FastAPI
MATHBUDDY_SPEAKER_URI = "tag:mathbuddy.local,2026:mb001"
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
                            "url": "http://assistant_mathbuddy_avanzado:5011/receive",
                            "speakerUri": MATHBUDDY_SPEAKER_URI
                        },
                        "role": "Tutor de Matemáticas Avanzadas",
                        "name": "MathBuddy Avanzado",
                        "description": "Tutor IA especializado en matemáticas desde 2° de secundaria hasta Cálculo 1 (álgebra intermedia, trigonometría, funciones, límites, derivadas, integrales).",
                        "keywords": ["matemáticas avanzadas", "cálculo", "tutor"],
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
                    logger.info(f"Query recibida: {query_to_process[:100]}...")
                except Exception as ex:
                    logger.error(f"Error extrayendo utterance: {ex}")

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"accepted": True, "reason": "MathBuddy Avanzado acepta subtarea avanzada"}
                })

            elif event_type in ['transfer_control', 'yieldFloor']:
                responses.append({"eventType": "ack", "parameters": {}})

        if query_to_process:
            # Inyectamos reglas de colaboración
            
            enriched_query = f"""Eres MathBuddy Avanzado. Tu objetivo es resolver la parte compleja de una cadena de colaboración educativa.
            
            INSTRUCCIONES DE SISTEMA:
            Eres MathBuddy Avanzado, un experto universitario en Cálculo Diferencial e Integral.
            REGLAS CRÍTICAS:
            1. PIENSA PASO A PASO. 
            2. EVALUACIÓN DE LÍMITES: Si evalúas un límite que da una indeterminación matemática (ejemplo 0/0), TIENES PROHIBIDO dar ese resultado. DEBES factorizar la expresión (ej. extraer factor común) para eliminar la indeterminación antes de evaluar el límite.
            3. PRECISIÓN: Utiliza notación LaTeX encerrada en $$ para todas tus fórmulas.

            REGLAS ESTRÍCTAS DE COLABORACIÓN:
            1. FOCO TÉCNICO: Solo resuelves álgebra intermedia, trigonometría, cálculo (límites, derivadas, integrales) y geometría analítica.
            2. INTEGRACIÓN DE CONTEXTO: 
             - SI el mensaje contiene "[Aporte de physics]": Toma las fórmulas físicas planteadas como hechos absolutos. No expliques la física, solo ejecuta el cálculo avanzado resultante (ej. derivar la ecuación de posición).
             - SI el mensaje contiene "[Aporte de mathbuddy_basico]": Utiliza los resultados aritméticos ya obtenidos. No vuelvas a sumar o restar lo que ya se resolvió; parte de esos valores para el siguiente paso complejo.
            3. RECHAZO INTELIGENTE: 
             - Si la consulta es 100% aritmética básica (ej. "cuánto es 5+5") y NO hay contexto de otros agentes → responde exactamente: "Esta consulta es demasiado básica para mí (MathBuddy Avanzado). Intenta con MathBuddy Básico."
             - Si la consulta es mixta, IGNORA la parte básica (deja que el otro agente la haga) y responde SOLO la parte avanzada.
            4. FORMATO:
             - NO saludes, NO des la bienvenida y NO uses frases como "¡Hola!" o "Claro, te ayudo".
             - Usa SIEMPRE español educativo y motivador.
             - Usa KaTeX para fórmulas.
             - Responde paso a paso, sin saludos ni introducciones.

            Pregunta/Contexto del usuario: {query_to_process}"""

            # Llamada al servicio MathBuddy real (FastAPI)
            try:
                resp = requests.post(
                    f"{MATHBUDDY_INTERNAL_URL}/chat",
                    json={
                        "message": enriched_query,
                        "session_id": conversation_id or "default-mathbuddy-session"
                    },
                    headers={"X-API-Key": MATHBUDDY_API_KEY},
                    timeout=300
                ) 
                resp.raise_for_status()
                reply = resp.json().get("response", "No pude generar respuesta.")
            except Exception as e:
                logger.error(f"Error llamando a MathBuddy backend: {e}")
                reply = "Error interno del tutor avanzado. Inténtalo de nuevo."

            # Evento de respuesta
            now = datetime.utcnow()
            response_event = {
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": MATHBUDDY_SPEAKER_URI,
                        "span": {
                            "startTime": now.isoformat() + "Z",
                            "endTime": (now + timedelta(seconds=4)).isoformat() + "Z"
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

            if "demasiado básica" not in reply.lower():
                responses.append({"eventType": "yieldFloor", "parameters": {}})

        # Payload final
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
        logger.exception("Error general en wrapper MathBuddy Avanzado")
        return jsonify({"openFloor": {"schema": {"version": "1.1.0"}, "events": [{"eventType": "error", "parameters": {"message": "Error interno"}}]}}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5011)