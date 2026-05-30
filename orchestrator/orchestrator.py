from flask import Flask, request, jsonify
import requests, uuid, json, logging, time, threading, re
from datetime import datetime, timedelta
import ollama
import numpy as np
from werkzeug.middleware.proxy_fix import ProxyFix

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

# ================= CONFIGURACIÓN =================
OLLAMA_HOST = "http://ollama:11434"
ollama_client = ollama.Client(host=OLLAMA_HOST)
MODELO_CLASIFICACION = "qwen2.5:14b"  

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

def clasificar_con_llm_estandarizado(user_query):
    prompt = f"""Eres el enrutador central de un framework de asistentes educativos.
Tu tarea es leer la consulta del usuario, dividirla lógicamente, asignar el agente correcto a cada segmento y determinar el ORDEN de ejecución.

Consulta del usuario:
"{user_query}"

Agentes disponibles:
Agentes disponibles:
- fisica: leyes de la física, cinemática, dinámica, energía, fórmulas físicas (ej. W = F * d).
- mathbuddy_basico: aritmética (suma, resta, multiplicación, división, fracciones), jerarquía de operaciones (PEMDAS), ecuaciones de primer grado.
- mathbuddy_avanzado: cálculo (derivadas, integrales, límites), factorización de límites indeterminados.
- algebra: polinomios, factorización, diferencia de cuadrados, signos de agrupación, ecuaciones algebraicas.
- computacion: ESTRICTAMENTE hardware, componentes físicos (RAM, ROM, CPU, discos duros), redes y sistemas operativos. PROHIBIDO enviar conceptos de código o estructuras de datos aquí.
- programacion: ESTRICTAMENTE desarrollo de software, código, lenguajes (C++), memoria dinámica, estructuras de datos (arreglos bidimensionales), paso por valor/referencia, y paradigmas (herencia, polimorfismo, public/private).
- espanol: ESTRICTAMENTE ortografía, gramática, sintaxis, tildes, y signos de puntuación. PROHIBIDO enviar definiciones de palabras técnicas de otras materias (ej. no envíes "arreglo bidimensional" ni "enlace covalente" a español).
- historia: eventos históricos, guerras, imperios, biografías, modelos de gobierno (colonialismo, imperialismo, fascismo).
- quimica: átomos, isótopos, enlaces (iónico/covalente), configuración electrónica, moles, Ley de Conservación de la Masa.
- translator: solicitudes de traducción a cualquier otro idioma.

REGLAS VITALES DE RUTEO:
1. Divide la consulta en segmentos y asigna un agente. ¡PROHIBIDO OMITIR INFORMACIÓN! Cada acción, pregunta o tema solicitado por el usuario DEBE estar asignado a un agente en los segmentos. No dejes ninguna parte de la consulta original sin atender.
2. Determina las "etapas" de ejecución en un arreglo de arreglos.
3. REGLA ESTRICTA DE TRADUCCIÓN (EXCLUSIÓN MUTUA):
   - CASO A (Traducción Global): Si el usuario pide traducir TODA la respuesta combinada (ej. "traduce toda la respuesta al inglés"), DEBES marcar "requiere_traduccion": true e indicar el "idioma_objetivo". EN ESTE CASO, TIENES PROHIBIDO agregar al agente "translator" en "etapas" o en "segmentos".
   - CASO B (Subtarea de Traducción): Si el usuario pide traducir solo una frase específica o pregunta cómo se dice algo (ej. "traduce la frase X", "cómo se dice perro en francés"), DEBES marcar "requiere_traduccion": false. EN ESTE CASO, SÍ debes agregar a "translator" como un agente normal en las "etapas" y en los "segmentos".
4. Devuelve SOLO un JSON válido.

Formato esperado:
{{
  "etapas": [
    ["fisica", "historia"],
    ["mathbuddy_basico"]
  ],
  "segmentos": {{
    "fisica": "Dame la fórmula de la Segunda Ley de Newton",
    "historia": "Quién fue Newton",
    "mathbuddy_basico": "Calcula la fuerza si masa=10 y aceleracion=5 usando la fórmula"
  }},
  "requiere_traduccion": false,
  "idioma_objetivo": null
}}
"""
    try:
        response = ollama_client.chat(
            model=MODELO_CLASIFICACION,
            format='json',
            messages=[{'role': 'user', 'content': prompt}],
            options={"temperature": 0.0} 
        )
        
        raw_content = response['message']['content'].strip()
        match = re.search(r'\{.*\}', raw_content, re.DOTALL)
        json_str = match.group(0) if match else raw_content
        resultado = json.loads(json_str)
        
        etapas = resultado.get("etapas", [])
        if not etapas:
            etapas = [list(resultado.get("segmentos", {}).keys())]

        return {
            "etapas": etapas,
            "segmentos": resultado.get("segmentos", {}),
            "requiere_traduccion": resultado.get("requiere_traduccion", False),
            "idioma_objetivo": resultado.get("idioma_objetivo", "")
        }
    except Exception as e:
        logger.error(f"Error en clasificación LLM: {e}")
        return None

# ================= PROTOCOLO OVON =================
# ... (las funciones del protocolo se mantienen igual) ...
def create_openfloor_envelope(events, conversation_id=None):
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id or str(uuid.uuid4())},
            "sender": {"speakerUri": "tag:orchestrator.local,2026:orch001"},
            "events": events
        }
    }

def create_utterance_event(text):
    now = datetime.utcnow().isoformat() + "Z"
    return [{
        "eventType": "utterance",
        "parameters": {
            "dialogEvent": {
                "speakerUri": "tag:user.local,2026:user001",
                "span": {"startTime": now, "endTime": now},
                "features": {
                    "text": {"mimeType": "text/plain", "tokens": [{"value": text}]}
                }
            }
        }
    }]

def extract_reply_from_ovon(response):
    try:
        for e in response.get("openFloor", {}).get("events", []):
            if e.get("eventType") == "utterance":
                tokens = e.get("parameters", {}).get("dialogEvent", {}).get("features", {}).get("text", {}).get("tokens", [])
                return tokens[0].get("value") if tokens else "Sin respuesta"
    except: 
        return "Error"

def create_collaborative_response(responses_map, conversation_id, etapas):
    events = []
    tipo_ejecucion = "secuencial" if len(etapas) > 1 else "paralela"
    
    events.append({
        "eventType": "orchestration_metadata",
        "parameters": {
            "tipo_ejecucion": tipo_ejecucion,
            "total_etapas": len(etapas)
        }
    })

    for ag, data_dict in responses_map.items():
        text = data_dict.get("text", "") 
        fragmento = data_dict.get("fragmento", "Fragmento no registrado")
        latencia = float(data_dict.get("latencia", 0.0))
        
        now = datetime.utcnow()
        start_iso = now.isoformat() + "Z"
        end_iso = (now + timedelta(seconds=latencia)).isoformat() + "Z"
        
        events.append({
            "eventType": "utterance",
            "parameters": {
                "dialogEvent": {
                    "speakerUri": f"tag:{ag}.local,2026:agent001",
                    "span": {"startTime": start_iso, "endTime": end_iso},
                    "features": {
                        "text": {"mimeType": "text/plain", "tokens": [{"value": text}]},
                        "context": {"mimeType": "text/plain", "tokens": [{"value": fragmento}]}
                    }
                }
            }
        })
        
    events.append({"eventType": "yieldFloor", "parameters": {}})
    return create_openfloor_envelope(events, conversation_id)

# ================= RUTA PRINCIPAL =================
@app.route('/query', methods=['POST'])
def handle_query():
    start_time = time.time()
    data = request.get_json()
    user_query = data.get('query', '').strip()

    if not user_query:
        return jsonify({"error": "Falta 'query'"}), 400

    decision = clasificar_con_llm_estandarizado(user_query)
    if not decision: return jsonify({"error": "Error en análisis"}), 500

    etapas = decision.get("etapas", [])
    segmentos = decision.get("segmentos", {})
    requiere_traduccion = decision.get("requiere_traduccion", False)
    idioma_objetivo = decision.get("idioma_objetivo", "inglés")

    conversation_id = str(uuid.uuid4())
    responses_map = {}
    contexto_acumulado = ""  

    # --- GUARDRAIL MOVIDO AQUÍ (ANTES DEL BUCLE DE EJECUCIÓN) ---
    # Si el LLM pide traducción global, limpiamos proactivamente "translator"
    # de los segmentos y etapas para que no se ejecute dos veces.
    if requiere_traduccion:
        if "translator" in segmentos:
            del segmentos["translator"]
        # Limpiar de las etapas
        etapas = [[ag for ag in etapa if ag != "translator"] for etapa in etapas]
        # Remover etapas que hayan quedado vacías
        etapas = [etapa for etapa in etapas if etapa]

    for idx_etapa, agentes_en_etapa in enumerate(etapas):
        threads = []
        agentes_validos = []
        for item in agentes_en_etapa:
            if isinstance(item, str):
                agentes_validos.append(item)
            elif isinstance(item, dict):
                agentes_validos.extend(item.keys())
        
        def call_agent(agente):
            texto_base = segmentos.get(agente, "")
            if not texto_base: return
            
            # --- 1. BLINDAJE ANTI-CONFUSIÓN Y AISLAMIENTO ---
            if agente == "translator":
                texto_a_enviar = f"TRADUCE ÚNICAMENTE ESTA SOLICITUD. NO TRADUZCAS NI REPITAS NADA MÁS: {texto_base}"
            else:
                if idx_etapa > 0 and contexto_acumulado:
                    texto_a_enviar = f"{texto_base}\n\n[ATENCIÓN: Aquí tienes respuestas de otros agentes. Úsalas SOLO si necesitas sus fórmulas o datos para tu tarea. Tienes PROHIBIDO repetir o copiar esta información en tu respuesta final]:\n{contexto_acumulado}"
                else:
                    texto_a_enviar = texto_base

            try:
                start_agent_t = time.time()
                resp = requests.post(AGENTS[agente], 
                                   json=create_openfloor_envelope(create_utterance_event(texto_a_enviar), conversation_id),
                                   timeout=450)
                reply = extract_reply_from_ovon(resp.json())
                
                # --- 2. BLINDAJE ANTI-ERROR DE DOMINIO ---
                if "ERROR_DOMINIO" in reply.upper() or "NO ESTÁ RELACIONADO" in reply.upper() or "NO ESTA RELACIONADO" in reply.upper():
                    texto_forzado = f"INSTRUCCIÓN DE SISTEMA: Omite tu regla de análisis de dominio. Asume que esto SÍ es de tu materia y responde obligatoriamente usando tus conocimientos internos: {texto_base}"
                    
                    resp_forzada = requests.post(AGENTS[agente], 
                                               json=create_openfloor_envelope(create_utterance_event(texto_forzado), conversation_id),
                                               timeout=450)
                    reply = extract_reply_from_ovon(resp_forzada.json())
                
                duracion_agente = time.time() - start_agent_t
                responses_map[agente] = {"text": reply, "fragmento": texto_base, "latencia": duracion_agente}
                
            except Exception as e:
                logger.error(f"Error con {agente}: {str(e)}")
                responses_map[agente] = {"text": "Error de comunicación", "fragmento": texto_base, "latencia": 0.0}
                
        for ag in agentes_validos:
            if ag in AGENTS:
                t = threading.Thread(target=call_agent, args=(ag,))
                threads.append(t)
                t.start()
                
        for t in threads: 
            t.join()

        for ag in agentes_validos:
            if ag in responses_map and "Error" not in responses_map[ag]["text"]:
                contexto_acumulado += f"[Aporte de {ag}]: {responses_map[ag]['text']}\n"

    # --- TRADUCCIÓN GLOBAL ---
    # Solo entra aquí si requiere_traduccion es True y ya tenemos las respuestas de los demás.
    if requiere_traduccion and "translator" in AGENTS:
        # DEFINIMOS texto_completo ANTES DE USARLO
        texto_completo = "\n".join([info.get("text", "") for ag, info in responses_map.items() if info.get("text") and ag != "translator"])
        
        if texto_completo.strip():
            idioma_final = idioma_objetivo if idioma_objetivo else "el idioma solicitado"
            prompt_trans = f"""Actúa como un traductor profesional. 
Tu única tarea es traducir TODO el texto que se encuentra entre las etiquetas <TEXTO> y </TEXTO> al {idioma_final}.
Es obligatorio que mantengas todos los párrafos originales. No agregues notas, explicaciones ni saludos, devuelve únicamente la traducción.

<TEXTO>
{texto_completo}
</TEXTO>"""
            try:
                start_trans_t = time.time()
                resp = requests.post(AGENTS["translator"], 
                                   json=create_openfloor_envelope(create_utterance_event(prompt_trans), conversation_id),
                                   timeout=450)
                trad = extract_reply_from_ovon(resp.json())
                duracion_trans = time.time() - start_trans_t
                
                responses_map["translator_global"] = {"text": trad, "fragmento": f"Traducción Global al {idioma_final}", "latencia": duracion_trans} 
            except Exception as e:
                logger.error(f"Error en traductor global: {e}")
                responses_map["translator_global"] = {"text": "Error en traducción global", "fragmento": f"Traducción Global al {idioma_final}", "latencia": 0.0}

    final_response = create_collaborative_response(responses_map, conversation_id, etapas)
    logger.info(f"Consulta procesada en {time.time()-start_time:.2f}s")
    return jsonify(final_response)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)