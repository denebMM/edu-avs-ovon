from flask import Flask, request, jsonify
import requests
import json
import logging
import jsonschema
from datetime import datetime, timedelta
import time

# Configuración de logs profesionales
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

INTERNAL_URL = "http://espanol-backend:5000/preguntar" 
SPEAKER_URI = "tag:espanol.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

# Carga de esquema de validación
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    logger.error(f"No se pudo cargar el esquema: {e}")
    OFP_SCHEMA = None

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
    try:
        data = request.get_json() or {}
        # Validar entrada
        if OFP_SCHEMA:
            jsonschema.validate(instance=data, schema=OFP_SCHEMA)

        conversation_id = data.get('openFloor', {}).get('conversation', {}).get('id')
        events = data.get('openFloor', {}).get('events', [])
        
        query = ""
        for event in events:
            if event.get('eventType') == 'utterance':
                try:
                    tokens = event['parameters']['dialogEvent']['features']['text']['tokens']
                    query = tokens[0]['value'] if tokens else ""
                except (KeyError, IndexError): continue

        if not query:
            return jsonify({"error": "No se recibió query"}), 400

        # --- DETECTAR EL TOKEN DE AUTORIDAD ---
        forzar_respuesta = False
        if "[FORZAR_RESPUESTA]" in query:
            forzar_respuesta = True
            query = query.replace("[FORZAR_RESPUESTA]", "").strip()
        # --------------------------------------

        # LLAMADA AL BACKEND CON VALIDACIÓN DE DOMINIO
        try:
            logger.info(f"Procesando consulta semántica para: {query[:50]}...")
            start_t = time.time()
            resp = requests.post(INTERNAL_URL, json={"pregunta": query}, timeout=300)
            resp.raise_for_status()
            duration = time.time() - start_t
            logger.info(f"Respuesta generada en {duration:.2f}s")
            
            backend_data = resp.json()
            reply = backend_data.get("respuesta", "").strip()
            
            # --- LÓGICA DE ERROR_DOMINIO IGNORADA SI HAY ORDEN ---
            # Cambiamos "relacionado" por "relacionad" para atrapar ambos géneros
            if not forzar_respuesta and (not reply or "no está relacionad" in reply.lower() or "error_dominio" in reply.lower()):
                logger.warning(f"Agente detectó fuera de dominio para: {query[:30]}...")
                reply = "ERROR_DOMINIO"
            # -----------------------------------------------------

        except Exception as e:
            logger.error(f"Error en backend de español: {e}")
            reply = "ERROR_DOMINIO" # Forzamos re-clasificación si el backend cae

        # CONSTRUIR RESPUESTA OFP
        now = datetime.utcnow()
        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": SPEAKER_URI},
                "events": [
                    {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": SPEAKER_URI,
                                "span": {
                                    "startTime": now.isoformat()+"Z", 
                                    "endTime": (now+timedelta(seconds=2)).isoformat()+"Z"
                                },
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
        return jsonify(payload)

    except Exception as e:
        logger.error(f"Error en wrapper Español: {e}")
        return jsonify({"error": str(e)}), 500

        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5015)