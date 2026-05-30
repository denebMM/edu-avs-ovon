from flask import Flask, request, jsonify
import requests
import json
from datetime import datetime
import logging
# IMPORTANTE: Esto ataca el error antes de que llegue a Flask
from werkzeug.serving import WSGIRequestHandler 

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- BYPASS TOTAL DE SEGURIDAD (SOLUCIÓN MAESTRA) ---
# Sobrescribimos el validador de Werkzeug para que ignore el Host Header de Docker
WSGIRequestHandler.address_string = lambda self: "127.0.0.1"

app = Flask(__name__)

# Engaño adicional en la capa de aplicación
@app.before_request
def final_host_bypass():
    if 'Host' in request.headers:
        request.environ['HTTP_HOST'] = 'localhost:5010'

# URL del contenedor que procesa la traducción (api_lingonaut.py)
LINGONAUT_BACKEND_URL = "http://translator-backend:8080/chat"

@app.route('/receive', methods=['POST'])
def handle_receive():
    logger.debug("=== NUEVA PETICIÓN RECIBIDA EN TRADUCTOR ===")
    
    data = request.get_json(silent=True) or {}
    logger.debug(f"JSON recibido:\n{json.dumps(data, indent=2)}")

    query_to_process = None
    openfloor = data.get('openFloor', {})
    events = openfloor.get('events', [])

    # 1. Extracción robusta de texto (Estándar OFP)
    for event in events:
        if event.get('eventType') == 'utterance':
            try:
                tokens = (event.get('parameters', {})
                             .get('dialogEvent', {})
                             .get('features', {})
                             .get('text', {})
                             .get('tokens', []))

                if tokens and len(tokens) > 0:
                    query_to_process = tokens[0].get('value', '').strip()
                    logger.info(f"✓ TEXTO A TRADUCIR: '{query_to_process}'")
                    break
            except Exception as ex:
                logger.error(f"Error extrayendo tokens: {ex}")

    # 2. Comunicación con el Backend de Traducción (Mistral/Llama3 via FastAPI)
    reply = "No se recibió texto válido."
    if query_to_process:
        try:
            logger.info(f"Llamando a backend: {LINGONAUT_BACKEND_URL}")
            r = requests.post(
                LINGONAUT_BACKEND_URL, 
                json={"message": query_to_process, "session_id": "none"}, 
                timeout=450
            )
            r.raise_for_status()
            reply = r.json().get("response", "Error: Respuesta vacía del backend")
            logger.info("✓ Traducción obtenida con éxito")
        except Exception as e:
            logger.error(f"✗ Error en comunicación con backend: {e}")
            reply = "Servicio de traducción temporalmente fuera de línea."

    # 3. Empaquetado de respuesta (Sobre OFP v1.1.0)
    now = datetime.utcnow().isoformat() + "Z"
    response_payload = {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": openfloor.get('conversation', {}).get('id', 'unknown')},
            "sender": {"speakerUri": "tag:translator.local,2026:trans001"},
            "events": [
                {
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": "tag:translator.local,2026:trans001",
                            "span": {"startTime": now, "endTime": now},
                            "features": {
                                "text": {
                                    "mimeType": "text/plain", 
                                    "tokens": [{"value": reply}]
                                }
                            }
                        }
                    }
                },
                {"eventType": "yieldFloor", "parameters": {}}
            ]
        }
    }

    return jsonify(response_payload)

if __name__ == '__main__':
    # Ejecución sin SERVER_NAME para evitar validaciones estrictas de host
    app.run(
        host='0.0.0.0', 
        port=5010, 
        debug=False, 
        threaded=True
    )