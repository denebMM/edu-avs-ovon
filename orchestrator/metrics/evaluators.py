# evaluadores automáticos
# metrics/evaluators.py
# Funciones para calcular métricas automáticas o semi-automáticas

import pandas as pd
from pathlib import Path

def calculate_accuracy_from_csv(csv_path):
    """
    Calcula la accuracy de clasificación comparando 'classified_as' vs una columna esperada.
    Requiere que en tu CSV de pruebas tengas una columna 'expected_categories'.
    """
    df = pd.read_csv(csv_path)
    if 'expected_categories' not in df.columns:
        raise ValueError("Necesitas una columna 'expected_categories' en el CSV para calcular accuracy")
    
    correct = 0
    total = len(df)
    for _, row in df.iterrows():
        predicted = set(row['classified_as'].split(', '))
        expected = set(row['expected_categories'].split(', '))
        if predicted == expected:
            correct += 1
    
    accuracy = correct / total if total > 0 else 0
    print(f"Accuracy de clasificación: {accuracy:.2%} ({correct}/{total})")
    return accuracy

def calculate_average_latency(csv_path):
    """Calcula latencia promedio de todas las queries en el CSV"""
    df = pd.read_csv(csv_path)
    if 'total_latency_sec' in df.columns:
        avg_latency = df['total_latency_sec'].mean()
        print(f"Latencia promedio: {avg_latency:.2f} segundos")
        return avg_latency
    return None

# añadir más evaluadores aquí en el futuro:
# - % de chaining exitoso
# - % de envelopes válidos
# - etc.