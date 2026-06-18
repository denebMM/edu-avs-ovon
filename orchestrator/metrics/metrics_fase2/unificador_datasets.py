import pandas as pd
import numpy as np
import os

def unificar_archivos():
    print("Iniciando unificación de los 7 lotes...\n")
    
    lista_preguntas = []
    lista_agentes = []
    
    # 1. Leer los archivos del 1 al 7
    for i in range(1, 8):
        file_preguntas = f"OK/resultados_fase2_detalle_preguntas_{i}_5.csv"
        file_agentes = f"OK/resultados_fase2_metricas_agentes_{i}_5.csv"
        
        # Unir preguntas
        if os.path.exists(file_preguntas):
            df_p = pd.read_csv(file_preguntas, encoding='utf-8-sig')
            lista_preguntas.append(df_p)
        else:
            print(f"[Advertencia] No se encontró {file_preguntas}")
            
        # Unir agentes
        if os.path.exists(file_agentes):
            df_a = pd.read_csv(file_agentes, encoding='utf-8-sig')
            lista_agentes.append(df_a)

    # ========================================================
    # 1. CREAR EL DATASET MAESTRO DE PREGUNTAS (35 Preguntas)
    # ========================================================
    if lista_preguntas:
        df_preguntas_final = pd.concat(lista_preguntas, ignore_index=True)
        df_preguntas_final.to_csv("DATASET_FINAL_35_PREGUNTAS.csv", index=False, encoding='utf-8-sig')
        print(f"✅ ¡Éxito! Se unificaron {len(df_preguntas_final)} preguntas en 'DATASET_FINAL_35_PREGUNTAS.csv'")
    
    # ========================================================
    # 2. RECALCULAR MÉTRICAS GLOBALES MATEMÁTICAMENTE EXACTAS
    # ========================================================
    if lista_preguntas:
        # Extraer métricas de ruteo
        precision = df_preguntas_final['precision_ruteo']
        recall = df_preguntas_final['recall_ruteo']
        f1 = df_preguntas_final['f1_score_ruteo']
        latencia = df_preguntas_final['latencia_global_segundos']
        
        # Filtrar los errores de embedding para calcular bien el coseno
        df_valid_cos = df_preguntas_final[df_preguntas_final['coseno_global'] != 'ERROR_EMBEDDING'].copy()
        df_valid_cos['coseno_global'] = df_valid_cos['coseno_global'].astype(float)
        coseno = df_valid_cos['coseno_global']

        datos_globales = [
            {"Metrica": "Precision de Ruteo", "Media": round(precision.mean(), 4), "Varianza": round(precision.var(ddof=1), 4)},
            {"Metrica": "Recall de Ruteo", "Media": round(recall.mean(), 4), "Varianza": round(recall.var(ddof=1), 4)},
            {"Metrica": "F1-Score de Ruteo", "Media": round(f1.mean(), 4), "Varianza": round(f1.var(ddof=1), 4)},
            {"Metrica": "Similitud Coseno End-to-End", "Media": round(coseno.mean(), 4), "Varianza": round(coseno.var(ddof=1), 4)},
            {"Metrica": "Latencia Global Total", "Media": round(latencia.mean(), 2), "Varianza": round(latencia.var(ddof=1), 4)}
        ]
        
        df_global_final = pd.DataFrame(datos_globales)
        df_global_final.to_csv("METRICAS_GLOBALES_FINAL.csv", index=False, encoding='utf-8-sig')
        print("✅ ¡Éxito! Se recalcularon las métricas globales en 'METRICAS_GLOBALES_FINAL.csv'")

    # ========================================================
    # 3. UNIFICAR Y PROMEDIAR MÉTRICAS DE AGENTES
    # ========================================================
    if lista_agentes:
        df_agentes_total = pd.concat(lista_agentes, ignore_index=True)
        # Agrupar por el nombre del agente y sacar el promedio de todas sus ejecuciones
        df_agentes_final = df_agentes_total.groupby('Agente').mean().reset_index()
        
        # Redondear para que se vea estético en tu tesis
        df_agentes_final = df_agentes_final.round(4)
        
        df_agentes_final.to_csv("METRICAS_AGENTES_FINAL.csv", index=False, encoding='utf-8-sig')
        print("✅ ¡Éxito! Se consolidó el rendimiento de los agentes en 'METRICAS_AGENTES_FINAL.csv'")

if __name__ == "__main__":
    unificar_archivos()