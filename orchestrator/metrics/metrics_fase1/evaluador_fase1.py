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
ARCHIVO_DATASET = os.path.join(directorio_actual, "dataset_individual.csv") # Asegúrate de que este archivo exista
ARCHIVO_RESULTADOS = os.path.join(directorio_actual, "resultados_fase1_completo_mistral.csv")
ARCHIVO_METRICAS_AGENTE = os.path.join(directorio_actual, "metricas_agentes_fase1_mistral.csv")

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODELO_EMBEDDING = "nomic-embed-text"

# Ajuste 3: Umbral incrementado a 0.75 para mayor rigor en la evaluación de VP/FN
UMBRAL_COSENO_POSITIVO = 0.75 

# ================= FUNCIONES =================
def obtener_embedding(texto, max_reintentos=3):
    """Obtiene el embedding de Ollama, con reintentos si el servidor local se satura."""
    if not isinstance(texto, str) or not texto.strip() or str(texto).lower() == 'nan':
        return None
        
    texto_seguro = texto[:1500] 
    
    for intento in range(max_reintentos):
        try:
            resp = requests.post(
                OLLAMA_URL, 
                json={"model": MODELO_EMBEDDING, "prompt": texto_seguro}, 
                timeout=30
            )
            resp.raise_for_status()
            return np.array(resp.json()["embedding"]).reshape(1, -1)
        except requests.exceptions.RequestException as e:
            print(f"   [⚠️] Ollama saturado. Reintentando en 3 seg... (Intento {intento+1}/{max_reintentos})")
            time.sleep(3) # Pausa táctica para que Ollama libere RAM
            
    print(f"   [❌] Fallo definitivo al obtener embedding tras {max_reintentos} intentos.")
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
    print("Iniciando Evaluación Completa de Fase 1 (Entorno Heterogéneo)...")
    
    # --- 1. LECTURA ROBUSTA DEL CSV ---
    df = None
    codificaciones = ['utf-8-sig', 'utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    
    for cod in codificaciones:
        try:
            df = pd.read_csv(ARCHIVO_DATASET, encoding=cod, sep=None, engine='python')
            print(f"Archivo leído exitosamente usando codificación: {cod}")
            break
        except Exception:
            continue
            
    if df is None:
        raise ValueError(" No se pudo leer el archivo CSV.")

    df.columns = df.columns.str.strip().str.lower().str.replace('"', '').str.replace("'", "")
    
    if 'asistente' not in df.columns:
        raise ValueError("Error: No se encontró la columna 'asistente'.")

    df = df.dropna(subset=['asistente']) 
    
    # --- 2. PREPARACIÓN DE NUEVAS COLUMNAS (MÉTRICAS POR PREGUNTA) ---
    df["respuesta_sistema"] = ""
    df["tiempo_segundos"] = 0.0
    df["similitud_ideal"] = 0.0 
    
    # Ajuste 1: Renombre de fidelidad_rag a fidelidad_fuente para ser agnóstico a la arquitectura
    df["fidelidad_fuente"] = 0.0 
    df["clasificacion"] = "" 
    df["precision_individual"] = 0.0  
    df["recall_individual"] = 0.0     
    df["f1_score_individual"] = 0.0   

    columna_libro = None
    for col in df.columns:
        if 'libro' in col:
            columna_libro = col
            break

    # --- 3. CICLO DE EVALUACIÓN ---
    for index, row in df.iterrows():
        asistente = str(row['asistente']).strip()
        
        try:
            puerto = int(float(row['puerto']))
        except (ValueError, TypeError):
            continue
            
        pregunta = str(row['pregunta'])
        
        respuesta_libro = str(row[columna_libro]) if columna_libro else ""
        respuesta_ideal = respuesta_libro 
        
        print(f"[{index+1}/{len(df)}] {asistente.upper()}: Evaluando...")

        url = f"http://localhost:{puerto}/receive"
        payload = armar_payload_ofp(pregunta)

        # Medir Latencia
        inicio = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            respuesta_bot = data.get('openFloor', {}).get('events', [{}])[0].get('parameters', {}).get('dialogEvent', {}).get('features', {}).get('text', {}).get('tokens', [{}])[0].get('value', 'Error')
        except Exception as e:
            respuesta_bot = f"Error: {e}"
        tiempo_total = round(time.time() - inicio, 2)

        # Medir Similitudes Vectoriales
        sim_ideal = 0.0
        sim_fuente = 0.0 # Ajuste 1
        
        if not respuesta_bot.startswith("Error"):
            vec_bot = obtener_embedding(respuesta_bot)
            vec_ideal = obtener_embedding(respuesta_ideal)
            
            if vec_ideal is not None and vec_bot is not None:
                sim_ideal = round(cosine_similarity(vec_ideal, vec_bot)[0][0], 4)
            
            if columna_libro and respuesta_libro.strip():
                vec_libro = obtener_embedding(respuesta_libro)
                if vec_libro is not None and vec_bot is not None:
                    sim_fuente = round(cosine_similarity(vec_libro, vec_bot)[0][0], 4) # Ajuste 1

        # Clasificación y Métricas Individuales (utiliza el nuevo umbral estricto)
        if respuesta_bot.startswith("Error") or sim_ideal < UMBRAL_COSENO_POSITIVO:
            clasificacion = "FN" 
            prec_ind = 0.0
            rec_ind = 0.0
            f1_ind = 0.0
        else:
            clasificacion = "VP" 
            prec_ind = 1.0
            rec_ind = 1.0
            f1_ind = 1.0

        # Guardar en DataFrame
        df.at[index, "respuesta_sistema"] = respuesta_bot
        df.at[index, "tiempo_segundos"] = tiempo_total
        df.at[index, "similitud_ideal"] = sim_ideal
        df.at[index, "fidelidad_fuente"] = sim_fuente # Ajuste 1
        df.at[index, "clasificacion"] = clasificacion
        df.at[index, "precision_individual"] = prec_ind
        df.at[index, "recall_individual"] = rec_ind
        df.at[index, "f1_score_individual"] = f1_ind

    # Guardar resultados detallados
    df.to_csv(ARCHIVO_RESULTADOS, index=False, encoding='utf-8-sig')
    
    # --- 4. CÁLCULO DE MÉTRICAS ESTADÍSTICAS POR ASISTENTE ---
    print("\n" + "="*60)
    print("MÉTRICAS UNIFICADAS Y VARIANZA POR ASISTENTE")
    print("="*60)
    
    agentes = df['asistente'].unique()
    resultados_estadisticos = []
    
    for agente in agentes:
        df_agente = df[df['asistente'] == agente]
        n_preguntas = len(df_agente)
        
        # Ajuste 2: Identificar el tipo de arquitectura (RAG, Ollama, etc.) si la columna existe
        tipo_arq = df_agente['tipo_arquitectura'].iloc[0] if 'tipo_arquitectura' in df_agente.columns else "No especificada"

        # Métrica global del agente
        vp = len(df_agente[df_agente['clasificacion'] == 'VP'])
        fn = len(df_agente[df_agente['clasificacion'] == 'FN'])
        fp = 0 
        
        precision = vp / (vp + fp) if (vp + fp) > 0 else 0.0
        recall = vp / (vp + fn) if (vp + fn) > 0 else 0.0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        # Cálculo de Varianzas
        try: var_sim = round(df_agente['similitud_ideal'].var(ddof=1), 4)
        except: var_sim = 0.0
        
        try: var_fuente = round(df_agente['fidelidad_fuente'].var(ddof=1), 4) # Ajuste 1
        except: var_fuente = 0.0
            
        try: var_lat = round(df_agente['tiempo_segundos'].var(ddof=1), 4)
        except: var_lat = 0.0

        try: var_prec = round(df_agente['precision_individual'].var(ddof=1), 4)
        except: var_prec = 0.0

        try: var_f1 = round(df_agente['f1_score_individual'].var(ddof=1), 4)
        except: var_f1 = 0.0

        coseno_promedio = df_agente['similitud_ideal'].mean()
        tiempo_promedio = df_agente['tiempo_segundos'].mean()
        
        print(f"\n[{agente.upper()}] - {tipo_arq}")
        print(f"  - Precisión: {precision:.2f} (Var: {var_prec:.4f}) | Recall: {recall:.2f} | F1-Score: {f1_score:.2f} (Var: {var_f1:.4f})")
        print(f"  - Similitud (Media): {coseno_promedio:.4f} | Varianza: {var_sim}")
        print(f"  - Latencia (Media): {tiempo_promedio:.2f} s | Varianza: {var_lat}")
        
        # Diccionario con el mapeo correcto
        resultados_estadisticos.append({
            "Asistente": agente,
            "Arquitectura": tipo_arq, # Ajuste 2 integrado
            "Total_Preguntas": n_preguntas,
            "Precision_Global": precision,
            "Varianza_Precision": var_prec,
            "Recall_Global": recall,
            "F1_Score_Global": f1_score,
            "Varianza_F1_Score": var_f1,
            "Similitud_Media": coseno_promedio,
            "Varianza_Similitud": var_sim,
            "Fidelidad_Fuente_Media": df_agente['fidelidad_fuente'].mean(), # Ajuste 1
            "Varianza_Fidelidad_Fuente": var_fuente, # Ajuste 1
            "Latencia_Media": tiempo_promedio,
            "Varianza_Latencia": var_lat
        })

    # Guardar métricas agrupadas
    df_metricas = pd.DataFrame(resultados_estadisticos)
    df_metricas.to_csv(ARCHIVO_METRICAS_AGENTE, index=False, encoding='utf-8-sig')
    print(f"\n¡Proceso finalizado! Revisa el archivo '{os.path.basename(ARCHIVO_METRICAS_AGENTE)}'.")

if __name__ == "__main__":
    ejecutar_pruebas_fase1()