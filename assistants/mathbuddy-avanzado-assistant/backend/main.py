import os
from dotenv import load_dotenv
import logging
import uuid
import json
import re
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
from datetime import datetime, timedelta

import sympy as sp
from sympy import latex
import ollama

load_dotenv()

# Validaciones básicas
required_env_vars = ["API_KEY", "OLLAMA_MODEL"]
for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} not found in environment variables")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Query(BaseModel):
    message: str
    session_id: str

sessions: Dict[str, Dict[str, Any]] = {}

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key_header: str = Depends(api_key_header)):
    if api_key_header == os.getenv("API_KEY"):
        return api_key_header
    raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Invalid API KEY")

# ==================== OLLAMA CLIENT ====================
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

def ollama_chat(messages, temperature=0.5, max_tokens=1500):
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_gpu": -1
            }
        )
        return response['message']['content']
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        return "Error conectando con el cerebro del asistente."

# ==================== LÓGICA SYMPY (AQUÍ ESTÁ) ====================
def solve_math_with_sympy(user_query: str):
    """
    Extrae la expresión matemática y la resuelve con SymPy para asegurar precisión.
    """
    try:
        # 1. Limpieza básica de la query para SymPy
        clean_expr = user_query.replace("^", "**").lower()
        
        # 2. Intentamos extraer una expresión matemática (números, x, operadores)
        # Este regex busca patrones matemáticos comunes
        math_parts = re.findall(r"([0-9x\+\-\*\/\^\(\)\.sincostanlog]+)", clean_expr)
        
        if math_parts:
            # Tomamos la cadena más larga que parezca una fórmula
            target = max(math_parts, key=len)
            if len(target) < 3: return None # Demasiado corto para ser una expresión

            expr = sp.sympify(target)
            x = sp.Symbol('x')
            
            # 3. Decidir operación según palabras clave
            if any(kw in clean_expr for kw in ["deriva", "derivative", "diferencia"]):
                result = sp.diff(expr, x)
                return f"**Resultado exacto (Derivada):** $${sp.latex(result)}$$"
            
            elif any(kw in clean_expr for kw in ["integra", "integral"]):
                result = sp.integrate(expr, x)
                return f"**Resultado exacto (Integral):** $${sp.latex(result)} + C$$"
            
            elif any(kw in clean_expr for kw in ["límite", "limit"]):
                # Asumimos límite a cero por defecto si no se especifica, 
                # o podrías ampliar la lógica aquí.
                result = sp.limit(expr, x, 0)
                return f"**Resultado exacto (Límite cuando $x \\to 0$):** $${sp.latex(result)}$$"
            
            else:
                result = sp.simplify(expr)
                return f"**Resultado simplificado:** $${sp.latex(result)}$$"
        return None
    except Exception as e:
        logger.error(f"SymPy error: {e}")
        return None

# ==================== SYSTEM PROMPT AVANZADO ====================
SYSTEM_PROMPT = """Eres MathBuddy Avanzado. Tu especialidad es secundaria alta y Cálculo 1.
REGLAS:
1. Responde en español, usando KaTeX ($...$ y $$...$$).
2. COLABORACIÓN: Si recibes aportes de 'physics' o 'math_basico', úsalos. Eres el experto que finaliza los cálculos complejos.
3. No uses saludos. Sé técnico, educativo y directo."""

# ==================== ENDPOINTS ====================

@app.post("/chat")
async def chat(query: Query, api_key: str = Depends(get_api_key)):
    if query.session_id not in sessions:
        sessions[query.session_id] = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}]
        }
    
    session = sessions[query.session_id]
    session["messages"].append({"role": "user", "content": query.message})
    
    try:
        # 1. Obtener explicación pedagógica de Ollama
        bot_message = ollama_chat(session["messages"])
        
        # 2. Obtener validación matemática de SymPy
        #sympy_validation = solve_math_with_sympy(query.message)
        
        # 3. Si SymPy tuvo éxito, lo pegamos al final de la respuesta
        # if sympy_validation:
        #     bot_message += f"\n\n---\n{sympy_validation}"

        session["messages"].append({"role": "assistant", "content": bot_message})
        # ...
        return {"response": bot_message}
        
    except Exception as e:
        logger.error(f"Error en chat avanzado: {e}")
        return {"response": "Lo siento, tuve un problema procesando ese cálculo avanzado."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)