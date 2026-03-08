from flask import Flask, request, jsonify
import requests
import uuid
from datetime import datetime
import jsonschema  # pip install jsonschema
import ollama
import os
import json
from colorama import Fore, Style

app = Flask(__name__)

OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

AGENTS = {
    "physics": "http://assistant_physics:5002/receive",    
    "alice": "http://assistant_alice:5005/receive",
    "history": "http://assistant_history:5003/receive",
    "translator": "http://assistant_translator:5010/receive",
    "mathbuddy": "http://assistant_mathbuddy:5011/receive"
}

ORCHESTRATOR_URL = "http://orchestrator:5000/receive"
ORCHESTRATOR_SPEAKER_URI = "tag:orchestrator.local,2026:orch001"

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
            "sender": {
                "speakerUri": ORCHESTRATOR_SPEAKER_URI
            },
            "events": events
        }
    }

def send_ovon_event(url, events, conversation_id=None):
    try:
        payload = create_openfloor_envelope(events, conversation_id)
        response = requests.post(url, json=payload, timeout=180, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        app.logger.error(f"Error enviando OFP a {url}: {e}")
        return {"openFloor": {"events": [], "error": str(e)}}

def extract_reply_from_ovon(response):
    try:
        events = response.get("openFloor", {}).get("events", [])
        for event in events:
            if event.get("eventType") == "utterance":
                dialog = event.get("parameters", {}).get("dialogEvent", {})
                tokens = dialog.get("features", {}).get("text", {}).get("tokens", [])
                if tokens:
                    return tokens[0].get("value", "Sin respuesta")
        return "Sin respuesta"
    except Exception:
        return "Error procesando respuesta"

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": ORCHESTRATOR_URL, "speakerUri": ORCHESTRATOR_SPEAKER_URI},
                        "role": "Orquestador",
                        "name": "EduOrch",
                        "description": "Coordina colaboración entre AVs educativos usando OFP.",
                        "keywords": ["orquestador", "interoperabilidad", "educación"],
                        "languages": ["es", "en"],
                        "modalities": ["text"],
                        "capabilities": ["delegation", "floor-management", "context-maintenance"]
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
        validate_envelope(data)
        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        responses = []
        for event in events:
            event_type = event.get('eventType')
            if event_type == 'getManifests':
                manifest_response = get_manifest()
                if conversation_id:
                    manifest_response['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(manifest_response)

            elif event_type == 'utterance':
                # Procesar respuesta de AV (guardar contexto si lo necesitas)
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Respuesta recibida"}
                })

            elif event_type == 'request_delegation':
                responses.append({
                    "eventType": "accept_delegation",
                    "parameters": {"reason": "Aceptado por orquestador"}
                })

            elif event_type == 'transfer_control':
                # Ejemplo: acepta transferencia de control
                responses.append({
                    "eventType": "accept_transfer_control",
                    "parameters": {"reason": "Control transferido aceptado"}
                })

            elif event_type == 'yieldFloor':
                # Ejemplo: confirma que el piso fue cedido
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": "Piso conversacional cedido recibido"}
                })
            else:
                responses.append({
                    "eventType": "error",
                    "parameters": {"message": f"Evento no soportado: {event_type}"}
                })

        response_payload = create_openfloor_envelope(responses, conversation_id)
        return jsonify(response_payload)
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/query', methods=['POST'])
def handle_query():
    print(f"{Fore.CYAN}[ORCHESTRADOR] ← Pregunta recibida{Style.RESET_ALL}")

    data = request.get_json()
    user_query = data.get('query')

    if not user_query or not isinstance(user_query, str):
        return jsonify({"error": "Falta 'query'"}), 400

    # ===============================
    # CLASIFICACIÓN SOLO LLM (LIMPIO)
    # ===============================
    prompt = f"""Clasifica la siguiente pregunta en EXACTAMENTE una o más de estas categorías (separadas por coma si son varias, máximo 3). 
            Solo responde con las palabras exactas de la lista, sin nada más, sin explicaciones, sin puntuación extra.

            Categorías válidas: alice, physics, history, translator, mathbuddy, none

            Reglas (elige la primera que aplique):

            - mathbuddy → cualquier cálculo, ecuación, logaritmo, derivada, integral, álgebra, geometría, trigonometría, "resuelve", "calcula", "valor de", "explica paso a paso matemáticas"

            - physics → física, gravedad, órbita, movimiento, fuerzas, leyes de Newton, satélite, caída libre, energía, electricidad, óptica

            - history → historia, guerras, revoluciones, figuras históricas, independencia, batallas

            - translator → traduce, traducción, idioma, gramática, corrige frase, cómo se dice en, vocabulario

            - alice → conversación general, saludos, opiniones, chistes, filosofía, preguntas personales, todo lo que no encaje en las anteriores

            - none → química, biología, programación, economía, deportes, noticias, temas avanzados fuera de scope

            Pregunta: {user_query}

            Respuesta (SOLO categorías separadas por coma, ejemplo: mathbuddy o physics,translator o none):"""

    intent_response = ollama_client.chat(
        model='gemma2:2b',
        messages=[{'role': 'user', 'content': prompt}],
        options={
            "temperature": 0.0,
            "num_predict": 30,          # ← ¡Sube esto! 20-40 es mucho más seguro
            "top_k": 5,
            "top_p": 0.8,
            "num_ctx": 1024,            # ← Aumenta contexto para que vea todo el prompt
            "num_thread": 0,
            "num_gpu": -1
        }
    )

    intent = intent_response['message']['content'].strip().lower()
    print(f"{Fore.YELLOW}Clasificado como → {intent}{Style.RESET_ALL}")

    intents = [i.strip() for i in intent.split(',')]  # Divide en lista para manejar multi-clasificación

    conversation_id = str(uuid.uuid4())

    # ===============================
    # EVENTO OFP (utterance común para todos)
    # ===============================
    utterance_event = [{
        "eventType": "utterance",
        "parameters": {
            "dialogEvent": {
                "speakerUri": "tag:user.local,2026:user001",
                "span": {
                    "startTime": datetime.utcnow().isoformat() + "Z",
                    "endTime": datetime.utcnow().isoformat() + "Z"
                },
                "features": {
                    "text": {
                        "mimeType": "text/plain",
                        "tokens": [{"value": user_query}]
                    }
                }
            }
        }
    }]

    # ===============================
    # ROUTING AVANZADO CON SOPORTE PARA MULTI-AV
    # ===============================
    final_reply = "Lo siento, ninguno de los asistentes actuales puede responder esta pregunta."  # Default fallback

    if 'none' in intents:
        final_reply = "Lo siento, ninguno de los asistentes actuales puede responder esta pregunta (química, economía, historia profunda, etc.). ¿Quieres intentar con otra pregunta?"
    elif len(intents) == 1:
        # Caso single-AV: Envío directo al agente clasificado
        agent_key = intents[0]
        if agent_key in AGENTS:
            resp = send_ovon_event(AGENTS[agent_key], utterance_event, conversation_id)
            final_reply = extract_reply_from_ovon(resp)
        else:
            final_reply = "No entendí, intenta de nuevo."
    else:
        # Caso multi-AV: Envío secuencial (principal primero, delega a secundarios)
        responses = []
        primary_agent = intents[0]  # Primero es principal
        if primary_agent in AGENTS:
            # Envía a principal
            resp_primary = send_ovon_event(AGENTS[primary_agent], utterance_event, conversation_id)
            responses.append(extract_reply_from_ovon(resp_primary))
            
            # Para cada secundario, simula delegación: Crea evento de delegation y envía
            for secondary in intents[1:]:
                if secondary in AGENTS:
                    # Crea evento OFP para delegation (adaptado a tu schema)
                    delegation_event = [{
                        "eventType": "request_delegation",
                        "parameters": {
                            "delegateTo": AGENTS[secondary],  # O usa speakerUri si lo tienes
                            "query": user_query  # Pasa la query o subparte
                        }
                    }]
                    resp_sec = send_ovon_event(AGENTS[secondary], delegation_event + utterance_event, conversation_id)
                    responses.append(extract_reply_from_ovon(resp_sec))
      
        # Sintetiza respuestas con Ollama (en lugar de concatenación simple)
        if responses:
            synth_prompt = f"Une estas respuestas individuales de asistentes en una respuesta coherente y unificada, manteniendo la información clave de cada una. Respuestas: {json.dumps(responses)}"
            synth_response = ollama_client.chat(
                model='gemma2:2b',
                messages=[{'role': 'user', 'content': synth_prompt}],
                options={
                    "temperature": 0.2,  # Baja para coherencia
                    "num_predict": 200,  # Ajusta según longitud esperada
                    "top_k": 10,
                    "top_p": 0.9,
                    "num_ctx": 1024
                }
            )
            final_reply = synth_response['message']['content'].strip()
        else:
            final_reply = "Error en colaboración multi-AV."
        
    return jsonify({
        "reply": final_reply,
        "collaborators": intents,  # Lista de asistentes que colaboraron (clasificados)
        "conversation_id": conversation_id
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)