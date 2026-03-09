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
        
        agent_name = "unknown"
        for name, agent_url in AGENTS.items():
            if agent_url == url:
                agent_name = name
                break
        
        resp_json = response.json()
        
        # Logging para cuando recibe respuesta de cada agente
        print(f"{Fore.GREEN}[ORCHESTRADOR] ← Respuesta de {agent_name}:{Style.RESET_ALL}")
        print(json.dumps(resp_json, indent=2, ensure_ascii=False))
        print(f"{Fore.GREEN}----------------------------------------{Style.RESET_ALL}")
        
        return resp_json
    
    except Exception as e:
        print(f"{Fore.RED}[ERROR] enviando a {url}: {e}{Style.RESET_ALL}")
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
        # Caso multi-AV: Intentamos dividir la query en subtareas secuenciales
        responses = []

    # 1. Si hay "traduce" → siempre primero translator
    if "translator" in intents:
        # Enviamos SOLO la parte que necesita traducción
        translate_prompt = f"Traduce SOLO la siguiente pregunta o texto al idioma indicado (sin explicaciones extras): {user_query}"
        resp_trans = send_ovon_event(AGENTS["translator"], [{
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": "tag:user.local,2026:user001",
                    "features": {"text": {"tokens": [{"value": translate_prompt}]}}
                }
            }
        }], conversation_id)
        translated_text = extract_reply_from_ovon(resp_trans)
        responses.append(translated_text)
        print(f"{Fore.GREEN}Traducción obtenida: {translated_text}{Style.RESET_ALL}")

        # 2. Luego el resto (physics, mathbuddy, etc.)
        remaining_intents = [i for i in intents if i != "translator"]
        for agent_key in remaining_intents:
            if agent_key in AGENTS:
                # Enviamos la query original o la traducida si existe
                query_to_send = translated_text if "translator" in intents else user_query
                resp = send_ovon_event(AGENTS[agent_key], utterance_event, conversation_id)  # o con query_to_send
                reply = extract_reply_from_ovon(resp)
                responses.append(reply)

    # Logging antes de sintetizar (ya lo tienes)
    if responses:
        print(f"{Fore.YELLOW}=== RESPUESTAS RECOLECTADAS ANTES DE SINTETIZAR ==={Style.RESET_ALL}")
        print(f"Número de respuestas: {len(responses)}")
        for i, resp in enumerate(responses, 1):
            print(f"[{i}] {resp[:300]}{'...' if len(resp) > 300 else ''}")
            print("-" * 80)

                # Sintetiza respuestas con Ollama
        if responses:
            synth_prompt = f"""Tienes respuestas de varios asistentes educativos. Tu tarea es combinarlas en UNA SOLA RESPUESTA coherente, completa y bien organizada.

            REGLAS OBLIGATORIAS:
            1. Respeta SIEMPRE el orden lógico de la pregunta original:
            - Si la pregunta empieza con "Traduce al [idioma]" → pon PRIMERO la traducción literal.
            - Luego pon la explicación o respuesta del otro agente.
            2. Nunca omitas ninguna respuesta. Incluye TODA la información clave de cada una.
            3. Usa el idioma que pida la pregunta:
            - Si dice "traduce al inglés", la explicación también debe ir en inglés (no en español).
            - Si no especifica idioma, responde en español.
            4. Estructura clara: usa encabezados como "Traducción:" y "Explicación:" cuando corresponda.
            5. Sé conciso pero completo. No agregues información inventada.

            Respuestas recibidas (en orden de llegada, NO las ignores):
            {json.dumps(responses, ensure_ascii=False, indent=2)}

            Responde ahora siguiendo estas reglas estrictas:"""

            synth_response = ollama_client.chat(
                model='gemma2:2b',
                messages=[{'role': 'user', 'content': synth_prompt}],
                options={
                    "temperature": 0.2,
                    "num_predict": 800,  # ← Aumentado para respuestas largas
                    "top_k": 10,
                    "top_p": 0.9,
                    "num_ctx": 2048      # ← Más contexto para ver todo el prompt
                }
            )
            final_reply = synth_response['message']['content'].strip()

            # Fallback si síntesis falla
            if len(final_reply) < 50 or "no" in final_reply.lower()[:20]:
                final_reply = "\n\n".join(responses)
                print(f"{Fore.RED}Síntesis falló → usando concatenación simple{Style.RESET_ALL}")
        else:
            final_reply = "Error en colaboración multi-AV."
        
    return jsonify({
        "reply": final_reply,
        "collaborators": intents,  # Lista de asistentes que colaboraron (clasificados)
        "conversation_id": conversation_id
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)