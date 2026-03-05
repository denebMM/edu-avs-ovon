from flask import Flask, request, jsonify
import uuid
from datetime import datetime
import jsonschema
import json
import os
import glob
from pyaiml21 import Kernel  # el intérprete AIML

app = Flask(__name__)

# ── Configuración OFP ────────────────────────────────────────
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    print(f"[ALICE STARTUP] No se pudo cargar schema OFP: {e}")
    OFP_SCHEMA = {}

ALICE_SPEAKER_URI = "tag:alice.local,2026:alice001"
ALICE_SERVICE_URL = "http://assistant_alice:5005/receive"

def validate_envelope(data):
    if not OFP_SCHEMA:
        return
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
    except jsonschema.exceptions.ValidationError as e:
        raise ValueError(f"Invalid OFP envelope: {e}")

def create_openfloor_envelope(events, conversation_id=None):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": ALICE_SPEAKER_URI},
            "events": events
        }
    }

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": ALICE_SERVICE_URL, "speakerUri": ALICE_SPEAKER_URI},
                        "role": "Assistant",
                        "name": "Alice",
                        "description": "Clásico chatbot ALICE basado en AIML (reglas pattern-matching)",
                        "keywords": ["alice", "aiml", "chatbot clásico", "ofp", "conversación general"],
                        "languages": ["en"],
                        "modalities": ["text"],
                        "capabilities": ["conversation", "small-talk"]
                    }
                }
            }]
        }
    }

# ── Kernel AIML ───────────────────────────────────────────────
alice_kernel = Kernel()

# Carga TODOS los archivos .aiml de la carpeta aiml_files/
aiml_directory = "aiml_files"
aiml_files = glob.glob(f"{aiml_directory}/*.aiml")

print(f"[ALICE STARTUP] Archivos AIML encontrados: {len(aiml_files)}")
for filepath in sorted(aiml_files):
    print(f"  → Cargando: {filepath}")
    try:
        alice_kernel.learn(filepath)
    except Exception as e:
        print(f"  → ERROR al cargar {filepath}: {str(e)}")

# Pruebas rápidas de verificación al inicio (muy útil para debug)
test_phrases = [
    "HELLO",
    "WHAT IS YOUR NAME"
]
for phrase in test_phrases:
    reply = alice_kernel.respond(phrase, "startup_test")
    print(f"[ALICE STARTUP TEST] '{phrase}' → '{reply}'")
# No hay forma pública de contar categorías en pyaiml21, así que solo decimos OK
print("[ALICE STARTUP] Kernel listo. Carga completada.")    

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify(get_manifest())

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json() or {}
        validate_envelope(data)
        
        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id') or str(uuid.uuid4())

        responses = []
        for event in events:
            event_type = event.get('eventType')
            
            if event_type == 'getManifests':
                manifest_resp = get_manifest()
                if conversation_id:
                    manifest_resp['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(manifest_resp)
                
            elif event_type == 'utterance':
                tokens = event.get("parameters", {}).get("dialogEvent", {}).get("features", {}).get("text", {}).get("tokens", [])
                user_query = tokens[0].get("value", "").strip() if tokens else ""
                
                if user_query:
                    session_id = conversation_id
                    try:
                        alice_reply = alice_kernel.respond(user_query, session_id)
                        if not alice_reply or alice_reply.strip().lower() in ["", "unknown"]:
                            alice_reply = "No entiendo bien... ¿puedes decirlo de otra forma?"
                    except Exception as e:
                        print(f"[ALICE ERROR] respond falló: {str(e)}")
                        alice_reply = f"Error interno en Alice: {str(e)}"
                    
                    reply_event = {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": ALICE_SPEAKER_URI,
                                "span": {
                                    "startTime": datetime.utcnow().isoformat() + "Z",
                                    "endTime": datetime.utcnow().isoformat() + "Z"
                                },
                                "features": {
                                    "text": {
                                        "mimeType": "text/plain",
                                        "tokens": [{"value": alice_reply}]
                                    }
                                }
                            }
                        }
                    }
                    responses.append(reply_event)
                else:
                    responses.append({"eventType": "error", "parameters": {"message": "No query received"}})
                    
            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"reason": "Alice acepta la delegación"}
                })
                
            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        response_payload = create_openfloor_envelope(responses, conversation_id)
        validate_envelope(response_payload)  # buena práctica
        
        return jsonify(response_payload)

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=False)