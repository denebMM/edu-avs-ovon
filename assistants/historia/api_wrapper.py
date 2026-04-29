from flask import Flask, request, jsonify
import requests
import json
from datetime import datetime, timedelta

app = Flask(__name__)

HIST_INTERNAL_URL = "http://historia-backend:5000/preguntar" 
HIST_SPEAKER_URI = "tag:historia.local,2026:agent001"

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify({
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": "http://assistant_historia:5016/receive", "speakerUri": HIST_SPEAKER_URI},
                        "role": "Especialista en Historia",
                        "name": "HistoryBot",
                        "description": "Agente experto en eventos históricos, fechas y procesos sociales.",
                        "languages": ["es"],
                        "capabilities": ["historical-analysis", "chronology"]
                    }
                }
            }]
        }
    })

@app.route('/receive', methods=['POST'])
def handle_receive():
    data = request.get_json()
    openfloor = data.get('openFloor', {})
    conversation_id = openfloor.get('conversation', {}).get('id')
    
    # Extraer query del orquestador
    events = openfloor.get('events', [])
    query = ""
    for event in events:
        if event.get('eventType') == 'utterance':
            query = event['parameters']['dialogEvent']['features']['text']['tokens'][0]['value']

    # Llamada al backend
    resp = requests.post(HIST_INTERNAL_URL, json={"pregunta": query}, timeout=120)
    reply = resp.json().get("respuesta", "No pude procesar la consulta de historia.")

    now = datetime.utcnow()
    payload = {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": HIST_SPEAKER_URI},
            "events": [
                {
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": HIST_SPEAKER_URI,
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
    app.run(host='0.0.0.0', port=5016)