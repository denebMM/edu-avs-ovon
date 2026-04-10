import time
import json
import uuid
from datetime import datetime
import pandas as pd
from pathlib import Path

class MetricsCollector:
    def __init__(self, storage_path="metrics"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        self.current_run_id = str(uuid.uuid4())[:8]

    def record_query(self, query, intents, strategy, responses_map, final_envelope, total_time):
        """
        Registra la consulta. 
        Nota: responses_map es un dict {agente: respuesta}
        """
        # Formateamos las respuestas para el CSV como un string JSON legible
        responses_json_str = json.dumps(responses_map, ensure_ascii=False)

        record = {
            "run_id": self.current_run_id,
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "strategy_used": strategy,
            "classified_as": ", ".join(intents) if isinstance(intents, list) else str(intents),
            "agents_used": ", ".join(responses_map.keys()),
            "total_latency_sec": round(total_time, 3),
            "envelope_valid": "openFloor" in final_envelope,
            "num_agents": len(responses_map),
            "has_chaining": strategy == "sequential" and len(responses_map) > 1,
            "responses_detail": responses_json_str  # Guardado como string para compatibilidad CSV
        }

        # === Guardar en CSV ===
        try:
            df = pd.DataFrame([record])
            csv_path = self.storage_path / f"metrics_run_{self.current_run_id}.csv"
            df.to_csv(csv_path, mode='a', header=not csv_path.exists(), index=False, encoding='utf-8-sig')
        except Exception as e:
            print(f"Error escribiendo CSV: {e}")

        # === Guardar JSON detallado (Para análisis profundo) ===
        # Aquí guardamos el record original con el diccionario real, no el string
        record["responses_detail"] = responses_map 
        json_filename = f"query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(self.storage_path / json_filename, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        return record