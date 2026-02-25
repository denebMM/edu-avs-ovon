from flask import Flask, request, jsonify
import ollama
import json
import os
from datetime import datetime
import uuid
import jsonschema  # pip install jsonschema

app = Flask(__name__)

OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

MATH_SERVICE_URL = "http://assistant_math:5001/receive"
MATH_SPEAKER_URI = "tag:math-assistant.local,2026:math001"

# Schema OFP v1.1.0 oficial (copiado dehttps://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/1.1.0/conversation-envelope-schema.json)
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"
# Carga el schema oficial una sola vez al inicio del módulo
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"No se encontró el schema OFP en: {SCHEMA_PATH}. Descárgalo de GitHub.")
except json.JSONDecodeError:
    raise ValueError("El archivo de schema OFP está corrupto o mal formado.")

def validate_envelope(data):
    """Valida un envelope contra el schema oficial OVON/OFP v1.1.0"""
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
    except jsonschema.exceptions.ValidationError as validation_error:
        raise ValueError(f"Envelope OFP inválido: {str(validation_error)}")
    


def validate_envelope(data):
    """Valida el envelope recibido contra el schema oficial OFP v1.1.0"""
    try:
        jsonschema.validate(instance=data, schema=OFP_SCHEMA)
    except jsonschema.exceptions.ValidationError as e:
        raise ValueError(f"Invalid OFP envelope: {str(e)}")

def get_manifest():
    """Devuelve el manifest conforme al schema Assistant Manifest (compatible con OFP)"""
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {
                            "url": MATH_SERVICE_URL,
                            "speakerUri": MATH_SPEAKER_URI
                        },
                        "role": "Especialista en Matemáticas",
                        "name": "MathSolver",
                        "description": "Resuelve problemas de matemáticas, álgebra, cálculo, ecuaciones, etc. Responde en español.",
                        "keywords": ["matemáticas", "ecuaciones", "cálculo", "álgebra", "resolver", "fracciones"],
                        "languages": ["es", "en"],
                        "modalities": ["text"],
                        "capabilities": ["math-solving", "step-by-step-explanation"]
                    }
                }
            }]
        }
    }

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    """Endpoint dedicado para publicación del manifest (recomendado por OFP)"""
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
                    print(f"[MATH v3] Pregunta recibida: {query}")

                    if not query:
                        reply = "No se recibió texto en la utterance."
                    else:
                        prompt = f"""Eres un experto en matemáticas. Responde SOLO con la solución clara, paso a paso y explicación breve en español. No saludes ni añadas texto innecesario.

Pregunta: {query}"""

                        try:
                            stream = ollama_client.chat(
                                model='qwen2:1.5b',
                                messages=[{'role': 'user', 'content': prompt}],
                                stream=True,
                                options={
                                       "temperature": 0.2,
                                        "timeout": 180,
                                        "num_gpu": -1,           # ← Fuerza GPU completa
                                        "num_thread": 4,         # ← Balance CPU
                                        "num_predict": 800       # ← Límite razonable
                                    }
                            )

                            reply = ""
                            for chunk in stream:
                                if 'message' in chunk and 'content' in chunk['message']:
                                    content = chunk['message']['content']
                                    reply += content
                                    print(content, end='', flush=True)

                            reply = reply.strip() or "No se pudo generar respuesta."
                            print(f"\n[MATH v3] Respuesta: {reply}")

                        except Exception as e:
                            print(f"[MATH v3] Error Ollama: {e}")
                            reply = f"Error al procesar con el modelo: {str(e)}"

                    # Respuesta utterance 100% compliant
                    now_iso = datetime.utcnow().isoformat() + "Z"
                    response_event = {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": MATH_SPEAKER_URI,
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
                    print(f"[MATH v3] Error parseando utterance: {parse_err}")
                    responses.append({
                        "eventType": "error",
                        "parameters": {"message": "Formato de utterance inválido"}
                    })

            elif event_type == 'request_delegation':
                # Respuesta básica compliant a request_delegation
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"reason": "Aceptado para matemáticas"}
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
                    "speakerUri": MATH_SPEAKER_URI
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
        print(f"[MATH v3] ERROR GENERAL: {str(e)}")
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
    app.run(host='0.0.0.0', port=5001, debug=False)