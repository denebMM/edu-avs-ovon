import pandas as pd
import requests
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import json
import uuid
import os

# ================= CONFIGURACIÓN =================
directorio_actual = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_DATASET = os.path.join(directorio_actual, "dataset_fase1.csv")
ARCHIVO_RESULTADOS = os.path.join(directorio_actual, "resultados_fase1_completo.csv")
ARCHIVO_METRICAS_AGENTE = os.path.join(directorio_actual, "metricas_agentes_fase1.csv") # NUEVO ARCHIVO

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODELO_EMBEDDING = "mxbai-embed-large" #"qwen:4b" 
UMBRAL_COSENO_POSITIVO = 0.50 

# ================= FUNCIONES =================
def obtener_embedding(texto):
    # Validación para evitar que textos nulos rompan el código
    if not isinstance(texto, str) or not texto.strip() or str(texto).lower() == 'nan':
        return None
        
    texto_seguro = texto[:1500] # Evita que Ollama se trabe con textos infinitos
    
    try:
        # Se agregó TIMEOUT para que no se quede congelado por horas
        resp = requests.post(OLLAMA_URL, json={"model": MODELO_EMBEDDING, "prompt": texto_seguro}, timeout=30)
        resp.raise_for_status()
        return np.array(resp.json()["embedding"]).reshape(1, -1)
    except Exception as e:
        print(f"Error embedding: {e}")
        return None

def armar_payload_ofp(pregunta):
    conversation_id = str(uuid.uuid4())
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": "tag:evaluator.local,2026:tester001"},
            "events": [{
                "eventType": "utterance",
                "parameters": {
                    "dialogEvent": {
                        "speakerUri": "tag:user.local,2026:user001",
                        "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": pregunta}]}}
                    }
                }
            }]
        }
    }

def ejecutar_pruebas_fase1():
    print("Iniciando Evaluación Completa de Fase 1 (A prueba de fallos)...")
    
    try:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='latin1')
    
    df = df.dropna(subset=['asistente']) 
    
    # Nuevas columnas preparadas
    df["respuesta_sistema"] = ""
    df["tiempo_segundos"] = 0.0
    df["similitud_ideal"] = 0.0  # Antes se llamaba similitud_coseno
    df["fidelidad_rag"] = 0.0    # Nueva métrica RAG
    df["clasificacion"] = "" 

    # Búsqueda segura del nombre de la columna del libro
    columna_libro = None
    for col in df.columns:
        if 'libro' in col.lower():
            columna_libro = col
            break

    for index, row in df.iterrows():
        asistente = str(row['asistente']).strip()
        puerto = int(row['puerto'])
        pregunta = str(row['pregunta'])
        
        # Extracción segura de datos
        respuesta_ideal = str(row.get('respuesta_ideal', ''))
        respuesta_libro = str(row[columna_libro]) if columna_libro else ""
        
        print(f"[{index+1}/{len(df)}] {asistente.upper()}: {pregunta[:30]}...")

        url = f"http://localhost:{puerto}/receive"
        payload = armar_payload_ofp(pregunta)

        # 1. Medir Latencia
        inicio = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            respuesta_bot = data.get('openFloor', {}).get('events', [{}])[0].get('parameters', {}).get('dialogEvent', {}).get('features', {}).get('text', {}).get('tokens', [{}])[0].get('value', 'Error')
        except Exception as e:
            respuesta_bot = f"Error: {e}"
        tiempo_total = round(time.time() - inicio, 2)

        # 2. Medir Similitudes
        sim_ideal = 0.0
        sim_rag = 0.0
        
        if not respuesta_bot.startswith("Error"):
            vec_bot = obtener_embedding(respuesta_bot)
            vec_ideal = obtener_embedding(respuesta_ideal)
            
            # Coseno Ideal
            if vec_ideal is not None and vec_bot is not None:
                sim_ideal = round(cosine_similarity(vec_ideal, vec_bot)[0][0], 4)
            
            # Coseno RAG (Fidelidad)
            if columna_libro and respuesta_libro.strip():
                vec_libro = obtener_embedding(respuesta_libro)
                if vec_libro is not None and vec_bot is not None:
                    sim_rag = round(cosine_similarity(vec_libro, vec_bot)[0][0], 4)

        # 3. Clasificación
        if respuesta_bot.startswith("Error") or sim_ideal < UMBRAL_COSENO_POSITIVO:
            clasificacion = "FN" 
        else:
            clasificacion = "VP" 

        # Guardado en DataFrame
        df.at[index, "respuesta_sistema"] = respuesta_bot
        df.at[index, "tiempo_segundos"] = tiempo_total
        df.at[index, "similitud_ideal"] = sim_ideal
        df.at[index, "fidelidad_rag"] = sim_rag
        df.at[index, "clasificacion"] = clasificacion

    # Guardar resultados brutos (por pregunta)
    df.to_csv(ARCHIVO_RESULTADOS, index=False, encoding='utf-8')
    
    # === CÁLCULO DE MÉTRICAS Y VARIANZA GLOBAL ===
    print("\n" + "="*50)
    print("MÉTRICAS UNIFICADAS Y VARIANZA POR ASISTENTE")
    print("="*50)
    
    agentes = df['asistente'].unique()
    resultados_estadisticos = []
    
    for agente in agentes:
        df_agente = df[df['asistente'] == agente]
        n_preguntas = len(df_agente)
        
        # Calcular VP y FN
        vp = len(df_agente[df_agente['clasificacion'] == 'VP'])
        fn = len(df_agente[df_agente['clasificacion'] == 'FN'])
        fp = 0 
        
        precision = vp / (vp + fp) if (vp + fp) > 0 else 0.0
        recall = vp / (vp + fn) if (vp + fn) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        # VARIANZAS SEGUROS (Si hay error matemático, pone 0.0)
        try: var_sim = round(df_agente['similitud_ideal'].var(ddof=1), 4)
        except: var_sim = 0.0
        
        try: var_rag = round(df_agente['fidelidad_rag'].var(ddof=1), 4)
        except: var_rag = 0.0
            
        try: var_lat = round(df_agente['tiempo_segundos'].var(ddof=1), 4)
        except: var_lat = 0.0
        
        # Promedios clásicos de tu script
        coseno_promedio = df_agente['similitud_ideal'].mean()
        tiempo_promedio = df_agente['tiempo_segundos'].mean()
        
        print(f"\n[{agente.upper()}]")
        print(f"  - Precisión: {precision:.2f} | Recall: {recall:.2f} | F1-Score: {f1_score:.2f}")
        print(f"  - Similitud (Media): {coseno_promedio:.4f} | Varianza: {var_sim}")
        print(f"  - Fidelidad RAG (Varianza): {var_rag}")
        print(f"  - Latencia (Media): {tiempo_promedio:.2f} s | Varianza: {var_lat}")
        
        # Almacenar para el reporte final
        resultados_estadisticos.append({
            "Asistente": agente,
            "Total_Preguntas": n_preguntas,
            "Precision": precision,
            "Recall": recall,
            "F1_Score": f1_score,
            "Varianza_Similitud": var_sim,
            "Varianza_Fidelidad_RAG": var_rag,
            "Varianza_Latencia": var_lat
        })

    # Guardar métricas agrupadas en el nuevo CSV
    df_metricas = pd.DataFrame(resultados_estadisticos)
    df_metricas.to_csv(ARCHIVO_METRICAS_AGENTE, index=False, encoding='utf-8')
    print(f"\n¡Proceso finalizado! Varianzas y métricas guardadas en {ARCHIVO_METRICAS_AGENTE}")

if __name__ == "__main__":
    ejecutar_pruebas_fase1()