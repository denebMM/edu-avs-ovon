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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Esto le dice a Flask que confíe en los headers que vienen del orquestador
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

# esta linea de abajo es para la PC dela escuela
OLLAMA_HOST = "http://ollama:11434"
#Este linea de abajo es para la lapto
#OLLAMA_HOST = "http://host.docker.internal:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)

AGENTS = {
    "physics": "http://assistant_physics:5002/receive",
    "alice": "http://assistant_alice:5005/receive",
    "history": "http://assistant_history:5003/receive",
    "translator": "http://assistant_translator:5010/receive", # para linux
    #"translator": "http://host.docker.internal:5010/receive", #para Windows mi lapto
    "mathbuddy_avanzado": "http://mathbuddy-avanzado-wrapper:5011/receive",  
    "mathbuddy_basico": "http://mathbuddy-basico-wrapper:5012/receive",
    "algebra": "http://assistant_algebra:5013/receive",
    "computacion": "http://assistant_computacion:5014/receive",
    "espanol": "http://assistant_espanol:5015/receive",
    "historia": "http://assistant_historia:5016/receive",
    "programacion": "http://assistant_programacion:5017/receive",
    "quimica": "http://assistant_quimica:5018/receive" 
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

    # ====================== CLASIFICACIÓN ORIENTADA A COLABORACIÓN ======================
    classification_prompt = f"""Analiza la consulta y responde ÚNICAMENTE con JSON.

    {{
      "intents": ["agente1", "agente2"],
      "strategy": "sequential" | "parallel",
      "segmentos": {{
          "agente1": "sub-pregunta específica para el agente1",
          "agente2": "sub-pregunta específica para el agente2"
      }},
      "requiere_traduccion": true | false,
      "idioma_objetivo": "español" | "inglés" | "francés" | "alemán" | "portugués",
      "orden_ejecucion": ["agente1", "agente2"]
    }}

    CAPACIDADES DE LOS AGENTES:
    1. physics: Teoría física, leyes (Newton, etc.), conceptos del libro de texto (RAG).
    2. mathbuddy_basico: Operaciones aritméticas, porcentajes, álgebra simple.
    3. mathbuddy_avanzado: Cálculo, derivadas, integrales, límites.
    4. algebra: Teoría de álgebra, polinomios, factorización y conceptos extraídos de libros especializados (RAG). Use este para consultas académicas profundas de álgebra.
    5. history: Datos históricos, fechas y personajes.
    6. alice: Saludos y presentaciones.
    7. computacion: Conceptos de hardware, software, sistemas operativos, redes y arquitectura de computadoras (RAG).
    8. espanol: Dudas sobre gramática, ortografía, análisis literario, sintaxis y reglas del idioma español (RAG).
    9. historia: Consultas sobre procesos históricos, fechas exactas, biografía de personajes históricos y análisis de contextos sociales pasados (RAG).
    10. programacion: Consultas sobre lógica de programación, sintaxis de lenguajes (especialmente C++), estructuras de datos y algoritmos (RAG).
    11. quimica: Consultas sobre la tabla periódica, enlaces químicos, estequiometría, compuestos orgánicos e inorgánicos y leyes de la materia (RAG).
    12. translator: OBLIGATORIO si piden 'traducir' o cambiar de idioma.
    PROHIBIDO activarlo para consultas informativas en el mismo idioma.
   

   REGLA DE SEGMENTACIÓN (OBLIGATORIA):
    - Si la estrategia es 'parallel': Divide la consulta en partes 100% independientes. 
      Ejemplo: "Inercia y 2+2" -> {{"physics": "ley de la inercia", "mathbuddy_basico": "2+2"}}
    - Si la estrategia es 'sequential': El segmento del primer agente debe ser la base, y el del segundo la instrucción de qué hacer con esa base.
      Ejemplo: "Calcula la fuerza de f=m*a con m=10, a=2" -> 
      {{
        "physics": "fórmula y planteamiento f=m*a con m=10, a=2", 
        "mathbuddy_basico": "calcular resultado numérico de f=10*2"
        }}
    
    REGLA DE SEGMENTACIÓN PARA TRADUCTOR:
    - El traductor NO necesita un segmento. Su entrada será el resultado de todos los demás agentes.
    - Si la consulta requiere traducción, DEBES incluir "translator" en la lista de 'intents'.
    
    REGLA DE DECISIÓN DE ESTRATEGIA (CRÍTICA):
        - Compara las partes de la consulta:
        * ¿El Agente 2 necesita un número o resultado que el Agente 1 va a generar? 
            SI -> 'strategy': 'sequential'
            NO -> 'strategy': 'parallel'
        
        - CASO DE PRUEBA: "Ley de inercia y cuánto es 450*12"
        Análisis: La inercia es teoría. 450*12 es aritmética. No hay conexión.
        Resultado: 'strategy': 'parallel' (OBLIGATORIO).

    MÁXIMA EFICIENCIA:
       - El objetivo es reducir la latencia. 'parallel' es siempre preferible a menos que el Agente B no pueda trabajar sin la respuesta del Agente A.
       - Si detectas a [physics] y [mathbuddy_basico] resolviendo cosas distintas (teoría vs aritmética), la estrategia SIEMPRE es 'parallel'.

    
    REGLAS DE EXCLUSIÓN Y UNIÓN:
        - Si el problema es de física y requiere cálculos, DEBES incluir 'physics' y el 'mathbuddy' correspondiente.
        - Solo incluye ambos mathbuddies si la consulta mezcla aritmética simple con cálculo complejo.
        - Si la consulta NO es educativa/técnica (cocina, chismes, etc.), responde: "intents": [], "orden_ejecucion": [].
        - Si la query pide explícitamente TRADUCIR una frase corta o famosa, NO actives a Alice. Alice solo debe activarse si no hay intención técnica o de traducción clara.
        - Si una pregunta pide 'Explica X y tradúcelo', DEBES asignar primero al experto (physics/history) y de ÚLTIMO al translator. El translator NUNCA debe ser el único si hay una consulta técnica involucrada.
        - Si la consulta NO pide traducción, el campo 'requiere_traduccion' DEBE ser estrictamente false.
        
    MATEMÁTICAS vs FÍSICA (Regla de Exclusión):
       - Si la consulta es una función matemática pura (ej. f(x)=..., sin(x), integrales, derivadas de funciones abstractas) sin mencionar objetos físicos (cohetes, pelotas, autos) ni leyes (Newton, Gravedad) -> USA ÚNICAMENTE 'mathbuddy'.
       - PROHIBIDO llamar a 'physics' si la consulta solo contiene notación matemática abstracta.

    Consulta: {user_query}
    """

    try:
        intent_response = ollama_client.chat(
            model='llama3.1:8b',
            format='json',
            messages=[{'role': 'user', 'content': classification_prompt}],
            options={"temperature": 0.0}
        )
        raw_content = intent_response['message']['content'].strip()
        decision = json.loads(raw_content)
        
        # --- FUNCIÓN DE LIMPIEZA ---
        def sanitize_list(raw_list):
            if not isinstance(raw_list, list):
                return []
            clean_list = []
            for item in raw_list:
                if isinstance(item, dict):
                    # Extrae el primer valor si el LLM mandó un objeto
                    val = list(item.values())[0]
                    clean_list.append(str(val))
                elif isinstance(item, str):
                    clean_list.append(item)
            return clean_list

        # Aplicamos la limpieza
        intents = sanitize_list(decision.get("intents", []))
        orden_ejecucion = sanitize_list(decision.get("orden_ejecucion", []))
        # --------------------------------------------------

        intent_traduccion_real = decision.get("requiere_traduccion", False) or ("translator" in intents)      
          
        #Escaneo de palabras clave en la consulta original
        user_query_lower = user_query.lower()
        palabras_traduccion = ["traduce", "traducir", "frances", "francés", "inglés", "ingles", "portugués", "portugues"]
        
        if any(p in user_query_lower for p in palabras_traduccion):
            intent_traduccion_real = True
            # Intentamos detectar el idioma si no viene en el JSON
            if not decision.get("idioma_objetivo"):
                if "frances" in user_query_lower or "francés" in user_query_lower:
                    decision["idioma_objetivo"] = "francés"
                elif "ingles" in user_query_lower or "inglés" in user_query_lower:
                    decision["idioma_objetivo"] = "inglés"

        # 3. ASIGNACIÓN FINAL DE VARIABLES DE CONTROL
        if intent_traduccion_real:
            requiere_traduccion = True
            # IMPORTANTE: Mantenemos 'translator' en 'intents' para las métricas,
            # pero lo sacamos de 'orden_ejecucion' para que no choque con los hilos expertos.
            orden_ejecucion = [a for a in orden_ejecucion if a != "translator"]
            if "translator" not in intents:
                intents.append("translator")
            logger.info(f"Traducción confirmada al idioma: {decision.get('idioma_objetivo', 'inglés')}")
        else:
            requiere_traduccion = False
        strategy = decision.get("strategy", "sequential")


    # === CASO: SIN ASISTENTE DISPONIBLE ===
        if not intents and not requiere_traduccion:
            msg = "Ninguno de nuestros asistentes educacionales tiene la respuesta para esta consulta."
            return jsonify(create_openfloor_envelope([{
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": ORCHESTRATOR_SPEAKER_URI,
                        "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": msg}]}}
                    }
                }
            }]))

        print(f"{Fore.MAGENTA}--- DECISIÓN DEL ORQUESTADOR ---{Style.RESET_ALL}")
        print(f"Estrategia: {strategy.upper()}")
        print(f"Orden: {orden_ejecucion}")
        print(f"{Fore.MAGENTA}-------------------------------{Style.RESET_ALL}")

    except Exception as e:
        logger.error(f"Error en clasificación: {e}")
        # En caso de error crítico del LLM, usamos Alice por defecto
        strategy = "sequential"
        orden_ejecucion = ["alice"]
        intents = ["alice"]

    conversation_id = str(uuid.uuid4())
    responses_map = {}
    main_agents = [a for a in orden_ejecucion if a != "translator" and a in AGENTS]
    
 # === PREPARACIÓN DE SEGMENTOS ===
    segmentos_dinamicos = decision.get("segmentos", {})

    # SELECCIÓN DE PATRÓN DE EJECUCIÓN 
    if strategy == "parallel":
        print(f"{Fore.GREEN}>> INICIANDO EJECUCIÓN PARALELA{Style.RESET_ALL}")
        threads = []

        def call_agent_thread(agente_key):
            # Usa el segmento específico si existe, si no, la query original
            query_especifica = segmentos_dinamicos.get(agente_key, user_query)
            logger.info(f"[PARALELO] Agente {agente_key} recibe: {query_especifica}")
            
            resp = send_ovon_event(AGENTS[agente_key], create_utterance_event(query_especifica), conversation_id)
            reply = extract_reply_from_ovon(resp)
            if reply and reply not in ["Sin respuesta", "Error"]:
                responses_map[agente_key] = reply

        for agente in main_agents:
            t = threading.Thread(target=call_agent_thread, args=(agente,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join() 
    else:
        # ================= PATRÓN SECUENCIAL =================
        print(f"{Fore.YELLOW}>> INICIANDO EJECUCIÓN SECUENCIAL{Style.RESET_ALL}")
        
        contexto_acumulado = "" # Empezamos limpio para construir la cadena

        for agente_key in main_agents:
            print(f"{Fore.YELLOW}>> EJECUTANDO AGENTE: {agente_key.upper()}{Style.RESET_ALL}")
            
            # En secuencial, combinamos el SEGMENTO específico con lo que dijeron los anteriores
            segmento_agente = segmentos_dinamicos.get(agente_key, user_query)
            
            # Si hay contexto previo, se lo pegamos al segmento para que sepa de qué viene
            prompt_con_historia = f"{contexto_acumulado}\n\nTarea actual: {segmento_agente}" if contexto_acumulado else segmento_agente

            resp = send_ovon_event(AGENTS[agente_key], create_utterance_event(prompt_con_historia), conversation_id)
            reply = extract_reply_from_ovon(resp)
            
            if reply and reply not in ["Sin respuesta", "Error"]:
                responses_map[agente_key] = reply
                # Actualizamos el contexto acumulado para el SIGUIENTE agente
                contexto_acumulado += f"\n\n[Aporte de {agente_key}]: {reply}"
   
   # TRADUCCIÓN FINAL (FUERA DE LOS IF/ELSE DE ESTRATEGIA)
    if requiere_traduccion and "translator" in AGENTS:
        # Unimos las respuestas generadas o usamos la query original si no hay agentes previos
        texto_para_traducir = "\n\n".join(responses_map.values()) if responses_map else user_query
        
        idioma_objetivo = decision.get("idioma_objetivo", "inglés").lower()
        
        prompt_trans = (
            f"INSTRUCCIÓN: Traduce el siguiente contenido técnico al {idioma_objetivo}. "
            f"RESPONDE ÚNICAMENTE CON LA TRADUCCIÓN. NO DIGAS 'AQUÍ ESTÁ LA TRADUCCIÓN'.\n\n"
            f"Contenido: {texto_para_traducir}"
        )
        
        logger.info(f"[ORCHESTRADOR] -> Solicitando traducción al {idioma_objetivo}")

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
            logger.info(" Traducción añadida al mapa de respuestas")

    # RESPUESTA FINAL
    response_payload = create_collaborative_response(responses_map, conversation_id)

    # METRICAS Y RETORNO
    total_time = time.time() - start_time
    try:
        from metrics.metrics_collector import MetricsCollector
        collector = MetricsCollector(storage_path="metrics")
        
        collector.record_query(
            user_query, 
            intents, 
            strategy,           # <-- PASAMOS LA ESTRATEGIA (parallel/sequential)
            responses_map, 
            response_payload, 
            total_time
        )
        logger.info(f"Métricas guardadas exitosamente para la query: {user_query[:30]}...")
    except Exception as e:
        logger.error(f"Error al guardar métricas: {e}")

    return jsonify(response_payload)
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)