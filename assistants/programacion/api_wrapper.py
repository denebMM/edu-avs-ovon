from flask import Flask, request, jsonify
import requests
import json
import logging
import jsonschema
import time
from datetime import datetime, timedelta

# Configuración de logs profesionales
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

PROG_INTERNAL_URL = "http://programacion-backend:5000/preguntar" 
PROG_SPEAKER_URI = "tag:programacion.local,2026:agent001"
SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

# Carga del esquema OFP
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except Exception as e:
    logger.error(f"Error cargando esquema en programación: {e}")
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
                        "service": {"url": "http://assistant_programacion:5017/receive", "speakerUri": PROG_SPEAKER_URI},
                        "role": "Especialista en Programación",
                        "name": "ProgBot",
                        "description": "Agente experto en C++, lógica de programación y algoritmos.",
                        "languages": ["es"],
                        "capabilities": ["coding-advice", "cpp-logic"]
                    }
                }
            }]
        }
    })

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json() or {}
        # Validar entrada OFP
        if OFP_SCHEMA:
            jsonschema.validate(instance=data, schema=OFP_SCHEMA)

        openfloor = data.get('openFloor', {})
        conversation_id = openfloor.get('conversation', {}).get('id')
        events = openfloor.get('events', [])
        
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
            logger.info(f"Procesando consulta técnica: {query[:50]}...")
            start_t = time.time()
            resp = requests.post(PROG_INTERNAL_URL, json={"pregunta": query}, timeout=300)
            resp.raise_for_status()
            duration = time.time() - start_t
            logger.info(f"Análisis generado en {duration:.2f}s")
            
            backend_data = resp.json()
            reply = backend_data.get("respuesta", "").strip()
            
            # --- LÓGICA DE ERROR_DOMINIO IGNORADA SI HAY ORDEN ---
            # Cambiamos "relacionado" por "relacionad" para atrapar ambos géneros
            if not forzar_respuesta and (not reply or "no está relacionad" in reply.lower() or "error_dominio" in reply.lower()):
                logger.warning(f"Agente detectó fuera de dominio para: {query[:30]}...")
                reply = "ERROR_DOMINIO"
            # -----------------------------------------------------
        
        except Exception as e:
            logger.error(f"Error en backend de programación: {e}")
            reply = "ERROR_DOMINIO"

        # Empaquetado de respuesta OFP
        now = datetime.utcnow()
        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id} if conversation_id else {},
                "sender": {"speakerUri": PROG_SPEAKER_URI},
                "events": [
                    {
                        "eventType": "utterance",
                        "parameters": {
                            "dialogEvent": {
                                "speakerUri": PROG_SPEAKER_URI,
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
        logger.error(f"Error en wrapper Programación: {e}")
        return jsonify({"error": str(e)}), 500
        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5017)