from flask import Flask, request, jsonify
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

QUI_INTERNAL_URL = "http://quimica-backend:5000/preguntar" 
QUI_SPEAKER_URI = "tag:quimica.local,2026:agent001"

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify({
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": "http://assistant_quimica:5018/receive", "speakerUri": QUI_SPEAKER_URI},
                        "role": "Especialista en Química",
                        "name": "QuimBot",
                        "description": "Agente experto en elementos, compuestos y reacciones químicas.",
                        "languages": ["es"],
                        "capabilities": ["chemical-reactions", "periodic-table-logic"]
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
    
    events = openfloor.get('events', [])
    query = ""
    for event in events:
        if event.get('eventType') == 'utterance':
            query = event['parameters']['dialogEvent']['features']['text']['tokens'][0]['value']

    resp = requests.post(QUI_INTERNAL_URL, json={"pregunta": query}, timeout=120)
    reply = resp.json().get("respuesta", "Error en el asistente de química.")

    now = datetime.utcnow()
    payload = {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": QUI_SPEAKER_URI},
            "events": [
                {
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": QUI_SPEAKER_URI,
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
    app.run(host='0.0.0.0', port=5018)