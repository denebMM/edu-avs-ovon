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
ALGEBRA_INTERNAL_URL = "http://algebra-backend:5000/preguntar"
ALGEBRA_SPEAKER_URI = "tag:algebra.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

# Cargar esquema de validación
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    logger.error(f"No se pudo cargar el esquema en {SCHEMA_PATH}: {e}")
    OFP_SCHEMA = None

def validate_envelope(data, context=""):
    try:
        if OFP_SCHEMA:
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
                            "url": "http://assistant_algebra:5013/receive", 
                            "speakerUri": ALGEBRA_SPEAKER_URI
                        },
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
       
        query_to_process = ""
        for event in events:
            if event.get('eventType') == 'utterance':
                try:
                    tokens = event['parameters']['dialogEvent']['features']['text']['tokens']
                    query_to_process = tokens[0]['value'] if tokens else ""
                except (KeyError, IndexError): continue

        if not query_to_process:
            return jsonify({"error": "No se recibió query"}), 400

        # --- DETECTAR EL TOKEN DE AUTORIDAD ---
        forzar_respuesta = False
        if "[FORZAR_RESPUESTA]" in query_to_process:
            forzar_respuesta = True
            query_to_process = query_to_process.replace("[FORZAR_RESPUESTA]", "").strip()
        # --------------------------------------

        # LLAMADA AL BACKEND
        try:
            # Corregido: Uso de ALGEBRA_INTERNAL_URL
            resp = requests.post(ALGEBRA_INTERNAL_URL, json={"pregunta": query_to_process}, timeout=300)
            resp.raise_for_status()
            backend_data = resp.json()
            reply = backend_data.get("respuesta", "").strip()

            # --- LÓGICA DE ERROR_DOMINIO IGNORADA SI HAY ORDEN ---
            if not forzar_respuesta and (not reply or "no está relacionad" in reply.lower()):
                logger.warning(f"Agente detectó fuera de dominio.")
                reply = "ERROR_DOMINIO"
            # -----------------------------------------------------
            
        # Corregido: Se agregó el except correspondiente para evitar crasheos si el backend cae
        except Exception as e:
            logger.error(f"Error conectando con backend de álgebra: {e}")
            reply = "ERROR_DOMINIO" 

        # Empaquetado OFP
        now = datetime.utcnow()
        start_iso = now.isoformat() + "Z"
        end_iso = (now + timedelta(seconds=2)).isoformat() + "Z"

        responses = [{
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": ALGEBRA_SPEAKER_URI,
                    "span": {"startTime": start_iso, "endTime": end_iso},
                    "features": {
                        "text": {"mimeType": "text/plain", "tokens": [{"value": reply}]}
                    }
                }
            }
        }, {"eventType": "yieldFloor", "parameters": {}}]

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
    app.run(host='0.0.0.0', port=5013, debug=False)