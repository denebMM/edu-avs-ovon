import pandas as pd
import requests
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import json

# ================= CONFIGURACIÓN =================
ARCHIVO_DATASET = "dataset_hibrido.csv"
ARCHIVO_RESULTADOS = "resultados_orquestador.csv"
ORCHESTRATOR_URL = "http://localhost:5000/query"
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

def calcular_f1(agentes_esperados, agentes_reales):
    """Calcula Precisión, Recall y F1-Score comparando listas de agentes."""
    set_esperados = set(agentes_esperados)
    set_reales = set(agentes_reales)
    
    verdaderos_positivos = len(set_esperados.intersection(set_reales))
    falsos_positivos = len(set_reales - set_esperados)
    falsos_negativos = len(set_esperados - set_reales)
    
    precision = verdaderos_positivos / (verdaderos_positivos + falsos_positivos) if (verdaderos_positivos + falsos_positivos) > 0 else 0.0
    recall = verdaderos_positivos / (verdaderos_positivos + falsos_negativos) if (verdaderos_positivos + falsos_negativos) > 0 else 0.0
    
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return round(precision, 2), round(recall, 2), round(f1_score, 2)

def procesar_respuesta_ofp(data):
    """Extrae los agentes llamados y el texto combinado del JSON OFP."""
    agentes_llamados = []
    texto_combinado = ""
    
    eventos = data.get('openFloor', {}).get('events', [])
    for evento in eventos:
        if evento.get('eventType') == 'utterance':
            dialog_event = evento.get('parameters', {}).get('dialogEvent', {})
            
            # Extraer quién habló (Ej: "tag:physics.local,2026:agent001" -> "physics")
            speaker_uri = dialog_event.get('speakerUri', '')
            if "tag:" in speaker_uri and ".local" in speaker_uri:
                agente = speaker_uri.split("tag:")[1].split(".local")[0]
                agentes_llamados.append(agente)
                
            # Extraer lo que dijo y sumarlo al bloque final
            tokens = dialog_event.get('features', {}).get('text', {}).get('tokens', [])
            if tokens:
                texto_combinado += f"[{agente.upper()}]: " + tokens[0].get('value', '') + "\n\n"
                
    return agentes_llamados, texto_combinado.strip()

def ejecutar_evaluacion_orquestador():
    print("Iniciando Evaluación Híbrida del Orquestador (Fases 2 y 3)...")
    
    # Intentamos leer con diferentes codificaciones por seguridad
    try:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(ARCHIVO_DATASET, encoding='latin1')

    # Añadimos columnas para almacenar los resultados
    df["agentes_usados"] = ""
    df["precision"] = 0.0
    df["recall"] = 0.0
    df["f1_score"] = 0.0
    df["respuesta_sistema"] = ""
    df["similitud_coseno"] = 0.0
    df["latencia_segundos"] = 0.0

    for index, row in df.iterrows():
        pregunta = row['pregunta']
        respuesta_ideal = row['respuesta_ideal']
        agentes_esperados = [a.strip() for a in row['agentes_esperados'].split(',')]
        
        print(f"\n[{index+1}/{len(df)}] Petición Híbrida: {pregunta[:40]}...")
        print(f"   ↳ Esperando a: {agentes_esperados}")

        payload = {"query": pregunta}

        inicio = time.time()
        try:
            resp = requests.post(ORCHESTRATOR_URL, json=payload, timeout=300)
            data = resp.json()
            agentes_reales, respuesta_bot = procesar_respuesta_ofp(data)
        except Exception as e:
            print(f"   X Error en el Orquestador: {e}")
            agentes_reales = []
            respuesta_bot = "Error de conexión"
        fin = time.time()

        latencia = round(fin - inicio, 2)
        print(f"   ↳ Orquestador llamó a: {agentes_reales} en {latencia}s")

        # 1. Calcular F1 Score (Enrutamiento)
        precision, recall, f1 = calcular_f1(agentes_esperados, agentes_reales)

        # 2. Calcular Similitud del Coseno (Interoperabilidad)
        similitud = 0.0
        if agentes_reales and "Error" not in respuesta_bot:
            vec_ideal = obtener_embedding(respuesta_ideal)
            vec_bot = obtener_embedding(respuesta_bot)
            if vec_ideal is not None and vec_bot is not None:
                similitud = round(cosine_similarity(vec_ideal, vec_bot)[0][0], 4)
        
        print(f"   ↳ F1-Score: {f1} | Coseno: {similitud}")

        # Guardar en DataFrame
        df.at[index, "agentes_usados"] = ",".join(agentes_reales)
        df.at[index, "precision"] = precision
        df.at[index, "recall"] = recall
        df.at[index, "f1_score"] = f1
        df.at[index, "respuesta_sistema"] = respuesta_bot
        df.at[index, "similitud_coseno"] = similitud
        df.at[index, "latencia_segundos"] = latencia

    # Guardar CSV final
    df.to_csv(ARCHIVO_RESULTADOS, index=False, encoding='utf-8')
    
    print("\n" + "="*50)
    print(" _____RESULTADOS FINALES DEL ORQUESTADOR (PROMEDIOS)")
    print("="*50)
    print(f"Precisión media del Ruteo:   {df['precision'].mean():.2f}")
    print(f"Recall medio del Ruteo:      {df['recall'].mean():.2f}")
    print(f"F1-Score Global (Fase 2):    {df['f1_score'].mean():.2f}")
    print(f"Similitud Semántica (Fase 3):{df['similitud_coseno'].mean():.4f}")
    print(f"Latencia promedio:           {df['latencia_segundos'].mean():.2f} segundos")
    print(f"Resultados guardados en: {ARCHIVO_RESULTADOS}")

if __name__ == "__main__":
    ejecutar_evaluacion_orquestador()