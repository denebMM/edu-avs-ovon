import pandas as pd
import requests
import json
import os
import time
import uuid

# =========================================================
# CONFIGURACIÓN DE RUTAS DINÁMICAS
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATH_DATASET = os.path.join(BASE_DIR, "dataset_preguntas.csv")
PATH_RESULTADOS = os.path.join(BASE_DIR, "respuestas_asistentes_real.csv")

def normalizar_texto(texto):
    if not isinstance(texto, str): return texto
    try:
        # Intenta reparar el texto si viene con basura de Latin-1
        return texto.encode('latin-1').decode('utf-8')
    except:
        return texto.strip()

def recolectar_respuestas():
    if not os.path.exists(PATH_DATASET):
        print(f"❌ Error: No se encontró '{PATH_DATASET}'")
        return

    # 1. Carga resiliente
    try:
        df = pd.read_csv(PATH_DATASET, encoding='latin-1')
    except Exception:
        df = pd.read_csv(PATH_DATASET, encoding='utf-8', errors='replace')

    # 2. Saneamiento usando .loc para evitar los 'SettingWithCopyWarning'
    # Eliminar columnas Unnamed
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')].copy()
    
    # Limpiar nombres de columnas
    df.columns = df.columns.str.strip()

    # Aplicar saneamiento de texto a las columnas de forma segura
    df.loc[:, 'pregunta'] = df['pregunta'].apply(normalizar_texto)
    if 'asistente' in df.columns:
        df.loc[:, 'asistente'] = df['asistente'].str.strip().str.lower()

    # Inicializar columnas nuevas de forma explícita
    df.loc[:, "respuesta_obtenida"] = ""
    df.loc[:, "latencia_segundos"] = 0.0

    print(f"🚀 Iniciando recolección de {len(df)} respuestas saneadas...")

    for index, row in df.iterrows():
        puerto = row['puerto']
        pregunta = row['pregunta']
        asistente = row['asistente']
        
        url = f"http://localhost:{puerto}/receive"

        payload = {
            "openFloor": {
                "schema": {"version": "1.1.0"},
                "conversation": {"id": str(uuid.uuid4())},
                "sender": {"speakerUri": "tag:evaluator.local,2026:tester001"},
                "events": [{
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
                }]
            }
        }

        print(f"[{index + 1}/{len(df)}] Consultando {asistente} (Puerto {puerto})...", end="\r")

        inicio_timer = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()

            # Extraer respuesta del sobre OFP
            eventos = data.get('openFloor', {}).get('events', [])
            respuesta_bot = "Sin respuesta en JSON"
            
            for ev in eventos:
                if ev.get('eventType') == 'utterance':
                    respuesta_bot = ev['parameters']['dialogEvent']['features']['text']['tokens'][0]['value']
                    break
            
            df.at[index, "respuesta_obtenida"] = respuesta_bot

        except Exception as e:
            df.at[index, "respuesta_obtenida"] = f"ERROR: {str(e)}"

        df.at[index, "latencia_segundos"] = round(time.time() - inicio_timer, 2)

    # 3. Guardado con UTF-8-SIG (Compatible con Excel/Windows)
    df.to_csv(PATH_RESULTADOS, index=False, encoding='utf-8-sig')
    print(f"\n\n✅ Proceso completado sin advertencias.")
    print(f"📄 Archivo generado: {PATH_RESULTADOS}")

if __name__ == "__main__":
    recolectar_respuestas()