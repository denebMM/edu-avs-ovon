from flask import Flask, request, jsonify
import requests
import json
import logging
import jsonschema
import time
from datetime import datetime, timedelta

# Configuración de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

HIST_INTERNAL_URL = "http://historia-backend:5000/preguntar" 
HIST_SPEAKER_URI = "tag:historia.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

# Carga de esquema OFP
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    logger.error(f"Fallo al cargar esquema: {e}")
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
    try:
        data = request.get_json() or {}
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
            start_t = time.time()
            resp = requests.post(HIST_INTERNAL_URL, json={"pregunta": query}, timeout=300)
            resp.raise_for_status()
            backend_data = resp.json()
            
            reply = backend_data.get("respuesta", "").strip()
            
            # --- LÓGICA DE ERROR_DOMINIO IGNORADA SI HAY ORDEN ---
            # Cambiamos "relacionado" por "relacionad" para atrapar ambos géneros
            if not forzar_respuesta and (not reply or "no está relacionad" in reply.lower() or "error_dominio" in reply.lower()):
                logger.warning(f"Agente detectó fuera de dominio para: {query[:30]}...")
                reply = "ERROR_DOMINIO"
            # -----------------------------------------------------

            duration = time.time() - start_t
            logger.info(f"Análisis histórico completado en {duration:.2f}s")
        
        except Exception as e:
            logger.error(f"Error en backend de historia: {e}")
            reply = "ERROR_DOMINIO"

        # CONSTRUIR RESPUESTA OFP
        now = datetime.utcnow()
        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": HIST_SPEAKER_URI},
                "events": [
                    {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": HIST_SPEAKER_URI,
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
        logger.error(f"Error en wrapper Historia: {e}")
        return jsonify({"error": str(e)}), 500
        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5016)