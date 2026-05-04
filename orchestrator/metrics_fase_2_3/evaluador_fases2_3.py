import pandas as pd
import requests
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import json
from datetime import datetime
import os

# ================= CONFIGURACIÓN =================
directorio_actual = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_DATASET = os.path.join(directorio_actual, "dataset_hibrido.csv")
ARCHIVO_RESULTADOS = os.path.join(directorio_actual, "resultados_orquestador_detallado.csv")

ORCHESTRATOR_URL = "http://localhost:5000/query"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODELO_EMBEDDING = "qwen:4b"

def obtener_embedding(texto):
    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODELO_EMBEDDING, "prompt": texto})
        return np.array(resp.json()["embedding"]).reshape(1, -1)
    except Exception as e:
        print(f"Error embedding: {e}")
        return None

def parsear_tiempo_iso(iso_str):
    """Convierte un string ISO 8601 (con o sin Z) a un objeto datetime."""
    if not iso_str: return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except:
        return None

def procesar_respuesta_ofp_detallado(data):
    """Extrae texto y calcula el tiempo de CADA agente analizando el span."""
    agentes_info = {}
    texto_combinado = ""
    
    eventos = data.get('openFloor', {}).get('events', [])
    for evento in eventos:
        if evento.get('eventType') == 'utterance':
            dialog_event = evento.get('parameters', {}).get('dialogEvent', {})
            
            # 1. ¿Quién habló?
            speaker_uri = dialog_event.get('speakerUri', '')
            agente = "desconocido"
            if "tag:" in speaker_uri and ".local" in speaker_uri:
                agente = speaker_uri.split("tag:")[1].split(".local")[0]
            
            # 2. ¿Qué dijo?
            tokens = dialog_event.get('features', {}).get('text', {}).get('tokens', [])
            texto = tokens[0].get('value', '') if tokens else ""
            
            # 3. ¿Cuánto tardó individualmente? (Usando el span del OFP)
            span = dialog_event.get('span', {})
            start = parsear_tiempo_iso(span.get('startTime'))
            end = parsear_tiempo_iso(span.get('endTime'))
            
            latencia_individual = 0.0
            if start and end:
                latencia_individual = (end - start).total_seconds()
            
            # 4. Guardar información individual
            if agente not in agentes_info:
                agentes_info[agente] = {"texto": texto, "latencia": latencia_individual}
            else:
                agentes_info[agente]["texto"] += " " + texto
                agentes_info[agente]["latencia"] += latencia_individual # Suma si habló varias veces
            
            # 5. Acumular para el global
            texto_combinado += f"[{agente.upper()}]: {texto}\n\n"
                
    return agentes_info, texto_combinado.strip()

def ejecutar_evaluacion_completa():
    print(" _Iniciando Evaluación de Trazabilidad End-to-End (Fases 2 y 3)...")
    
    try:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='latin1')
        
    df = df.dropna(subset=['pregunta'])

    # Inicializar columnas para guardar en el CSV
    df["agentes_reales"] = ""
    df["texto_respuesta_global"] = ""
    df["latencia_global_segundos"] = 0.0
    df["precision_global"] = 0.0
    df["recall_global"] = 0.0
    df["f1_score_turno"] = 0.0
    df["coseno_global_turno"] = 0.0

    # Diccionario maestro para guardar métricas individuales en memoria
    metricas_agentes = {}

    # Listas para métricas globales
    global_precision = []
    global_recall = []
    global_f1 = []
    global_cosenos = []
    global_tiempos = []

    for index, row in df.iterrows():
        pregunta = str(row['pregunta'])
        respuesta_ideal_global = str(row['respuesta_ideal'])
        
        # Agentes que DEBÍAN ser llamados
        esperados_str = str(row.get('agentes_esperados', ''))
        agentes_esperados = [a.strip() for a in esperados_str.split(',')] if esperados_str else []
        
        # Diccionario opcional de respuestas ideales por agente
        ideales_individuales = {}
        if 'respuestas_ideales_json' in df.columns and not pd.isna(row['respuestas_ideales_json']):
            try:
                ideales_individuales = json.loads(row['respuestas_ideales_json'])
            except: pass

        print(f"\n[{index+1}/{len(df)}] Q: {pregunta[:40]}...")
        
        # --- EJECUCIÓN ---
        inicio_global = time.time()
        try:
            resp = requests.post(ORCHESTRATOR_URL, json={"query": pregunta}, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            agentes_reales_info, texto_bot_global = procesar_respuesta_ofp_detallado(data)
        except Exception as e:
            print(f"  X Error Orquestador: {e}")
            agentes_reales_info = {}
            texto_bot_global = "Error"
        latencia_global = round(time.time() - inicio_global, 2)
        global_tiempos.append(latencia_global)
        
        agentes_reales_lista = list(agentes_reales_info.keys())
        print(f"  ↳ Esperados: {agentes_esperados} | Reales: {agentes_reales_lista} | Tiempo: {latencia_global}s")

        # --- EVALUACIÓN FASE 2: RUTEO ---
        vp_turno = len(set(agentes_esperados).intersection(set(agentes_reales_lista)))
        fp_turno = len(set(agentes_reales_lista) - set(agentes_esperados))
        fn_turno = len(set(agentes_esperados) - set(agentes_reales_lista))
        
        prec_g = vp_turno / (vp_turno + fp_turno) if (vp_turno + fp_turno) > 0 else 0
        rec_g = vp_turno / (vp_turno + fn_turno) if (vp_turno + fn_turno) > 0 else 0
        f1_g = 2 * (prec_g * rec_g) / (prec_g + rec_g) if (prec_g + rec_g) > 0 else 0
        
        global_precision.append(prec_g)
        global_recall.append(rec_g)
        global_f1.append(f1_g)

        # Actualizar contadores individuales
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

        # --- EVALUACIÓN FASE 3: INTEROPERABILIDAD ---
        cos_g = 0.0
        if "Error" not in texto_bot_global:
            v_ideal_g = obtener_embedding(respuesta_ideal_global)
            v_bot_g = obtener_embedding(texto_bot_global)
            if v_ideal_g is not None and v_bot_g is not None:
                cos_g = round(cosine_similarity(v_ideal_g, v_bot_g)[0][0], 4)
                global_cosenos.append(cos_g)

        for ag, info in agentes_reales_info.items():
            metricas_agentes[ag]['latencias'].append(info['latencia'])
            texto_ideal_agente = ideales_individuales.get(ag, respuesta_ideal_global)
            v_ideal_ind = obtener_embedding(texto_ideal_agente)
            v_bot_ind = obtener_embedding(info['texto'])
            
            if v_ideal_ind is not None and v_bot_ind is not None:
                cos_ind = round(cosine_similarity(v_ideal_ind, v_bot_ind)[0][0], 4)
                metricas_agentes[ag]['cosenos'].append(cos_ind)

        # -> ASIGNAR AL DATAFRAME <-
        df.at[index, "agentes_reales"] = ",".join(agentes_reales_lista)
        df.at[index, "texto_respuesta_global"] = texto_bot_global
        df.at[index, "latencia_global_segundos"] = latencia_global
        df.at[index, "precision_global"] = round(prec_g, 4)
        df.at[index, "recall_global"] = round(rec_g, 4)
        df.at[index, "f1_score_turno"] = round(f1_g, 4)
        df.at[index, "coseno_global_turno"] = cos_g

    # -> GUARDAR EL CSV <-
    try:
        df.to_csv(ARCHIVO_RESULTADOS, index=False, encoding='utf-8')
        print(f"\n Resultados guardados exitosamente en: {ARCHIVO_RESULTADOS}")
    except Exception as e:
        print(f"\n Error al guardar el archivo CSV: {e}")

    # === IMPRESIÓN DE RESULTADOS FINALES ===
    print("\n" + "="*60)
    print("  REPORTE DE AUDITORÍA: RENDIMIENTO INDIVIDUAL (FASE 2 Y 3)")
    print("="*60)
    print(f"{'AGENTE':<18} | {'PRECISION':<9} | {'RECALL':<8} | {'F1-SCORE':<8} | {'COSENO':<8} | {'LATENCIA (s)'}")
    print("-" * 75)
    
    for ag, m in sorted(metricas_agentes.items()):
        vp, fp, fn = m['VP'], m['FP'], m['FN']
        p = vp / (vp + fp) if (vp + fp) > 0 else 0
        r = vp / (vp + fn) if (vp + fn) > 0 else 0
        f1 = 2 * (p * r) / (p + r) if (p + r) > 0 else 0
        
        cos_mean = np.mean(m['cosenos']) if m['cosenos'] else 0.0
        lat_mean = np.mean(m['latencias']) if m['latencias'] else 0.0
        
        print(f"{ag.upper():<18} | {p:<9.2f} | {r:<8.2f} | {f1:<8.2f} | {cos_mean:<8.4f} | {lat_mean:.2f}s")

    print("\n" + "="*60)
    print(" REPORTE DE AUDITORÍA: RENDIMIENTO GLOBAL (END-TO-END)")
    print("="*60)
    print(f"Precisión Media (Ruteo Orquestador):     {np.mean(global_precision):.4f}")
    print(f"Recall Medio (Ruteo Orquestador):        {np.mean(global_recall):.4f}")
    print(f"F1-Score Medio (Ruteo Orquestador):      {np.mean(global_f1):.4f}")
    print(f"Similitud Coseno Media (Composición):    {np.mean(global_cosenos):.4f}")
    print(f"Latencia Media Total (Experiencia User): {np.mean(global_tiempos):.2f} segundos")

if __name__ == "__main__":
    ejecutar_evaluacion_completa()