import os
from dotenv import load_dotenv
import logging
import uuid
import json
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any
from openai import OpenAI
import requests
import re
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Check for required environment variables
required_env_vars = ["OPENAI_API_KEY", "WOLFRAM_ALPHA_APP_ID", "API_KEY", "FRONTEND_URL"]
for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} not found in environment variables")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Query(BaseModel):
    message: str
    session_id: str

class SessionResponse(BaseModel):
    session_id: str

# In-memory session storage (replace with a database in production)
sessions: Dict[str, Dict[str, Any]] = {}

# Rate limiting
RATE_LIMIT = 50  # requests per day
rate_limit_data: Dict[str, Dict[str, Any]] = {}

# API key security
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key_header: str = Depends(api_key_header)):
    expected_api_key = os.getenv("API_KEY")
    logger.info(f"Received API Key: {api_key_header}, Expected: {expected_api_key}")  # Debug print
    if api_key_header == expected_api_key:
        return api_key_header
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, detail="Could not validate API KEY"
    )

# Initialize OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are MathBuddy, a concise AI math tutor for topics from 3rd grade to Calculus 1. Your primary goals are:

1. Be extremely brief and to the point in all responses.
2. Use only KaTeX syntax for formatting. Inline formulas use single dollar signs ($...$) and display formulas use double dollar signs ($$...$$).
3. Do not use any Markdown formatting. Only plain text and KaTeX are allowed.
4. Guide students with brief questions and hints, never solving problems directly.
5. For calculations, use: "Wolfram Alpha query: [query]" format.
6. After Wolfram Alpha results, briefly interpret and confirm correctness.
7. Adapt complexity to the student's level without mentioning difficulty explicitly.
8. Silently assess topic and difficulty (1-10) after each response to adjust your approach.

Remember: Brevity is key. Use KaTeX only. No Markdown.
"""

def query_wolfram_alpha(query: str) -> str:
    base_url = "https://www.wolframalpha.com/api/v1/llm-api"
    
    # Remove square brackets and strip whitespace
    clean_query = query.strip("[]").strip()
    
    params = {
        "input": clean_query,
        "appid": os.getenv("WOLFRAM_ALPHA_APP_ID"),
    }
    try:
        response = requests.get(base_url, params=params)
        
        if response.status_code != 200:
            return f"Error querying Wolfram Alpha: Status code {response.status_code}. Response: {response.text[:200]}"
        
        result = response.text.strip()
        return result
    except Exception as e:
        return f"Error processing Wolfram Alpha response: {str(e)}"

def extract_wolfram_result(wolfram_response: str) -> str:
    extraction_prompt = f"""
    Extract only the essential mathematical result from the following Wolfram Alpha response. 
    Provide the result in LaTeX format, enclosed in double dollar signs ($$...$$), without any additional explanation or context.
    If there are multiple forms of the result, choose the simplest or most relevant one.
    Preface the result with "Correct answer:" (outside the LaTeX delimiters).

    Wolfram Alpha response:
    {wolfram_response}

    Extracted result (in LaTeX):
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts and formats mathematical results."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.3,
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "Error extracting result from Wolfram Alpha response."

def check_rate_limit(session_id: str):
    now = datetime.now()
    if session_id not in rate_limit_data:
        rate_limit_data[session_id] = {"count": 1, "reset_time": now + timedelta(days=1)}
    elif rate_limit_data[session_id]["reset_time"] < now:
        rate_limit_data[session_id] = {"count": 1, "reset_time": now + timedelta(days=1)}
    elif rate_limit_data[session_id]["count"] >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    else:
        rate_limit_data[session_id]["count"] += 1

@app.get("/health")
async def health_check():
    return {"status": "OK", "timestamp": datetime.now().isoformat()}

@app.post("/start_session", response_model=SessionResponse)
async def start_session(api_key: str = Depends(get_api_key)):
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "topic": "General Math",
        "difficulty": 5  # Start at a middle difficulty
    }
    return {"session_id": session_id}

@app.post("/chat")
async def chat(query: Query, api_key: str = Depends(get_api_key)):
    if query.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    check_rate_limit(query.session_id)
    
    session = sessions[query.session_id]
    session["messages"].append({"role": "user", "content": query.message})
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=session["messages"],
            temperature=0.7,
            max_tokens=2000
        )
        
        bot_message = response.choices[0].message.content
        
        # Check if Wolfram Alpha query is needed
        if "Wolfram Alpha query:" in bot_message:
            wolfram_queries = re.findall(r"Wolfram Alpha query: (.+?)(?=\n|$)", bot_message)
            for wolfram_query in wolfram_queries:
                wolfram_result = query_wolfram_alpha(wolfram_query.strip())
                extracted_result = extract_wolfram_result(wolfram_result)
                bot_message = bot_message.replace(f"Wolfram Alpha query: {wolfram_query}", extracted_result)
        
        session["messages"].append({"role": "assistant", "content": bot_message})
        
        # Use AI to estimate difficulty and topic
        estimation_prompt = f"""
        Based on the conversation history and the last user query, estimate the current math topic and difficulty level (1-10).
        Respond with a JSON object containing 'topic' and 'difficulty' keys.
        Last user query: {query.message}
        """
        
        estimation_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an AI that estimates math topics and difficulty levels."},
                {"role": "user", "content": estimation_prompt}
            ],
            temperature=0.3,
            max_tokens=100
        )
        
        try:
            estimation = json.loads(estimation_response.choices[0].message.content)
            session["topic"] = estimation.get("topic", session["topic"])
            session["difficulty"] = estimation.get("difficulty", session["difficulty"])
        except json.JSONDecodeError:
            logger.error("Failed to parse AI estimation response")
        
        return {"response": bot_message}
    
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))