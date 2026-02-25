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
    "math": "http://assistant_math:5001/receive",
    "physics": "http://assistant_physics:5002/receive",
    "rits": "http://rits_math:5003/receive"
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

            elif event_type == 'yield_floor':
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
    prompt = f"""
    Clasifica SOLO con UNA palabra exacta: math, physics, rits, other.
    NUNCA uses 'both' a menos que la pregunta mencione explícitamente conceptos de física Y matemáticas avanzadas al mismo tiempo.

    Reglas estrictas:
    - math: ecuaciones, álgebra, resolver variables, fracciones conceptuales, cálculo
    - physics: movimiento, fuerzas, energía, leyes de Newton, gravedad, velocidad (incluso si usa ecuaciones simples)
    - rits: operaciones aritméticas puras con fracciones (suma/resta/etc. sin variables)
    - other: todo lo demás

    Si es solo resolver ecuación simple → math (NO both).

    Pregunta: {user_query}

    Respuesta (solo la palabra):
    """

    intent_response = ollama_client.chat(
        model='gemma2:2b',
        messages=[{'role': 'user', 'content': prompt}],
        options={
            "temperature": 0.0,
            "num_predict": 10,
            "top_k": 5,
            "top_p": 0.8,
            "num_ctx": 512,
            "num_thread": 0,
            "num_gpu": -1
        }
    )

    intent = intent_response['message']['content'].strip().lower()
    print(f"{Fore.YELLOW}Clasificado como → {intent}{Style.RESET_ALL}")

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
    # ROUTING SIMPLE
    # ===============================
    final_reply = "No corresponde a matemáticas ni física."  # default fallback

    if intent == 'rits':
        resp = send_ovon_event(AGENTS["rits"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    elif intent == 'math':
        resp = send_ovon_event(AGENTS["math"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    elif intent == 'physics':
        resp = send_ovon_event(AGENTS["physics"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    elif intent == 'both':
        try:
            # Envía a ambos en paralelo
            math_resp = send_ovon_event(AGENTS["math"], utterance_event, conversation_id)
            physics_resp = send_ovon_event(AGENTS["physics"], utterance_event, conversation_id)

            math_text = extract_reply_from_ovon(math_resp)
            physics_text = extract_reply_from_ovon(physics_resp)

            # Prompt de síntesis pedagógica
            synthesis_prompt = f"""
            Combina estas dos respuestas en una sola explicación coherente, clara y pedagógica para un estudiante de secundaria o bachillerato.
            No repitas información innecesaria. Integra los aspectos matemáticos y físicos de forma natural y fluida.
            Usa un lenguaje sencillo, evita tecnicismos excesivos y explica paso a paso cuando sea necesario.
            La respuesta final debe ser una sola narración unificada, no separada en secciones.

            Respuesta del asistente de Matemáticas:
            {math_text}

            Respuesta del asistente de Física:
            {physics_text}

            Respuesta unificada final:
            """

            # Llama a Ollama para sintetizar (modelo pequeño y rápido)
            synthesis_response = ollama_client.chat(
                model='gemma2:2b',  # puedes cambiar a 'llama3.2:1b' si quieres más velocidad
                messages=[{'role': 'user', 'content': synthesis_prompt}],
                options={
                    "temperature": 0.3,
                    "num_predict": 600,
                    "top_k": 20,
                    "top_p": 0.85,
                    "num_ctx": 2048,
                    "num_gpu": -1
                }
            )

            final_reply = synthesis_response['message']['content'].strip()

            # Fallback si síntesis vacía o muy corta
            if not final_reply or len(final_reply) < 50:
                final_reply = f"**Respuesta combinada (síntesis incompleta):**\n\n**Matemáticas:**\n{math_text}\n\n**Física:**\n{physics_text}"

        except Exception as e:
            app.logger.error(f"Error en síntesis Ollama para 'both': {e}")
            # Fallback seguro: concatenación simple
            final_reply = f"**Matemáticas:**\n{math_text}\n\n**Física:**\n{physics_text}"

    return jsonify({
        "reply": final_reply,
        "classified_as": intent,
        "conversation_id": conversation_id
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

