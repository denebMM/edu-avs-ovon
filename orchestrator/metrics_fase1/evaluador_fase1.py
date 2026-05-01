import pandas as pd
import requests
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import json
import uuid
from datetime import datetime
import os

# ================= CONFIGURACIÓN =================

# Esto detecta en qué carpeta está guardado este script de Python
directorio_actual = os.path.dirname(os.path.abspath(__file__))

# Esto une la ruta de la carpeta con el nombre de tu archivo
ARCHIVO_DATASET = os.path.join(directorio_actual, "dataset_fase1.csv")
ARCHIVO_RESULTADOS = os.path.join(directorio_actual, "resultados_fase1.csv")
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODELO_EMBEDDING = "qwen:4b" 

def obtener_embedding(texto):
    """Llama a Ollama para convertir texto en un vector matemático."""
    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODELO_EMBEDDING, "prompt": texto})
        return np.array(resp.json()["embedding"]).reshape(1, -1)
    except Exception as e:
        print(f"Error al obtener embedding: {e}")
        return None

def armar_payload_ofp(pregunta):
    """Arma el JSON estricto del protocolo OFP 1.1.0 que esperan tus wrappers."""
    conversation_id = str(uuid.uuid4())
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"}, # <-- OBLIGATORIO PARA EVITAR ERROR 500
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": "tag:evaluator.local,2026:tester001"}, # <-- OBLIGATORIO
            "events": [
                {
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": "tag:user.local,2026:user001",
                            "features": {
                                "text": {
                                    "mimeType": "text/plain",
                                    "tokens": [{"value": pregunta}]
                                }
                            }
                        }
                    }
                }
            ]
        }
    }

def ejecutar_pruebas():
    print(" _Iniciando Evaluación Automatizada de Fase 1...")
    
    # Manejo seguro de la codificación al leer el dataset
    try:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='latin1')
    
    # <-- CORRECCIÓN: Limpiamos filas vacías para evitar errores al final del bucle
    df = df.dropna(subset=['asistente']) 
    
    # Nuevas columnas para guardar los resultados
    df["respuesta_sistema"] = ""
    df["tiempo_segundos"] = 0.0
    df["similitud_coseno"] = 0.0

    for index, row in df.iterrows():
        asistente = str(row['asistente']).strip()
        puerto = int(row['puerto'])
        pregunta = str(row['pregunta'])
        respuesta_ideal = str(row['respuesta_ideal'])
        
        print(f"[{index+1}/{len(df)}] Probando {asistente.upper()}: {pregunta[:30]}...")

        url_asistente = f"http://localhost:{puerto}/receive"
        payload = armar_payload_ofp(pregunta)

        # 1. Medir tiempo y hacer la petición
        inicio = time.time()
        try:
            resp = requests.post(url_asistente, json=payload, timeout=180) # Aumenté timeout a 3 min por si acaso
            resp.raise_for_status() # Lanza un error si el servidor no devuelve código 200
            data = resp.json()
            # Extraer la respuesta del formato OFP del wrapper
            respuesta_bot = data.get('openFloor', {}).get('events', [{}])[0].get('parameters', {}).get('dialogEvent', {}).get('features', {}).get('text', {}).get('tokens', [{}])[0].get('value', 'Error: Formato OFP inesperado')
        except Exception as e:
            respuesta_bot = f"Error: {e}"
        fin = time.time()
        
        tiempo_total = round(fin - inicio, 2)

        # 2. Calcular Similitud del Coseno usando Ollama
        similitud = 0.0
        if not respuesta_bot.startswith("Error"):
            vec_ideal = obtener_embedding(respuesta_ideal)
            vec_bot = obtener_embedding(respuesta_bot)
            
            if vec_ideal is not None and vec_bot is not None:
                # Calcula el ángulo entre los dos textos
                similitud = cosine_similarity(vec_ideal, vec_bot)[0][0]
                similitud = round(similitud, 4)

        # 3. Guardar en el DataFrame
        df.at[index, "respuesta_sistema"] = respuesta_bot
        df.at[index, "tiempo_segundos"] = tiempo_total
        df.at[index, "similitud_coseno"] = similitud

    # Guardar resultados en un nuevo CSV de forma segura
    df.to_csv(ARCHIVO_RESULTADOS, index=False, encoding='utf-8')
    print(f"\n__ Evaluación completada. Resultados guardados en {ARCHIVO_RESULTADOS}")
    
    # Mostrar resumen rápido
    print("\n ____* RESUMEN PROMEDIO POR ASISTENTE:")
    resumen = df.groupby('asistente')[['similitud_coseno', 'tiempo_segundos']].mean()
    print(resumen)

if __name__ == "__main__":
    ejecutar_pruebas()