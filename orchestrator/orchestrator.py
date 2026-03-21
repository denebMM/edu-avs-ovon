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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

AGENTS = {
    "physics": "http://assistant_physics:5002/receive",
    "alice": "http://assistant_alice:5005/receive",
    "history": "http://assistant_history:5003/receive",
    "translator": "http://assistant_translator:5010/receive",
    "mathbuddy_avanzado": "http://assistant_mathbuddy_avanzado:5011/receive",
    "mathbuddy_basico": "http://assistant_mathbuddy_basico:5012/receive"
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
        payload = create_openfloor_envelope(events, conversation_id)
        response = requests.post(url, json=payload, timeout=180, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        
        agent_name = next((name for name, u in AGENTS.items() if u == url), "unknown")
        logger.info(f"[ORCHESTRADOR] ← Respuesta de {agent_name}")
        print(f"{Fore.GREEN}[ORCHESTRADOR] ← Respuesta de {agent_name}:{Style.RESET_ALL}")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        print(f"{Fore.GREEN}----------------------------------------{Style.RESET_ALL}")
        
        return response.json()
    except Exception as e:
        logger.error(f"[ERROR] enviando a {url}: {e}")
        print(f"{Fore.RED}[ERROR] enviando a {url}: {e}{Style.RESET_ALL}")
        return {"openFloor": {"events": [], "error": str(e)}}

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
    logger.info("[ORCHESTRADOR] ← Pregunta recibida")
    print(f"{Fore.CYAN}[ORCHESTRADOR] ← Pregunta recibida{Style.RESET_ALL}")
    data = request.get_json()
    user_query = data.get('query')

    if not user_query or not isinstance(user_query, str):
        return jsonify({"error": "Falta 'query'"}), 400

    # === INICIO DE MEDICIÓN DE TIEMPO PARA MÉTRICAS ===
    start_time = time.time()  # Marca el inicio del procesamiento completo    

    # 1. Clasificación
    classification_prompt = f"""Clasifica esta pregunta en UNA O MÁS categorías (separadas por coma, máximo 3): 
    alice, physics, history, translator, mathbuddy_basico, mathbuddy_avanzado, none.

    REGLAS OBLIGATORIAS (en este orden):
    1. TRADUCCIÓN: Si hay "traduce", "traducción", "translate", "al [idioma]", "to [language]", "explica en", "responde en" → INCLUYE SIEMPRE "translator".

    2. MATEMÁTICAS BÁSICAS: primaria/secundaria baja (sumas, restas, fracciones simples, porcentajes, ecuaciones lineales básicas, geometría elemental) → mathbuddy_basico.

    3. MATEMÁTICAS AVANZADAS: secundaria alta hasta Cálculo 1 (álgebra intermedia, trigonometría, funciones, límites, derivadas, integrales básicas, ecuaciones cuadráticas, logaritmos) → mathbuddy_avanzado.
    - Mezcla básico y avanzado → incluye ambos.

    4. FÍSICA: SI menciona conceptos físicos centrales (leyes de Newton, energía cinética, gravedad, movimiento de objetos, fuerzas, órbitas, colisiones, teoría de cuerdas, qué es la energía cinética, qué son las leyes de Newton) → physics.
    - Derivadas, pendientes, funciones o fórmulas SOLAS sin contexto físico real → mathbuddy_avanzado, NO physics.

    5. HISTORIA: guerras, revoluciones, imperios, eventos pasados → history.

    6. GENERAL: conversación, chistes, opiniones → alice.

    7. NADA → none.

    IMPORTANTE:
    - NUNCA clasifiques como mathbuddy_basico o mathbuddy_avanzado si es "explica las leyes de Newton" o "qué es la energía cinética" → SIEMPRE physics.
    - Prioriza translator si hay instrucción de idioma.
    - NUNCA pongas physics solo por fórmulas o "energía cinética" sin aplicación real, pero SI es "qué es la energía cinética" → physics.

    Pregunta: {user_query}

    Responde SOLO con las categorías, SEPARADAS por coma, sin explicación ni texto extra."""
    
    intent_response = ollama_client.chat(
        model='llama3.1:8b',
        messages=[{'role': 'user', 'content': classification_prompt}],
        options={"temperature": 0.0, "num_predict": 60}
    )
    
    intent_text = intent_response['message']['content'].strip().lower()
    logger.info(f"Clasificado como → {intent_text}")
    print(f"{Fore.YELLOW}Clasificado como → {intent_text}{Style.RESET_ALL}")
    
    intents = [i.strip() for i in intent_text.split(',') if i.strip() in AGENTS or i.strip() == 'none']
    if not intents:
        intents = ['alice']

    conversation_id = str(uuid.uuid4())
    responses_map = {}

    # Detectar idioma objetivo (más idiomas)
    idioma_objetivo = "español"
    for lang in ["inglés", "francés", "chino", "japonés", "alemán", "italiano", "portugués", "ruso"]:
        if f"traduce al {lang}" in user_query.lower() or f"explícala en {lang}" in user_query.lower():
            idioma_objetivo = lang
            break
    logger.info(f"Idioma objetivo: {idioma_objetivo}")
    print(f"{Fore.MAGENTA}Idioma objetivo: {idioma_objetivo}{Style.RESET_ALL}")

    # Extraer pregunta real (más robusto)
    pregunta_real = user_query.strip()
    pregunta_original_para_trad = user_query
    hay_traduccion = any(palabra in user_query.lower() for palabra in [
        "traduce al", "traducción al", "translate to", "traduce a", "traducción a",
        "al inglés", "al francés", "al italiano", "al portugués", "al alemán", "al chino"
    ])

    if hay_traduccion:
        separadores = [": ", " : ", "la siguiente: ", "la pregunta: ", "esta pregunta: ", "traduce ", "traducción ", "explica en ", "responde en "]
        for sep in separadores:
            if sep in user_query:
                partes = user_query.split(sep, 1)
                if len(partes) > 1:
                    pregunta_real = partes[1].strip()
                    break
        pregunta_real = pregunta_real.strip(' "¿¡?.,:;').strip()
        logger.info(f"Pregunta real extraída: {pregunta_real}")
        print(f"{Fore.CYAN}Pregunta real extraída: {pregunta_real}{Style.RESET_ALL}")

    current_text = pregunta_real

    # 2. Ejecutar agentes expertos
    expert_results = []
    remaining_intents = [i for i in intents if i not in ["translator", "alice", "none"]]
    previous_reply = ""

    for idx, agent_key in enumerate(remaining_intents):
        if agent_key in AGENTS:
            text_to_expert = current_text
            if previous_reply:
                text_to_expert = f"Pregunta del usuario: {current_text}\n\nContexto adicional del asistente anterior ({remaining_intents[idx-1]}): {previous_reply}"

            resp = send_ovon_event(AGENTS[agent_key], create_utterance_event(text_to_expert), conversation_id)
            reply = extract_reply_from_ovon(resp)

            if "no es de mi área" in reply.lower() or "no es de mi área" in reply.lower():
                logger.info(f"{agent_key.capitalize()} rechazó: {reply}")
                print(f"{Fore.RED}{agent_key.capitalize()} rechazó: {reply}{Style.RESET_ALL}")
                continue

            responses_map[agent_key] = reply
            expert_results.append(f"[{agent_key.upper()}]: {reply}")
            previous_reply = reply
            logger.info(f"{agent_key.capitalize()} respondió: {reply[:150]}...")
            print(f"{Fore.GREEN}{agent_key.capitalize()} respondió: {reply[:150]}...{Style.RESET_ALL}")

    # Chaining simple entre mathbuddy_basico y mathbuddy_avanzado (opcional pero útil)
    if "mathbuddy_basico" in intents and "mathbuddy_avanzado" in intents:
        reply_basico = responses_map.get("mathbuddy_basico", "")
        if reply_basico:
            text_avanzado = f"Explicación básica recibida:\n{reply_basico}\n\nAhora responde la parte avanzada de la pregunta original: {user_query}"
            resp_avanzado = send_ovon_event(AGENTS["mathbuddy_avanzado"], create_utterance_event(text_avanzado), conversation_id)
            reply_avanzado = extract_reply_from_ovon(resp_avanzado)
            if "no es de mi área" not in reply_avanzado.lower():
                responses_map["mathbuddy_avanzado"] = reply_avanzado
                expert_results.append(f"[MATHBUDDY-AVANZADO]: {reply_avanzado}")
                logger.info("Chaining básico → avanzado completado")

    # 3. Contexto completo para traductor
    contexto_para_traductor = f"Pregunta original: {pregunta_original_para_trad}\n\nRespuestas de expertos:\n" + "\n\n".join(expert_results)
    if not expert_results:
        contexto_para_traductor += "\n(No se obtuvo respuesta de expertos)"

    # 4. Traducción final
    final_reply = contexto_para_traductor if contexto_para_traductor else "No pude encontrar una respuesta específica."
    if "translator" in intents and hay_traduccion and idioma_objetivo != "español":
        contenido_a_traducir = contexto_para_traductor
        trans_final_prompt = f"Traduce TODO este texto al {idioma_objetivo}:\n\n{contenido_a_traducir}"
        
        resp_final = send_ovon_event(AGENTS["translator"], create_utterance_event(trans_final_prompt), conversation_id)
        traduccion_final = extract_reply_from_ovon(resp_final)
        responses_map["translator"] = traduccion_final
        final_reply = traduccion_final
        logger.info(f"Traducción final al {idioma_objetivo}: {traduccion_final[:150]}...")
        print(f"{Fore.GREEN}Traducción final al {idioma_objetivo}: {traduccion_final[:150]}...{Style.RESET_ALL}")

    # 5. Respuesta final en OFP completo
    response_payload = create_collaborative_response(responses_map, conversation_id)

    if responses_map:
        logger.info("=== RESPUESTAS FINALES (OFP) ===")
        print(f"{Fore.YELLOW}=== RESPUESTAS FINALES (OFP) ==={Style.RESET_ALL}")
        print(json.dumps(response_payload, indent=2, ensure_ascii=False))
    
    # === NUEVO: REGISTRO DE MÉTRICAS ===
    total_time = time.time() - start_time  # Calcula tiempo total

    try:
        from metrics.metrics_collector import MetricsCollector
        collector = MetricsCollector(storage_path="metrics")
        collector.record_query(
            query=user_query,
            intents=intents,
            responses_map=responses_map,
            final_envelope=response_payload,
            total_time=total_time
        )
        logger.info("Métricas registradas correctamente")
    except Exception as metrics_err:
        logger.error(f"Error al registrar métricas: {metrics_err}")
    # Fin del registro de métricas

    return jsonify(response_payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)