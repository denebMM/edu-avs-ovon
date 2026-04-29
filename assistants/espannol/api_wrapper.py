from flask import Flask, request, jsonify
import requests
import json
import jsonschema
from datetime import datetime, timedelta

app = Flask(__name__)

INTERNAL_URL = "http://espanol-backend:5000/preguntar" 
SPEAKER_URI = "tag:espanol.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify({
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": "http://assistant_espanol:5015/receive", "speakerUri": SPEAKER_URI},
                        "role": "Especialista en Lengua Española",
                        "name": "EspanolBot",
                        "description": "Asistente experto en gramática, ortografía y literatura.",
                        "languages": ["es"],
                        "capabilities": ["grammar-check", "literary-analysis"]
                    }
                }
            }]
        }
    })

@app.route('/receive', methods=['POST'])
def handle_receive():
    data = request.get_json()
    conversation_id = data.get('openFloor', {}).get('conversation', {}).get('id')
    
    # Extraer query
    events = data.get('openFloor', {}).get('events', [])
    query = ""
    for event in events:
        if event.get('eventType') == 'utterance':
            query = event['parameters']['dialogEvent']['features']['text']['tokens'][0]['value']

    # Hablar con el backend
    resp = requests.post(INTERNAL_URL, json={"pregunta": query}, timeout=120)
    reply = resp.json().get("respuesta", "Lo siento, hubo un error.")

    now = datetime.utcnow()
    payload = {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": SPEAKER_URI},
            "events": [
                {
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": SPEAKER_URI,
                            "span": {"startTime": now.isoformat()+"Z", "endTime": (now+timedelta(seconds=2)).isoformat()+"Z"},
                            "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": reply}]}}
                        }
                    }
                },
                {"eventType": "yieldFloor", "parameters": {}}
            ]
        }
    }
    return jsonify(payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5015)