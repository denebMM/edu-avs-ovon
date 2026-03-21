# metrics/metrics_collector.py
# Clase principal que recolecta y guarda métricas de cada query procesada

import time
import json
import uuid
from datetime import datetime
import pandas as pd
from pathlib import Path

class MetricsCollector:
    def __init__(self, storage_path="metrics"):
        """
        Inicializa el recolector de métricas.
        - Crea la carpeta de almacenamiento si no existe
        - Genera un ID único para la sesión actual (run)
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)  # Crea carpeta si no existe
        self.current_run_id = str(uuid.uuid4())[:8]  # ID corto y único para esta ejecución

    def record_query(self, query, intents, responses_map, final_envelope, total_time):
        """
        Registra una consulta completa con métricas básicas automáticas.
        
        Parámetros:
        - query: texto original de la pregunta del usuario
        - intents: lista de categorías clasificadas (ej: ['translator', 'mathbuddy_avanzado'])
        - responses_map: diccionario {nombre_agente: texto_respuesta}
        - final_envelope: el JSON OFP completo que se devuelve
        - total_time: tiempo total en segundos que tardó todo el procesamiento
        
        Guarda:
        - Un registro en CSV (acumulativo)
        - Un JSON detallado por cada query (para debug)
        """
        record = {
            "run_id": self.current_run_id,                     # ID de esta corrida completa
            "timestamp": datetime.now().isoformat(),           # Fecha y hora exacta
            "query": query,                                    # Pregunta original
            "classified_as": ", ".join(intents),               # Categorías que eligió el clasificador
            "agents_used": list(responses_map.keys()),         # Lista de agentes que respondieron
            "total_latency_sec": round(total_time, 3),         # Tiempo total (orquestador completo)
            "envelope_valid": "openFloor" in final_envelope,   # ¿Cumple el schema básico?
            "num_agents": len(responses_map),                  # Cuántos agentes intervinieron
            "has_chaining": len(responses_map) > 1,            # ¿Hubo colaboración?
            "raw_responses": {                                     # Respuestas truncadas (para no guardar gigas)
                k: v[:200] + ("..." if len(v) > 200 else "") 
                for k, v in responses_map.items()
            }
        }

        # === Guardar en CSV (fácil de abrir en Excel o analizar con pandas) ===
        df = pd.DataFrame([record])
        csv_path = self.storage_path / f"metrics_run_{self.current_run_id}.csv"
        # Si el archivo ya existe, añade sin cabecera; si no, crea con cabecera
        df.to_csv(csv_path, mode='a', header=not csv_path.exists(), index=False)

        # === Guardar JSON detallado por cada query (útil para debug o revisión manual) ===
        json_filename = f"query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(self.storage_path / json_filename, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        return record  # Devuelve el registro por si quieres usarlo en otro lugar