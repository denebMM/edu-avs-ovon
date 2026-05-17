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
from werkzeug.middleware.proxy_fix import ProxyFix 
import threading
import numpy as np

# ================= CONFIGURACIÓN DE LOGS Y FLASK =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

# ================= CONFIGURACIÓN OLLAMA =================
OLLAMA_HOST = "http://ollama:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)
MODELO_EMBEDDING = "mxbai-embed-large"

# ================= DEFINICIÓN DE AGENTES =================
AGENTS = {
    "fisica": "http://assistant_physics:5002/receive",
    "translator": "http://assistant_translator:5010/receive", 
    "mathbuddy_avanzado": "http://mathbuddy-avanzado-wrapper:5011/receive",  
    "mathbuddy_basico": "http://mathbuddy-basico-wrapper:5012/receive",
    "algebra": "http://assistant_algebra:5013/receive",
    "computacion": "http://assistant_computacion:5014/receive",
    "espanol": "http://assistant_espanol:5015/receive",
    "historia": "http://assistant_historia:5016/receive",
    "programacion": "http://assistant_programacion:5017/receive",
    "quimica": "http://assistant_quimica:5018/receive" 
}

# ================= DESCRIPCIONES SEMÁNTICAS (Para Embeddings) =================
AGENT_DESCRIPTIONS = {
    "fisica": "Leyes de la física, cinemática, dinámica, energía, leyes de Newton, relatividad y fenómenos naturales.",
    "mathbuddy_basico": "Aritmética básica, suma, resta, multiplicación, división, fracciones, porcentajes y ecuaciones de primer grado.",
    "mathbuddy_avanzado": "Cálculo diferencial e integral, límites, derivadas, funciones complejas y análisis matemático avanzado.",
    "algebra": "Factorización, polinomios, ecuaciones algebraicas, productos notables, matrices y expresiones algebraicas.",
    "computacion": "Hardware, software, arquitectura de computadoras, sistemas operativos, memoria RAM, CPU, ALU y periféricos.",
    "espanol": "Gramática, ortografía, reglas de acentuación, signos de puntuación, sintaxis y uso correcto del idioma español.",
    "historia": "Hechos históricos, biografías, Revolución Mexicana, guerras, imperios antiguos, fascismo y contextos sociopolíticos.",
    "programacion": "Lógica de programación, algoritmos, lenguaje C++, clases, objetos, punteros, herencia y memoria dinámica.",
    "quimica": "Tabla periódica, enlaces químicos (covalente, iónico), átomos, moléculas, estequiometría, ácidos, bases e isótopos.",
    "translator": "Traducción de textos, cambio de idioma, inglés, francés, alemán, portugués, italiano y japonés."
}

# Caché global para los vectores
AGENT_EMBEDDINGS = {}

# ================= FUNCIONES CORE DE EMBEDDINGS =================
def get_embedding(text):
    """Genera un vector numérico a partir de un texto usando Ollama."""
    try:
        response = ollama_client.embeddings(model=MODELO_EMBEDDING, prompt=text)
        return response['embedding']
    except Exception as e:
        logger.error(f"Error generando embedding: {e}")
        return None

def cosine_similarity(v1, v2):
    """Calcula la similitud entre dos vectores (0 a 1)."""
    if v1 is None or v2 is None: return 0.0
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0: return 0.0
    return dot_product / (norm_v1 * norm_v2)

def load_embeddings_if_needed():
    """Carga los embeddings en memoria solo si no se han cargado antes (Lazy Loading)."""
    global AGENT_EMBEDDINGS
    if not AGENT_EMBEDDINGS:
        logger.info(f"{Fore.CYAN}Inicializando matriz de vectores semánticos (Embeddings)...{Style.RESET_ALL}")
        for name, desc in AGENT_DESCRIPTIONS.items():
            vec = get_embedding(desc)
            if vec:
                AGENT_EMBEDDINGS[name] = vec
        logger.info(f"{Fore.GREEN}Vectores cargados: {len(AGENT_EMBEDDINGS)}/{len(AGENT_DESCRIPTIONS)}{Style.RESET_ALL}")

# ================= FUNCIONES OPEN FLOOR PROTOCOL (OFP) =================
ORCHESTRATOR_URL = "http://orchestrator:5000/receive"
ORCHESTRATOR_SPEAKER_URI = "tag:orchestrator.local,2026:orch001"

def create_openfloor_envelope(events, conversation_id=None):
    if not conversation_id: conversation_id = str(uuid.uuid4())
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
    for agent, info in responses_map.items():
        speaker = f"tag:{agent}.local,2026:agent001"
        
        # --- CORRECCIÓN FASE 2: Inyectar Spans y extraer texto ---
        if isinstance(info, dict):
            content = info.get("text", "")
            span_content = info.get("span", {})
        else:
            content = info
            now = datetime.utcnow().isoformat() + "Z"
            span_content = {"startTime": now, "endTime": now}
            
        events.append({
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": speaker,
                    "span": span_content, # ¡AQUÍ SE GUARDAN LOS TIEMPOS!
                    "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": content}]}}
                }
            }
        })
    events.append({"eventType": "yieldFloor", "parameters": {}})
    return create_openfloor_envelope(events, conversation_id)

def send_ovon_event(url, events, conversation_id=None):
    try:
        if not conversation_id: conversation_id = str(uuid.uuid4())
        payload = create_openfloor_envelope(events, conversation_id)
        logger.info(f"[ORCHESTRADOR] → Enviando a {url} | Conv ID: {conversation_id[:8]}...")
        
        response = requests.post(url, json=payload, timeout=180, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        
        agent_name = next((name for name, u in AGENTS.items() if u == url), "unknown")
        print(f"{Fore.GREEN}← Respuesta recibida de {agent_name.upper()}{Style.RESET_ALL}")
        return response.json()
    except Exception as e:
        logger.error(f"[ERROR] en comunicación con {url}: {e}")
        return create_openfloor_envelope([{"eventType": "error", "parameters": {"message": str(e)}}], conversation_id)

def extract_reply_from_ovon(response):
    try:
        events = response.get("openFloor", {}).get("events", [])
        for event in events:
            if event.get("eventType") == "utterance":
                tokens = event.get("parameters", {}).get("dialogEvent", {}).get("features", {}).get("text", {}).get("tokens", [])
                if tokens: return tokens[0].get("value", "Sin respuesta")
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
                "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": text}]}}
            }
        }
    }]

# ================= RUTA PRINCIPAL DE CONSULTA =================
@app.route('/query', methods=['POST'])
def handle_query():
    logger.info("[ORCHESTRADOR] ← Nueva consulta recibida")
    start_time = time.time()
    data = request.get_json()
    user_query = data.get('query')

    if not user_query or not isinstance(user_query, str):
        return jsonify({"error": "Falta el campo 'query' en el JSON"}), 400

    # 1. CARGA DE VECTORES Y CÁLCULO DE SIMILITUD
    load_embeddings_if_needed()
    user_vec = get_embedding(user_query)
    
    scores = {}
    if user_vec is not None:
        for name, agent_vec in AGENT_EMBEDDINGS.items():
            similarity = cosine_similarity(user_vec, agent_vec)
            scores[name] = round(float(similarity), 4)
    
    logger.info(f"Matriz de Similitud: {scores}")

   # 2. CLASIFICACIÓN ORIENTADA A COLABORACIÓN (Con Chain of Thought)
    classification_prompt = f"""Analiza la consulta híbrida paso a paso y responde ÚNICAMENTE con un objeto JSON válido.

    {{
      "razonamiento_interno": "Aquí debes escribir tu análisis lógico. Divide la consulta en partes e identifica qué agente es experto en cada parte.",
      "intents": ["agente1", "agente2", "..."],
      "strategy": "sequential" | "parallel",
      "segmentos": {{
          "agente1": "la sub-pregunta exacta extraída para el agente1",
          "agente2": "la sub-pregunta exacta extraída para el agente2"
      }},
      "requiere_traduccion": true | false,
      "idioma_objetivo": "español" | "inglés" | "francés" | "alemán" | "portugués",
      "orden_ejecucion": ["agente1", "agente2", "..."]
    }}

    --- CAPACIDADES EXPLICITAS DE LOS EXPERTOS ---
    1. fisica: Leyes físicas, fórmulas, cinemática, energía, Newton.
    2. mathbuddy_basico: Operaciones básicas, sumas, fracciones, ecuaciones simples, divisiones.
    3. mathbuddy_avanzado: Cálculo, derivadas, integrales, límites.
    4. algebra: Factorización, polinomios, ecuaciones algebraicas, mínimo común múltiplo.
    5. computacion: Hardware, software, RAM, ROM, CPU, sistemas operativos, ENIAC.
    6. espanol: Gramática, ortografía, acentos, palabras graves/agudas, signos de puntuación.
    7. historia: Fechas, guerras, biografías (Curie, Einstein, Juárez), Revolución, imperios.
    8. programacion: C++, punteros, memoria dinámica, new/delete, herencia, clases.
    9. quimica: Tabla periódica, enlaces, átomos, isótopos, lluvia ácida, moles.
    10. translator: ÚNICAMENTE si la pregunta pide explícitamente traducir texto a otro idioma.

    AYUDA MATEMÁTICA (Scores de similitud de la consulta con los agentes):
    {json.dumps(scores, indent=2)}

    REGLAS CRÍTICAS DE DECISIÓN (¡LEER ATENTAMENTE!):
    1. ¡NO OMITAS A NADIE! Si la consulta hace 4 preguntas diferentes, DEBES incluir obligatoriamente a los 4 agentes distintos en el arreglo 'intents'.
    2. CUIDADO CON LA DILUCIÓN VECTORIAL: Al mezclar 4 temas en una frase, los scores matemáticos bajan. Confía en tu comprensión lectora por encima de los scores. Si la consulta habla de "ortografía" (espanol) y "átomos" (quimica), agrégalos sin importar si su score es bajo.
    3. Si se pide explicar algo Y traducirlo, incluye al experto (ej. historia) Y al 'translator' al final.
    4. MÁXIMA EFICIENCIA: Usa 'parallel' siempre que las preguntas se puedan responder de forma independiente.

    Consulta del usuario: {user_query}
    """
    try:
        print(f"{Fore.CYAN}[ORCHESTRADOR] Analizando intención (Embedding + LLM)...{Style.RESET_ALL}")
        intent_response = ollama_client.chat(
            model='llama3.2:3b',
            format='json',
            messages=[{'role': 'user', 'content': classification_prompt}],
            options={"temperature": 0.0}
        )
        decision = json.loads(intent_response['message']['content'].strip())
        
        
        # Limpieza de listas: Forzar minúsculas y limpiar espacios)
        intents = [str(i).strip().lower() for i in decision.get("intents", []) if isinstance(i, str)]
        orden_ejecucion = [str(o).strip().lower() for o in decision.get("orden_ejecucion", []) if isinstance(o, str)]
        
        # Forzar minúsculas en las claves de los segmentos
        segmentos_dinamicos = {str(k).strip().lower(): v for k, v in decision.get("segmentos", {}).items()}

        # Validación de Traducción
        user_query_lower = user_query.lower()
        palabras_traduccion = ["traduce", "traducir", "frances", "francés", "inglés", "ingles", "portugués", "portugues"]
        
        intent_traduccion_real = decision.get("requiere_traduccion", False) or ("translator" in intents) or any(p in user_query_lower for p in palabras_traduccion)

        if intent_traduccion_real:
            requiere_traduccion = True
            orden_ejecucion = [a for a in orden_ejecucion if a != "translator"]
            if "translator" not in intents: intents.append("translator")
            if not decision.get("idioma_objetivo"):
                if "frances" in user_query_lower or "francés" in user_query_lower: decision["idioma_objetivo"] = "francés"
                elif "ingles" in user_query_lower or "inglés" in user_query_lower: decision["idioma_objetivo"] = "inglés"
        else:
            requiere_traduccion = False

        strategy = decision.get("strategy", "sequential")

        if not intents and not requiere_traduccion:
            return jsonify(create_openfloor_envelope(create_utterance_event("Ninguno de nuestros asistentes tiene la respuesta para esta consulta.")))

        print(f"{Fore.MAGENTA}--- DECISIÓN DEL ORQUESTADOR ---{Style.RESET_ALL}")
        print(f"Estrategia: {strategy.upper()}")
        print(f"Orden: {orden_ejecucion}")
        print(f"{Fore.MAGENTA}-------------------------------{Style.RESET_ALL}")

    except Exception as e:
        logger.error(f"Error crítico en clasificación del LLM: {e}")
        return jsonify(create_openfloor_envelope(create_utterance_event("Hubo un error interno al analizar tu pregunta.")))

    # 3. EJECUCIÓN DE AGENTES (Con auditoría de Spans)
    conversation_id = str(uuid.uuid4())
    responses_map = {}
    main_agents = [a for a in orden_ejecucion if a != "translator" and a in AGENTS]

    if strategy == "parallel":
        print(f"{Fore.GREEN}>> INICIANDO EJECUCIÓN PARALELA{Style.RESET_ALL}")
        threads = []

        def call_agent_thread(agente_key):
            query_especifica = segmentos_dinamicos.get(agente_key, user_query)
            
            # --- CORRECCIÓN FASE 2: Capturar Tiempos Individuales ---
            t_start = datetime.utcnow().isoformat() + "Z"
            resp = send_ovon_event(AGENTS[agente_key], create_utterance_event(query_especifica), conversation_id)
            t_end = datetime.utcnow().isoformat() + "Z"
            
            reply = extract_reply_from_ovon(resp)
            if reply and reply not in ["Sin respuesta", "Error"]:
                # Guardamos como diccionario con el Span
                responses_map[agente_key] = {"text": reply, "span": {"startTime": t_start, "endTime": t_end}}

        for agente in main_agents:
            t = threading.Thread(target=call_agent_thread, args=(agente,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join() 
    else:
        print(f"{Fore.YELLOW}>> INICIANDO EJECUCIÓN SECUENCIAL{Style.RESET_ALL}")
        contexto_acumulado = ""

        for agente_key in main_agents:
            segmento_agente = segmentos_dinamicos.get(agente_key, user_query)
            prompt_con_historia = f"{contexto_acumulado}\n\nTarea actual: {segmento_agente}" if contexto_acumulado else segmento_agente

            # --- CORRECCIÓN FASE 2: Capturar Tiempos Individuales ---
            t_start = datetime.utcnow().isoformat() + "Z"
            resp = send_ovon_event(AGENTS[agente_key], create_utterance_event(prompt_con_historia), conversation_id)
            t_end = datetime.utcnow().isoformat() + "Z"
            
            reply = extract_reply_from_ovon(resp)
            
            if reply and reply not in ["Sin respuesta", "Error"]:
                responses_map[agente_key] = {"text": reply, "span": {"startTime": t_start, "endTime": t_end}}
                contexto_acumulado += f"\n\n[Aporte de {agente_key}]: {reply}"
   
    # 4. TRADUCCIÓN (Capa final con auditoría de Span)
    if requiere_traduccion and "translator" in AGENTS:
        # Extraemos solo los textos del mapa de respuestas para unirlos
        texto_para_traducir = "\n\n".join([info["text"] if isinstance(info, dict) else info for info in responses_map.values()]) if responses_map else user_query
        idioma_objetivo = decision.get("idioma_objetivo", "inglés").lower()
        prompt_trans = f"INSTRUCCIÓN: Traduce al {idioma_objetivo}. RESPONDE ÚNICAMENTE CON LA TRADUCCIÓN.\n\nContenido: {texto_para_traducir}"
        
        logger.info(f"[ORCHESTRADOR] -> Solicitando traducción al {idioma_objetivo}")
        
        t_start = datetime.utcnow().isoformat() + "Z"
        resp_trans = send_ovon_event(AGENTS["translator"], create_utterance_event(prompt_trans), conversation_id)
        t_end = datetime.utcnow().isoformat() + "Z"
        
        traduccion_final = extract_reply_from_ovon(resp_trans)
        
        if traduccion_final and "Sin respuesta" not in traduccion_final:
            responses_map["translator"] = {"text": traduccion_final, "span": {"startTime": t_start, "endTime": t_end}}

    # 5. RETORNO FINAL
    response_payload = create_collaborative_response(responses_map, conversation_id)
    logger.info(f"Consulta resuelta en {time.time() - start_time:.2f} segundos")
    return jsonify(response_payload)
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)