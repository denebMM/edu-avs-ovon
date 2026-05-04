from flask import Flask, request, jsonify
import requests
import json
import logging
import jsonschema
from datetime import datetime, timedelta
import time

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURACIÓN DE IDENTIDAD ---
# Cambiamos las URLs y URIs para Álgebra
ALGEBRA_INTERNAL_URL = "http://algebra-backend:5000/preguntar"
ALGEBRA_SPEAKER_URI = "tag:algebra.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

# Cargar esquema de validación
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    logger.error(f"No se pudo cargar el esquema en {SCHEMA_PATH}: {e}")

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
                        "service": {"url": "http://assistant_algebra:5013/receive", 
                        "speakerUri": ALGEBRA_SPEAKER_URI},
                        "role": "Especialista en Álgebra",
                        "name": "AlgebraBot",
                        "description": "Asistente experto en álgebra con soporte RAG (Libros de texto).",
                        "languages": ["es"],
                        "capabilities": ["algebraic-resolution", "explanation"]
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
        validate_envelope(data, "Entrada Orquestador Álgebra")

        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        query_to_process = None

        # Extraer la pregunta del usuario desde el evento 'utterance'
        for event in events:
            if event.get('eventType') == 'utterance':
                try:
                    tokens = event['parameters']['dialogEvent']['features']['text']['tokens']
                    query_to_process = tokens[0]['value'] if tokens else ""
                except Exception as ex:
                    logger.error(f"Error extrayendo query: {ex}")

        if not query_to_process:
            return jsonify({"error": "No se recibió query"}), 400

        # Llamada al backend de Álgebra (el que lee los PDFs)
        try:
            start_time = time.time()
            resp = requests.post(ALGEBRA_INTERNAL_URL, json={"pregunta": query_to_process}, timeout=120)
            duration = time.time() - start_time
            logger.info(f"Backend procesó búsqueda semántica en {duration:.2f} segundos")
            resp.raise_for_status()
            backend_data = resp.json()
            
            # Extraemos la respuesta del JSON que definimos antes
            reply = backend_data.get("respuesta") or "No tengo una respuesta clara en este momento."

        except Exception as e:
            logger.error(f"Error conectando con backend de álgebra: {e}")
            reply = "Lo siento, mi motor de álgebra no está disponible."

        # Construcción del tiempo de respuesta
        now = datetime.utcnow()
        start_iso = now.isoformat() + "Z"
        end_iso = (now + timedelta(seconds=2)).isoformat() + "Z"

        # Empaquetado de vuelta al Orquestador (Formato OFP)
        responses = [{
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": ALGEBRA_SPEAKER_URI,
                    "span": {"startTime": start_iso, "endTime": end_iso},
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
                "sender": {"speakerUri": ALGEBRA_SPEAKER_URI},
                "events": responses
            }
        }
        return jsonify(payload)

    except Exception as e:
        logger.error(f"Error general en wrapper álgebra: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Puerto 5013 según tu esquema de puertos del docker-compose
    app.run(host='0.0.0.0', port=5013, debug=False)