from flask import Flask, request, jsonify
from pyswip import Prolog
import json
import os
from datetime import datetime
import uuid
import jsonschema  # pip install jsonschema

app = Flask(__name__)

# Ruta al schema OFP dentro del contenedor
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"


# Carga el schema oficial una sola vez
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"No se encontró el schema OFP en: {SCHEMA_PATH}")
except json.JSONDecodeError:
    raise ValueError("El archivo de schema OFP está corrupto.")

BASE_DIR = os.path.dirname(__file__)
RITS_PATH = os.path.join(BASE_DIR, "rits_fractions.pl")

# Inicializa Prolog y carga el archivo
prolog = Prolog()
prolog.consult(RITS_PATH)

RITS_SERVICE_URL = "http://rits_math:5003/receive"
RITS_SPEAKER_URI = "tag:rits-math.local,2026:rits001"

def validate_envelope(data):
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
    except jsonschema.exceptions.ValidationError as e:
        raise ValueError(f"Invalid OFP envelope: {str(e)}")

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {
                            "url": RITS_SERVICE_URL,
                            "speakerUri": RITS_SPEAKER_URI
                        },
                        "role": "Tutor basado en reglas para fracciones matemáticas",
                        "name": "RITS Fractions Tutor",
                        "description": "Asistente virtual educativo basado en reglas (Prolog) para resolver y explicar operaciones con fracciones paso a paso.",
                        "keywords": ["fracciones", "matemáticas básicas", "suma fracciones", "resta fracciones", "simplificación"],
                        "languages": ["en"],  # Original en inglés, puedes traducir si adaptas el Prolog
                        "modalities": ["text"],
                        "capabilities": ["rule-based-tutoring", "step-by-step-explanation"]
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
        validate_envelope(data)  # Validación estricta contra schema oficial
        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        if not events:
            return jsonify({"error": "No events found"}), 400

        responses = []

        for event in events:
            event_type = event.get('eventType')

            if event_type == 'getManifests':
                manifest_response = get_manifest()
                if conversation_id:
                    manifest_response['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(manifest_response)

            elif event_type == 'utterance':
                try:
                    dialog_event = event['parameters']['dialogEvent']
                    tokens = dialog_event['features']['text']['tokens']
                    query = tokens[0]['value'] if tokens else ""
                    print(f"[RITS] Pregunta recibida: {query}")

                    if not query:
                        reply = "No se recibió texto en la utterance."
                    else:
                        # Consulta Prolog (ajusta el predicado real de rits_fractions.pl)
                        # Ejemplo genérico; revisa el archivo .pl para el predicado exacto
                        # result = list(prolog.query(f"solve('{query}', Answer)"))
                        # if result:
                        #     reply = result[0]['Answer']
                        # else:
                        #     reply = "No se pudo resolver la pregunta con las reglas disponibles."

                           # rits_simple_fractions  ESTE archivo nuevo para que sea un predicado directo y simple: solve_fraction(Question, Answer)
                        result = list(prolog.query(f"solve_fraction('{query}', Answer)"))
                        if result:
                             reply = result[0]['Answer']
                        else:
                            reply = "No se pudo resolver la pregunta con las reglas disponibles."

                    # Respuesta utterance 100% compliant
                    now_iso = datetime.utcnow().isoformat() + "Z"
                    response_event = {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": RITS_SPEAKER_URI,
                                "span": {
                                    "startTime": now_iso,
                                    "endTime": now_iso  # En producción mide tiempo real
                                },
                                "features": {
                                    "text": {
                                        "mimeType": "text/plain",  # Obligatorio
                                        "tokens": [{"value": reply}]
                                    }
                                }
                            }
                        }
                    }
                    responses.append(response_event)

                except (KeyError, IndexError) as parse_err:
                    print(f"[RITS] Error parseando utterance: {parse_err}")
                    responses.append({
                        "eventType": "error",
                        "parameters": {"message": "Formato de utterance inválido"}
                    })

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"reason": "Aceptado para fracciones matemáticas"}
                })

            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        # Envelope de respuesta 100% compliant
        response_payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {
                    "speakerUri": RITS_SPEAKER_URI
                },
                "events": responses
            }
        }

        validate_envelope(response_payload)  # Valida lo que envías
        return jsonify(response_payload)

    except ValueError as ve:
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{
                    "eventType": "error",
                    "parameters": {"message": str(ve)}
                }]
            }
        }), 400
    except Exception as e:
        print(f"[RITS] ERROR GENERAL: {str(e)}")
        return jsonify({
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "events": [{
                    "eventType": "error",
                    "parameters": {"message": str(e)}
                }]
            }
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)