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

# Validación de variables
required_env_vars = ["API_KEY", "OLLAMA_MODEL"]
for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} no encontrada en el entorno")

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
    raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="API Key Inválida")

# ==================== OLLAMA CONFIG ====================
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

def ollama_chat(messages, temperature=0.6, max_tokens=1200):
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
        logger.error(f"Error en Ollama: {e}")
        raise

# ==================== LÓGICA SYMPY BÁSICA ====================
def solve_basic_math_with_sympy(user_query: str):
    """
    Resuelve aritmética, fracciones y ecuaciones de 1er grado con SymPy.
    """
    try:
        # 1. Limpieza para SymPy (potencias y minúsculas)
        clean_expr = user_query.replace("^", "**").lower()
        
        # 2. Regex para detectar números, x, y operadores básicos
        math_match = re.search(r"([0-9x\+\-\*\/\^\(\)\=\.\s]+)", clean_expr)
        
        if math_match:
            target = math_match.group(1).strip()
            if len(target) < 3: return None

            # Si hay un "=" es una ecuación
            if "=" in target:
                parts = target.split("=")
                lhs = sp.sympify(parts[0])
                rhs = sp.sympify(parts[1])
                # Resolvemos para x por defecto
                result = sp.solve(sp.Eq(lhs, rhs), sp.Symbol('x'))
                return f"**Resultado de la ecuación (SymPy):** $x = {sp.latex(result[0])}$" if result else None
            
            else:
                # Es una expresión aritmética o simplificación de fracciones
                expr = sp.sympify(target)
                result = sp.simplify(expr)
                # Si el resultado es igual al target, no aportó nada nuevo
                if str(result) == target.replace(" ", ""): return None
                return f"**Cálculo exacto (SymPy):** $${sp.latex(result)}$$"
        
        return None
    except Exception:
        return None

# ==================== SYSTEM PROMPT (Personalidad) ====================
SYSTEM_PROMPT = """Eres MathBuddy Básico, un tutor amigable de matemáticas (Primaria a 2° Secundaria).
REGLAS:
- Responde siempre en español, con un tono amable para niños.
- Usa KaTeX ($...$ y $$...$$).
- COLABORACIÓN: Si recibes contexto de 'physics', úsalo para hacer las cuentas básicas.
- Si la pregunta es avanzada (derivadas, integrales), indica que debe ir con MathBuddy Avanzado."""

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
        # 1. Respuesta pedagógica (Ollama)
        bot_message = ollama_chat(session["messages"])
        
        # 2. Validación matemática (SymPy)
        sympy_validation = solve_basic_math_with_sympy(query.message)
        
        # 3. Integración
        if sympy_validation:
            bot_message += f"\n\n---\n{sympy_validation}"

        session["messages"].append({"role": "assistant", "content": bot_message})
        
        if len(session["messages"]) > 10:
            session["messages"] = [session["messages"][0]] + session["messages"][-5:]

        return {"response": bot_message}
    
    except Exception as e:
        logger.error(f"Error en chat básico: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

if __name__ == "__main__":
    import uvicorn
    # IMPORTANTE: host debe ser 0.0.0.0 para que Docker permita conexiones externas
    uvicorn.run(app, host="0.0.0.0", port=8080)