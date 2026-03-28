from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import ollama
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LingoNaut Translation Backend")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
MODEL_NAME = "mistral:latest"   # Cambia si quieres usar otro

client = ollama.Client(host=OLLAMA_HOST)

class TranslationRequest(BaseModel):
    message: str
    session_id: str = None

@app.get("/health")
async def health():
    return {"status": "ready", "model": MODEL_NAME}

@app.post("/chat")
async def chat(request: TranslationRequest):
    try:
        logger.info(f"Traduciendo: {request.message[:100]}...")

        response = client.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": request.message}],
            options={"temperature": 0.3, "num_predict": 1024}
        )

        reply = response['message']['content'].strip()
        return {"response": reply}

    except Exception as e:
        logger.error(f"Error en traducción: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)