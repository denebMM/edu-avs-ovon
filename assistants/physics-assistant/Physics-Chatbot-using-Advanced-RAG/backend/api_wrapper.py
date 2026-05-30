from flask import Flask, request, jsonify
import requests
import json
import logging
import jsonschema
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

PHYSICS_INTERNAL_URL = "http://physics-backend:5000/api/generate"
PHYSICS_SPEAKER_URI = "tag:physics-assistant.local,2026:phys001"

SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
    OFP_SCHEMA = json.load(f)

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
                        "service": {"url": "http://assistant_physics:5002/receive", "speakerUri": PHYSICS_SPEAKER_URI},
                        "role": "Especialista en Física",
                        "name": "PhysicsBot",
                        "description": "Agente de física con RAG. Colabora con otros asistentes.",
                        "languages": ["es"],
                        "capabilities": ["explanation", "physics-logic"]
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
        validate_envelope(data, "Entrada Orquestador")

        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        query_to_process = None

        for event in events:
            if event.get('eventType') == 'utterance':
                try:
                    tokens = event['parameters']['dialogEvent']['features']['text']['tokens']
                    query_to_process = tokens[0]['value'] if tokens else ""
                    logger.info(f"Query recibida: {query_to_process[:200]}...")
                except Exception as ex:
                    logger.error(f"Error extrayendo query: {ex}")

        if not query_to_process:
            return jsonify({"error": "No se recibió query"}), 400

        # Prompt enriquecido seguro para el backend
        enriched_prompt = f"""[INSTRUCCIÓN DE COLABORACIÓN]
Actúa como experto en Física escolar (grados 9-10).
Explica claramente el concepto, usa fórmulas cuando sea necesario y mantén el lenguaje accesible.

Pregunta del usuario: {query_to_process}"""

        try:
            # Llamada correcta al backend (usa 'prompt' como clave)
            resp = requests.post(
                PHYSICS_INTERNAL_URL,
                json={
                    "prompt": enriched_prompt,     
                    "session_id": conversation_id or "default"
                },
                timeout=450
            )
            resp.raise_for_status()
            
            backend_data = resp.json()
            # Ajusta según lo que realmente devuelve tu backend
            reply = backend_data.get("response") or backend_data.get("answer") or str(backend_data)

        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión con physics-backend: {e}")
            reply = "Lo siento, no pude conectar con el motor de física en este momento."
        except Exception as e:
            logger.error(f"Error procesando respuesta de física: {e}")
            reply = "Ocurrió un error interno al procesar la pregunta de física."

        # Construcción del envelope OFP
        # --- CÁLCULO DE TIEMPO PARA EL SPAN ---
        now = datetime.utcnow()
        # Simulamos que el bot tardó 3 segundos en "decir" la respuesta
        start_iso = now.isoformat() + "Z"
        end_iso = (now + timedelta(seconds=3)).isoformat() + "Z"

        # Construcción del envelope OFP
        responses = [{
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": PHYSICS_SPEAKER_URI,
                    "span": {
                        "startTime": start_iso, 
                        "endTime": end_iso  # <-- Ahora tiene una duración real
                    },
                    "features": {
                        "text": {
                            "mimeType": "text/plain",
                            "tokens": [{"value": reply}]
                        }
                    }
                }
            }
        }, {
            "eventType": "yieldFloor",
            "parameters": {}
        }]

        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": PHYSICS_SPEAKER_URI},
                "events": responses
            }
        }
        return jsonify(payload)

    except Exception as e:
        logger.error(f"Error general en wrapper physics: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)