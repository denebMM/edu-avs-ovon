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
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODELO_EMBEDDING = "qwen:4b" 
UMBRAL_COSENO_POSITIVO = 0.50 # Si el coseno es menor a esto, se considera Falso Negativo

def obtener_embedding(texto):
    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODELO_EMBEDDING, "prompt": texto})
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
    print("Iniciando Evaluación Completa de Fase 1 (5 Métricas)...")
    
    try:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='latin1')
    
    df = df.dropna(subset=['asistente']) 
    
    # Nuevas columnas
    df["respuesta_sistema"] = ""
    df["tiempo_segundos"] = 0.0
    df["similitud_coseno"] = 0.0
    df["clasificacion"] = "" # VP, FN, FP.

    for index, row in df.iterrows():
        asistente = str(row['asistente']).strip()
        puerto = int(row['puerto'])
        pregunta = str(row['pregunta'])
        respuesta_ideal = str(row['respuesta_ideal'])
        
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

        # 2. Medir Similitud Semántica (Coseno)
        similitud = 0.0
        if not respuesta_bot.startswith("Error"):
            vec_ideal = obtener_embedding(respuesta_ideal)
            vec_bot = obtener_embedding(respuesta_bot)
            if vec_ideal is not None and vec_bot is not None:
                similitud = round(cosine_similarity(vec_ideal, vec_bot)[0][0], 4)

        # 3. Lógica para Precisión, Recall y F1 (Basado en el Coseno)
        # Asumimos que todas las preguntas en el dataset SON del tema (Esperamos Positivos)
        if respuesta_bot.startswith("Error"):
            clasificacion = "FN" # Falso Negativo (El bot falló al responder algo que debía saber)
        elif similitud >= UMBRAL_COSENO_POSITIVO:
            clasificacion = "VP" # Verdadero Positivo (Respondió bien)
        else:
            clasificacion = "FN" # Falso Negativo (Respondió basura o fuera de contexto)

        df.at[index, "respuesta_sistema"] = respuesta_bot
        df.at[index, "tiempo_segundos"] = tiempo_total
        df.at[index, "similitud_coseno"] = similitud
        df.at[index, "clasificacion"] = clasificacion

    # Guardar resultados brutos
    df.to_csv(ARCHIVO_RESULTADOS, index=False, encoding='utf-8')
    
    # === CÁLCULO DE MÉTRICAS GLOBALES POR ASISTENTE ===
    print("\n" + "="*50)
    print("MÉTRICAS UNIFICADAS POR ASISTENTE (FASE 1)")
    print("="*50)
    
    agentes = df['asistente'].unique()
    
    for agente in agentes:
        df_agente = df[df['asistente'] == agente]
        
        # Calcular VP y FN
        vp = len(df_agente[df_agente['clasificacion'] == 'VP'])
        fn = len(df_agente[df_agente['clasificacion'] == 'FN'])
        
        # En este dataset puro, asumimos FP = 0 (no le hemos hecho preguntas trampa aún)
        fp = 0 
        
        precision = vp / (vp + fp) if (vp + fp) > 0 else 0.0
        recall = vp / (vp + fn) if (vp + fn) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        coseno_promedio = df_agente['similitud_coseno'].mean()
        tiempo_promedio = df_agente['tiempo_segundos'].mean()
        
        print(f"\n[{agente.upper()}]")
        print(f"  - Precisión: {precision:.2f} | Recall: {recall:.2f} | F1-Score: {f1_score:.2f}")
        print(f"  - Coseno:    {coseno_promedio:.4f}")
        print(f"  - Latencia:  {tiempo_promedio:.2f} s")

if __name__ == "__main__":
    ejecutar_pruebas_fase1()