import pandas as pd
import requests
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import json
from datetime import datetime
import os
import gc

# ================= CONFIGURACIÓN =================
directorio_actual = os.path.dirname(os.path.abspath(__file__))
# 1. Define el identificador dinámico de tu prueba actual
SUFIJO_PRUEBA = "_3_5"


# 2. Inyecta el sufijo dinámicamente usando f-strings (la letra 'f' antes de las comillas)
#ARCHIVO_DATASET = os.path.join(directorio_actual, f"dataset{SUFIJO_PRUEBA}.csv") 


ARCHIVO_DATASET = os.path.join(directorio_actual,"dataset_hibrido.csv") 

ARCHIVO_RESULTADOS_PREGUNTAS = os.path.join(directorio_actual, f"resultados_fase2_detalle_preguntas{SUFIJO_PRUEBA}.csv")
ARCHIVO_RESULTADOS_AGENTES = os.path.join(directorio_actual, f"resultados_fase2_metricas_agentes{SUFIJO_PRUEBA}.csv")
ARCHIVO_RESULTADOS_GLOBALES = os.path.join(directorio_actual, f"resultados_fase2_metricas_globales{SUFIJO_PRUEBA}.csv")

ORCHESTRATOR_URL = "http://localhost:5000/query"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"

MODELO_EMBEDDING = "mxbai-embed-large" 
# Agregamos TODOS los modelos del ecosistema para purgar la RAM completa
MODELOS_A_LIMPIAR = [
    "llama3.2:3b", "llama3.1:8b", "qwen2.5:3b", "gemma2:2b",
    "qwen2.5:14b", "mxbai-embed-large"  
]

# ================= FUNCIONES DE LIMPIEZA DE RAM =================
def limpiar_memoria_ollama():
    """Fuerza a Ollama a descargar TODOS los modelos de la RAM/VRAM"""
    print(f"\n ..... Forzando liberación total de memoria RAM en Ollama...")
    for modelo in MODELOS_A_LIMPIAR:
        try:
            requests.post(OLLAMA_GENERATE_URL, json={"model": modelo, "keep_alive": 0}, timeout=5)
        except Exception:
            pass # Ignoramos errores si el modelo ya estaba descargado
    time.sleep(5) # Dar tiempo al sistema operativo para reclamar la RAM
    print("......... Memoria liberada exitosamente. Continuando...\n")

def obtener_embedding(texto, max_reintentos=4):
    if not isinstance(texto, str) or not texto.strip() or str(texto).lower() == 'nan':
        return None
    
    texto_seguro = texto[:1500]
    tiempo_espera = 5 
    
    for intento in range(max_reintentos):
        try:
            resp = requests.post(
                OLLAMA_URL, 
                json={"model": MODELO_EMBEDDING, "prompt": texto_seguro}, 
                timeout=500
            )
            resp.raise_for_status()
            return np.array(resp.json()["embedding"]).reshape(1, -1)
            
        except requests.exceptions.RequestException as e:
            print(f"___Ollama saturado en embedding. (Intento {intento+1}/{max_reintentos})")
            time.sleep(tiempo_espera) 
            tiempo_espera *= 2 
            
    print(f".. Fallo definitivo al obtener embedding tras {max_reintentos} intentos.")
    return None
        
def parsear_tiempo_iso(iso_str):
    if not iso_str: return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except:
        return None

def procesar_respuesta_ofp_detallado(data):
    agents_info = {}
    texto_combinado = ""
    fragmentos_log = [] 
    
    eventos = data.get('openFloor', {}).get('events', [])
    for evento in eventos:
        if evento.get('eventType') == 'utterance':
            dialog_event = evento.get('parameters', {}).get('dialogEvent', {})
            
            speaker_uri = dialog_event.get('speakerUri', '')
            agente = "desconocido"
            if "tag:" in speaker_uri and ".local" in speaker_uri:
                agente = speaker_uri.split("tag:")[1].split(".local")[0]
            
            features = dialog_event.get('features', {})
            tokens = features.get('text', {}).get('tokens', [])
            texto = tokens[0].get('value', '') if tokens else ""
            
            # --- EXTRAER EL FRAGMENTO ENVIADO ---
            tokens_fragmento = features.get('context', {}).get('tokens', [])
            fragmento = tokens_fragmento[0].get('value', 'No enviado/No fraccionado') if tokens_fragmento else "No enviado"
            fragmentos_log.append(f"[{agente.upper()}]: {fragmento}")
            
            span = dialog_event.get('span', {})
            start = parsear_tiempo_iso(span.get('startTime'))
            end = parsear_tiempo_iso(span.get('endTime'))
            
            latencia_individual = 0.0
            if start and end:
                latencia_individual = (end - start).total_seconds()
            
            if agente not in agents_info:
                agents_info[agente] = {"texto": texto, "latencia": latencia_individual}
            else:
                agents_info[agente]["texto"] += " " + texto
                agents_info[agente]["latencia"] += latencia_individual
            
            texto_combinado += f"[{agente.upper()}]: {texto}\n\n"
            
    # Retornamos solo las 3 variables originales
    string_fragmentos = " | ".join(fragmentos_log)
    return agents_info, texto_combinado.strip(), string_fragmentos
    
# ================= FUNCIÓN PRINCIPAL DE EVALUACIÓN =================
def ejecutar_evaluacion_completa():
    print(" === Iniciando Evaluación End-to-End (Fase 2) con Gestión Extrema de Memoria ===")
    
    try:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='utf-8-sig', sep=None, engine='python')
    except UnicodeDecodeError:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='latin1', sep=None, engine='python')
        
    df.columns = df.columns.str.strip().str.lower().str.replace('"', '').str.replace("'", "")
    df = df.dropna(subset=['pregunta'])

    # Inicialización de las columnas del DataFrame de resultados   
    df["fragmentos_enviados_por_agente"] = ""
    df["agentes_reales"] = ""
    df["texto_respuesta_global"] = ""
    df["latencia_global_segundos"] = 0.0
    df["precision_ruteo"] = 0.0
    df["recall_ruteo"] = 0.0
    df["f1_score_ruteo"] = 0.0
    df["coseno_global"] = None

    metricas_agentes = {}
    global_precision, global_recall, global_f1 = [], [], []
    global_cosenos, global_tiempos = [], []

    for index, row in df.iterrows():
        pregunta = str(row['pregunta'])
        respuesta_ideal_global = str(row['respuesta_ideal'])
        
        esperados_str = str(row.get('agentes_esperados', ''))
        agentes_esperados = [a.strip().lower() for a in esperados_str.split(',')] if esperados_str else []

        print(f"\n-> Evaluando [{index+1}/{len(df)}]: {pregunta[:50]}...")
        
        inicio_global = time.time()
        try:
            resp = requests.post(ORCHESTRATOR_URL, json={"query": pregunta}, timeout=500)
            resp.raise_for_status()
            data = resp.json()
            # Desempaquetamos 3 variables
            agentes_reales_info, texto_bot_global, string_fragmentos = procesar_respuesta_ofp_detallado(data)
        except Exception as e:
            print(f"   X Error: {e}")
            agentes_reales_info, texto_bot_global, string_fragmentos = {}, "Error", "Error al procesar"
            
        latencia_global = round(time.time() - inicio_global, 2)
        global_tiempos.append(latencia_global)
        
        # --- EL RESPIRO TÁCTICO ---
        print("...Dando un respiro de 3s al hardware...")
        time.sleep(3) 

        agentes_reales_lista = [a.lower() for a in agentes_reales_info.keys()]

        # MÉTRICAS DE RUTEO
        vp_turno = len(set(agentes_esperados).intersection(set(agentes_reales_lista)))
        fp_turno = len(set(agentes_reales_lista) - set(agentes_esperados))
        fn_turno = len(set(agentes_esperados) - set(agentes_reales_lista))
        
        prec_g = vp_turno / (vp_turno + fp_turno) if (vp_turno + fp_turno) > 0 else 0
        rec_g = vp_turno / (vp_turno + fn_turno) if (vp_turno + fn_turno) > 0 else 0
        f1_g = 2 * (prec_g * rec_g) / (prec_g + rec_g) if (prec_g + rec_g) > 0 else 0
        
        global_precision.append(prec_g)
        global_recall.append(rec_g)
        global_f1.append(f1_g)

        # MÉTRICAS INDIVIDUALES
        todos_los_involucrados = set(agentes_esperados + agentes_reales_lista)
        for ag in todos_los_involucrados:
            if ag not in metricas_agentes:
                metricas_agentes[ag] = {'VP':0, 'FP':0, 'FN':0, 'cosenos':[], 'latencias':[]}
                
            if ag in agentes_esperados and ag in agentes_reales_lista:
                metricas_agentes[ag]['VP'] += 1
            elif ag not in agentes_esperados and ag in agentes_reales_lista:
                metricas_agentes[ag]['FP'] += 1
            elif ag in agentes_esperados and ag not in agentes_reales_lista:
                metricas_agentes[ag]['FN'] += 1

        # ========================================================
        # NUEVO: PURGA VITAL ANTES DE LOS EMBEDDINGS
        # ========================================================
        print("... Purgando modelos de los agentes para hacer espacio al modelo de Embeddings ...")
        limpiar_memoria_ollama()
        time.sleep(3) 

        # ========================================================
        # MÉTRICAS COSENO 
        # ========================================================
        cos_g = None  # Inicializamos en None en lugar de 0.0 para no afectar promedios
        if "Error" not in texto_bot_global:
            v_ideal_g = obtener_embedding(respuesta_ideal_global)
            v_bot_g = obtener_embedding(texto_bot_global)
            if v_ideal_g is not None and v_bot_g is not None:
                cos_g = round(cosine_similarity(v_ideal_g, v_bot_g)[0][0], 4)
                global_cosenos.append(cos_g)
            else:
                print(" -> Aviso: Embedding falló (RAM llena), saltando coseno...")

        for ag, info in agentes_reales_info.items():
            metricas_agentes[ag]['latencias'].append(info['latencia'])
            v_ideal_ind = obtener_embedding(respuesta_ideal_global)
            v_bot_ind = obtener_embedding(info['texto'])
            if v_ideal_ind is not None and v_bot_ind is not None:
                cos_ind = round(cosine_similarity(v_ideal_ind, v_bot_ind)[0][0], 4)
                metricas_agentes[ag]['cosenos'].append(cos_ind)

        # --- GUARDADO EN EL DATAFRAME ---
        df.at[index, "fragmentos_enviados_por_agente"] = string_fragmentos
        df.at[index, "agentes_reales"] = ", ".join(agentes_reales_lista)
        df.at[index, "texto_respuesta_global"] = texto_bot_global
        df.at[index, "latencia_global_segundos"] = latencia_global
        df.at[index, "precision_ruteo"] = round(prec_g, 4)
        df.at[index, "recall_ruteo"] = round(rec_g, 4)
        df.at[index, "f1_score_ruteo"] = round(f1_g, 4)
        
        # Si falló el embedding, escribimos un texto claro en el CSV
        df.at[index, "coseno_global"] = cos_g if cos_g is not None else "ERROR_EMBEDDING"

        # --- LIMPIEZA POST-PREGUNTA EXTREMA ---
        print(" === LIMPIEZA POST-PREGUNTA ===")
        limpiar_memoria_ollama() 
        gc.collect()             

    # ================= GUARDADO DE REPORTES EN CSV =================
    print("\n === Procesamiento completado. Generando reportes CSV... ===")

    try:
        df.to_csv(ARCHIVO_RESULTADOS_PREGUNTAS, index=False, encoding='utf-8-sig')
        print(f" [OK] Reporte Detallado: {os.path.basename(ARCHIVO_RESULTADOS_PREGUNTAS)}")
    except Exception as e: print(f" Error: {e}")

    datos_agentes = []
    for ag, m in sorted(metricas_agentes.items()):
        vp, fp, fn = m['VP'], m['FP'], m['FN']
        p = vp / (vp + fp) if (vp + fp) > 0 else 0
        r = vp / (vp + fn) if (vp + fn) > 0 else 0
        f1 = 2 * (p * r) / (p + r) if (p + r) > 0 else 0
        
        cos_mean = np.mean(m['cosenos']) if m['cosenos'] else 0.0
        lat_mean = np.mean(m['latencias']) if m['latencias'] else 0.0
        
        cos_var = np.var(m['cosenos'], ddof=1) if len(m['cosenos']) > 1 else 0.0
        lat_var = np.var(m['latencias'], ddof=1) if len(m['latencias']) > 1 else 0.0
        
        datos_agentes.append({
            "Agente": ag.upper(),
            "F1_Score_Ruteo": round(f1, 4),
            "Media_Similitud_Coseno": round(cos_mean, 4),
            "Varianza_Similitud_Coseno": round(cos_var, 4),
            "Media_Latencia_Segundos": round(lat_mean, 2),
            "Varianza_Latencia_Segundos": round(lat_var, 4)
        })
    try:
        df_ag = pd.DataFrame(datos_agentes)
        df_ag.to_csv(ARCHIVO_RESULTADOS_AGENTES, index=False, encoding='utf-8-sig')
        print(f" [OK] Reporte de Agentes: {os.path.basename(ARCHIVO_RESULTADOS_AGENTES)}")
    except Exception as e: print(f" Error: {e}")

    var_prec = np.var(global_precision, ddof=1) if len(global_precision) > 1 else 0.0
    var_rec = np.var(global_recall, ddof=1) if len(global_recall) > 1 else 0.0
    var_f1 = np.var(global_f1, ddof=1) if len(global_f1) > 1 else 0.0
    var_cos = np.var(global_cosenos, ddof=1) if len(global_cosenos) > 1 else 0.0
    var_lat = np.var(global_tiempos, ddof=1) if len(global_tiempos) > 1 else 0.0

    datos_globales = [{
        "Metrica": "Precision de Ruteo", "Media": round(np.mean(global_precision), 4), "Varianza": round(var_prec, 4)
    }, {
        "Metrica": "Recall de Ruteo", "Media": round(np.mean(global_recall), 4), "Varianza": round(var_rec, 4)
    }, {
        "Metrica": "F1-Score de Ruteo", "Media": round(np.mean(global_f1), 4), "Varianza": round(var_f1, 4)
    }, {
        "Metrica": "Similitud Coseno End-to-End", "Media": round(np.mean(global_cosenos), 4), "Varianza": round(var_cos, 4)
    }, {
        "Metrica": "Latencia Global Total", "Media": round(np.mean(global_tiempos), 2), "Varianza": round(var_lat, 4)
    }]
    try:
        df_glb = pd.DataFrame(datos_globales)
        df_glb.to_csv(ARCHIVO_RESULTADOS_GLOBALES, index=False, encoding='utf-8-sig')
        print(f" [OK] Reporte Global Orquestador: {os.path.basename(ARCHIVO_RESULTADOS_GLOBALES)}")
    except Exception as e: print(f" Error: {e}")

    print("\n === Evaluación Terminada Exitosamente. ===")

if __name__ == "__main__":
    ejecutar_evaluacion_completa()