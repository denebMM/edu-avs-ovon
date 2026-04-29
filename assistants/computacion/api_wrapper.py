from flask import Flask, request, jsonify
import requests
import json
import logging
import jsonschema
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURACIÓN DE IDENTIDAD ---
COMP_INTERNAL_URL = "http://computacion-backend:5000/preguntar" 
COMP_SPEAKER_URI = "tag:computacion.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    logger.error(f"Error cargando esquema: {e}")

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify({
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": "http://assistant_computacion:5014/receive", "speakerUri": COMP_SPEAKER_URI},
                        "role": "Especialista en Computación",
                        "name": "CompBot",
                        "description": "Asistente experto en informática y arquitectura de computadoras.",
                        "languages": ["es"],
                        "capabilities": ["it-theory", "hardware-software"]
                    }
                }
            }]
        }
    })

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json() or {}
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)

        events = data.get('openFloor', {}).get('events', [])
        conversation_id = data.get('openFloor', {}).get('conversation', {}).get('id')

        query = ""
        for event in events:
            if event.get('eventType') == 'utterance':
                query = event['parameters']['dialogEvent']['features']['text']['tokens'][0]['value']

        # Llamada al backend de computación
        resp = requests.post(COMP_INTERNAL_URL, json={"pregunta": query}, timeout=120)
        reply = resp.json().get("respuesta", "Error en motor de computación")

        now = datetime.utcnow()
        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": COMP_SPEAKER_URI},
                "events": [{
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": COMP_SPEAKER_URI,
                            "span": {"startTime": now.isoformat()+"Z", "endTime": (now+timedelta(seconds=2)).isoformat()+"Z"},
                            "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": reply}]}}
                        }
                    }
                }, {"eventType": "yieldFloor", "parameters": {}}]
            }
        }
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5014) # Puerto 5014 para Computación