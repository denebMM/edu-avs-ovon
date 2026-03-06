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
        Clasifica SOLO con UNA palabra exacta: alice, physics,history,translator,mathbuddy, none.

        Reglas muy estrictas (elige la PRIMERA que aplique):

        - alice → CUALQUIER cosa que no sea matemáticas puras o física pura o historia. Incluye:
        conversación general, saludos, chistes, opiniones, preguntas personales, filosofía, IA/chatbots/ALICE/AIML/robots/historia de IA,
        tecnología conversacional, conocimiento general, política, ideologías,
        comunismo, capitalismo, revoluciones, partidos políticos, geografía, literatura,
        música, cine, arte, religión, mitología, mitos urbanos, economía básica, psicología,
        comportamiento humano, ética, moral, sueños, futuro de la humanidad, etc.

        - physics → SOLO física: movimiento, fuerzas, energía, gravedad, leyes de Newton,
        velocidad, aceleración, electricidad, óptica, termodinámica, incluso si usa ecuaciones simples.

        - history → Preguntas sobre HISTORIA: eventos históricos, revoluciones, guerras, figuras históricas, historia de México, independencia, revolución mexicana, reyes, imperios, batallas, etc.

        - translator → Preguntas explícitas de TRADUCCIÓN, gramática de idiomas, "traduce al ...", "cómo se dice ... en ...", corrección de frases en otro idioma, aprendizaje de vocabulario/expresiones.  
        
        - mathbuddy → Preguntas de matemáticas que necesiten tutor paso a paso detallado, explicaciones educativas, resolución de problemas con ejemplos, desde aritmética hasta cálculo. Incluye: "explica paso a paso", "cómo resolver", "tutor matemáticas", etc.
        
        - none → SOLO temas muy específicos que ninguno de los asistentes cubre:
        química avanzada, biología molecular, idiomas (traducción/gramática), programación (no bots),
        finanzas/bolsa, derecho/leyes específicas, medicina/enfermedades, noticias actuales,
        deportes profesionales, cocina/recetas detalladas, astrología seria, religión profunda,
        cualquier tema técnico o académico muy especializado fuera de math/physics/IA/conversación.

        Ejemplos claros:
        - "Hola, ¿cómo estás?" → alice
        - "HAVE YOU READ THE COMMUNIST" → alice
        - "Qué opinas del comunismo" → alice
        - "Quién creó AIML" → alice       
        - "Qué es la ley de Newton" → physics
        - "Qué es la fotosíntesis" → none
        - "Traducción al inglés de hola" → none
        - "Cuánto cuesta el dólar hoy" → none
        - "Historia de la Revolución Mexicana" → alice
        - "Traduce 'hola mundo' al japonés" → translator
        - "Cómo se dice gracias en francés" → translator
        - "Corrige esta frase en inglés: I goed to school" → translator
        - "Traducción de este párrafo: ..." → translator
        - "Resuelve 2x + 5 = 13 paso a paso" → mathbuddy
        - "Explica qué es una derivada con ejemplos" → mathbuddy
        - "Ayúdame con álgebra básica" → mathbuddy

        Pregunta: {user_query}

        Respuesta (SOLO una de estas palabras, nada más):
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
    final_reply = "No corresponde a matemáticas, a física, o historia, ni conocimiento de ALice ."  # default fallback

    if intent == 'alice':
        resp = send_ovon_event(AGENTS["alice"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)    

    elif intent == 'physics':
        resp = send_ovon_event(AGENTS["physics"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)
    
    elif intent == 'history':
        resp = send_ovon_event(AGENTS["history"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    elif intent == 'translator':
        resp = send_ovon_event(AGENTS["translator"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)    

    elif intent == 'mathbuddy':
        resp = send_ovon_event(AGENTS["mathbuddy"], utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)    

    elif intent == 'none':
        final_reply = "Lo siento, ninguno de los asistentes actuales puede responder esta pregunta (química, economía, historia, idiomas, etc.). ¿Quieres intentar con otra pregunta?"

    else:
        final_reply = "No entendí intenta de nuevo."
        
    return jsonify({
        "reply": final_reply,
        "classified_as": intent,
        "conversation_id": conversation_id
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

