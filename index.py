import requests
from fastapi import FastAPI
from pydantic import BaseModel
import json
from hypercorn.asyncio import serve
from hypercorn.config import Config
import asyncio

app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"

class QueryRequest(BaseModel):
    query: str

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/ask")
async def ask(request: QueryRequest):
    query = request.query
    print(query)
    response = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "prompt": query
    })

    print("Ollama Raw Response:", response.text) 

    if response.status_code == 200:
        try:
            responses = response.text.strip().split("\n")
            final_response = ""
            for line in responses:
                if line.strip():
                    parsed = json.loads(line)
                    final_response += parsed.get("response", "")
            return {"answer": final_response}
        except Exception as e:
            return {"error": f"Failed to parse response: {str(e)}"}
    else:
        return {"error": "LLM call failed"}

if __name__ == "__main__":
    config = Config()
    config.bind = ["0.0.0.0:3000"]
    config.certfile = "localhost.pem"
    config.keyfile = "localhost-key.pem"

    asyncio.run(serve(app, config))
