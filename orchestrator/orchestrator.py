from flask import Flask, request, jsonify
import requests
import uuid
from datetime import datetime
import jsonschema
import ollama
import os
import json
from colorama import Fore, Style
import logging
import time
from werkzeug.middleware.proxy_fix import ProxyFix # <--- ASEGÚRATE DE TENER ESTO


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Esto le dice a Flask que confíe en los headers que vienen del orquestador
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)


OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

AGENTS = {
    "physics": "http://assistant_physics:5002/receive",
    "alice": "http://assistant_alice:5005/receive",
    "history": "http://assistant_history:5003/receive",
    #"translator": "http://assistant_translator:5010/receive",
    "translator": "http://host.docker.internal:5010/receive",
    "mathbuddy_avanzado": "http://mathbuddy-avanzado-wrapper:5011/receive",  
    "mathbuddy_basico": "http://mathbuddy-basico-wrapper:5012/receive"
}

ORCHESTRATOR_URL = "http://orchestrator:5000/receive"
ORCHESTRATOR_SPEAKER_URI = "tag:orchestrator.local,2026:orch001"

SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"
try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"No se encontró el schema OFP en: {SCHEMA_PATH}")
except json.JSONDecodeError:
    raise ValueError("El archivo de schema OFP está corrupto o mal formado.")

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
            "sender": {"speakerUri": ORCHESTRATOR_SPEAKER_URI},
            "events": events
        }
    }

def create_collaborative_response(responses_map, conversation_id):
    events = []
    for agent, content in responses_map.items():
        speaker = f"tag:{agent}.local,2026:agent001"
        events.append({
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": speaker,
                    "features": {
                        "text": {
                            "mimeType": "text/plain",
                            "tokens": [{"value": content}]
                        }
                    }
                }
            }
        })

    events.append({"eventType": "yieldFloor", "parameters": {}})
    return create_openfloor_envelope(events, conversation_id)

def send_ovon_event(url, events, conversation_id=None):
    try:
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Construimos el payload OFP estándar. 
        # IMPORTANTE: 'events' debe ser una LISTA de objetos de evento.
        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id},
                "sender": {"speakerUri": ORCHESTRATOR_SPEAKER_URI},
                "events": events
            }
        }

        logger.info(f"[ORCHESTRADOR] → Enviando a {url} | Conv ID: {conversation_id[:8]}...")
        
        response = requests.post(
            url, 
            json=payload, 
            timeout=180, 
            headers={"Content-Type": "application/json"}
        )

        # Si el servidor responde 400, imprimimos el detalle del error para debugging
        if response.status_code == 400:
            logger.error(f"Fallo de validación en {url}: {response.text}")
        
        response.raise_for_status()

        agent_name = next((name for name, u in AGENTS.items() if u == url), "unknown")
        logger.info(f"[ORCHESTRADOR] ← Respuesta recibida de {agent_name}")
        
        # Opcional: Imprimir en consola con color para pruebas manuales
        print(f"{Fore.GREEN}← Respuesta de {agent_name}:{Style.RESET_ALL}")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        
        return response.json()

    except Exception as e:
        logger.error(f"[ERROR] en comunicación con {url}: {e}")
        return {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": conversation_id},
                "events": [{"eventType": "error", "parameters": {"message": str(e)}}]
            }
        }
def extract_reply_from_ovon(response):
    try:
        events = response.get("openFloor", {}).get("events", [])
        for event in events:
            if event.get("eventType") == "utterance":
                tokens = event.get("parameters", {}).get("dialogEvent", {}).get("features", {}).get("text", {}).get("tokens", [])
                if tokens:
                    return tokens[0].get("value", "Sin respuesta")
        return "Sin respuesta"
    except Exception:
        return "Error procesando respuesta"

def create_utterance_event(text):
    now = datetime.utcnow().isoformat() + "Z"
    return [{
        "eventType": "utterance",
        "parameters": {
            "dialogEvent": {
                "speakerUri": "tag:user.local,2026:user001",
                "span": {"startTime": now, "endTime": now},
                "features": {
                    "text": {
                        "mimeType": "text/plain",
                        "tokens": [{"value": text}]
                    }
                }
            }
        }
    }]

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

            elif event_type in ['utterance', 'request_delegation', 'transfer_control', 'yieldFloor']:
                responses.append({
                    "eventType": "ack",
                    "parameters": {"message": f"Evento {event_type} recibido"}
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
    logger.info("[ORCHESTRADOR] ← Nueva consulta recibida")
    print(f"{Fore.CYAN}[ORCHESTRADOR] ← Procesando...{Style.RESET_ALL}")
    
    start_time = time.time()
    data = request.get_json()
    user_query = data.get('query')

    if not user_query or not isinstance(user_query, str):
        return jsonify({"error": "Falta el campo 'query' en el JSON"}), 400

    # ====================== CLASIFICACIÓN MEJORADA ======================
    classification_prompt = f"""Analiza la consulta del usuario y responde **ÚNICAMENTE** con un objeto JSON válido.

{{
  "intents": ["lista", "de", "agentes"],
  "idioma_objetivo": "español | inglés | francés | otro",
  "requiere_traduccion": true/false,
  "orden_ejecucion": ["agente1", "agente2", ...]
}}

Agentes disponibles: physics, history, mathbuddy_basico, mathbuddy_avanzado, alice, translator.

REGLAS ESTRICTAS (prioridad alta a baja):

1. TRADUCCIÓN: Si la consulta contiene "traduce", "traducción", "translate", "al inglés", "to english", "al francés", "en inglés", etc. → 
   - "requiere_traduccion": true
   - "intents" debe incluir "translator"
   - "orden_ejecucion" debe terminar con "translator"

2. FÍSICA (physics): Úsalo para CUALQUIER consulta de ciencias físicas de nivel escolar (9º-10º grado). 
   - Debe ser el PRIMERO en el orden si la pregunta es teórica o menciona científicos (ej. "Bose", "Newton", "Einstein").
   - Es el encargado de extraer conceptos del libro (RAG). Si la pregunta es "¿Quién es Bose?", DEBE ir a physics, no a alice.

3. MATEMÁTICAS: 
   - Básico (sumas, fracciones simples, porcentajes) → mathbuddy_basico
   - Avanzado (derivadas, funciones, límites) → mathbuddy_avanzado
   - Mezcla → incluye ambos en orden lógico (básico primero)
   - CRITERIO DE DISTINCIÓN: Clasifica como 'physics' ÚNICAMENTE si la consulta menciona explícitamente conceptos de la naturaleza o mecánica como: fuerza, masa, gravedad, velocidad, circuitos, energía o leyes de Newton. 
   - PRIORIDAD: Ante cualquier fórmula matemática pura (sin contexto de leyes físicas), el sistema DEBE elegir un agente 'mathbuddy'.
 
4. ALICE:
   - Úsala ÚNICAMENTE para: Saludos, presentaciones ("¿quién eres?"), preguntas existenciales, bromas, cultura pop general o cuando el tema NO encaje en los expertos técnicos.
   - Alice es el "fallback": si la pregunta es de cocina o deportes, va a Alice.

Consulta: {user_query}

Responde SOLO el JSON, sin ningún texto adicional antes o después."""

    try:
        intent_response = ollama_client.chat(
            model='llama3.1:8b',
            format='json',
            messages=[{'role': 'user', 'content': classification_prompt}],
            options={"temperature": 0.0, "num_predict": 300}
        )
        decision = json.loads(intent_response['message']['content'].strip())
        intents = decision.get("intents", [])
        orden_ejecucion = decision.get("orden_ejecucion", ["alice"])
        requiere_traduccion = decision.get("requiere_traduccion", False)

        print(f"{Fore.MAGENTA}--- DECISIÓN DEL ORQUESTADOR ---{Style.RESET_ALL}")
        print(f"Intents detectados: {decision['intents']}")
        print(f"Orden de ejecución: {decision['orden_ejecucion']}")
        print(f"Traducción requerida: {decision['requiere_traduccion']}")
        print(f"{Fore.MAGENTA}-------------------------------{Style.RESET_ALL}")
    except Exception as e:
        logger.error(f"Error en clasificación: {e}")
        decision = {"intents": ["alice"], "orden_ejecucion": ["alice"], "requiere_traduccion": False}
        intents, orden_ejecucion, requiere_traduccion = ["alice"], ["alice"], False

   # ====================== EJECUCIÓN CON ENCADENAMIENTO ======================
    conversation_id = str(uuid.uuid4())
    responses_map = {}
    
    # 1. BUCLE DE EXPERTOS CON PASO DE CONTEXTO
    main_agents = [a for a in orden_ejecucion if a != "translator" and a in AGENTS]
    
    for agente_key in main_agents:
        print(f"{Fore.YELLOW}>> EJECUTANDO AGENTE: {agente_key.upper()}{Style.RESET_ALL}")
        # Preparamos el prompt base
        prompt_para_experto = user_query
        
        # --- LÓGICA DE COLABORACIÓN ESPECÍFICA PARA MATHBUDDY ---
        if agente_key == "mathbuddy_avanzado":
            # Si el básico ya respondió, le pasamos su aporte al avanzado
            if "mathbuddy_basico" in responses_map:
                aporte_basico = responses_map["mathbuddy_basico"]
                prompt_para_experto = f"[Aporte de mathbuddy_basico]: {aporte_basico}\n\nPregunta original: {user_query}"
                logger.info("--> Inyectando aporte básico al MathBuddy Avanzado")
        
        # --- LÓGICA PARA PHYSICS (Opcional, pero recomendada) ---
        if agente_key == "mathbuddy_avanzado" and "physics" in responses_map:
             aporte_fisica = responses_map["physics"]
             # Tu wrapper avanzado ya tiene una regla para "[Aporte de physics]"
             prompt_para_experto = f"[Aporte de physics]: {aporte_fisica}\n\n{prompt_para_experto}"


        # Enviamos el evento al wrapper correspondiente
        resp = send_ovon_event(
            AGENTS[agente_key], 
            create_utterance_event(prompt_para_experto), 
            conversation_id
        )
        
        reply = extract_reply_from_ovon(resp)
        # 
        if reply and reply != "Sin respuesta" and reply != "Error procesando respuesta":
            responses_map[agente_key] = reply
        # Guardamos la respuesta para mostrarla y para usarla como contexto del siguiente
        if "Sin respuesta" not in reply:
            responses_map[agente_key] = reply
            logger.info(f"✓ Respuesta de {agente_key} guardada en el mapa de contexto.")

    # 2. TRADUCCIÓN FINAL (AHORA FUERA DEL BUCLE FOR)
    if requiere_traduccion and "translator" in AGENTS:
        idioma_objetivo = decision.get("idioma_objetivo", "inglés").lower()
        solo_texto_crudo = "\n\n".join(responses_map.values())
        prompt_trans = f"Traduce fielmente al {idioma_objetivo}. NO añadas etiquetas ni nombres de asistentes, solo el contenido técnico: {solo_texto_crudo}"
        
        logger.info(f"[ORCHESTRADOR] -> Solicitando traducción al {idioma_objetivo}")

        # Estructura simplificada que funciona con tu Wrapper
        evento_traduccion = [{
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "features": {
                        "text": {
                            "tokens": [{"value": prompt_trans}]
                        }
                    }
                }
            }
        }]

        resp_trans = send_ovon_event(AGENTS["translator"], evento_traduccion, conversation_id)
        traduccion_final = extract_reply_from_ovon(resp_trans)
        
        if traduccion_final and "Sin respuesta" not in traduccion_final:
            responses_map["translator"] = traduccion_final
            logger.info("✓ Traducción añadida al mapa de respuestas")

    # 3. RESPUESTA FINAL (FUERA DEL BUCLE FOR)
    response_payload = create_collaborative_response(responses_map, conversation_id)

    # 4. Métricas y Retorno
    total_time = time.time() - start_time
    try:
        from metrics.metrics_collector import MetricsCollector
        collector = MetricsCollector(storage_path="metrics")
        collector.record_query(user_query, intents, responses_map, response_payload, total_time)
    except: pass

    return jsonify(response_payload)
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)