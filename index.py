from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import asyncio
import os
import json
import httpx
from hypercorn.asyncio import serve
from hypercorn.config import Config

app = FastAPI()

OLLAMA_MODEL = "mistral"
OLLAMA_URL = "http://localhost:11434/api/generate"
DOCS_DIR = "legalDocuments"

# Load documents at startup
print("Loading legal documents...")
documents = []
for filename in os.listdir(DOCS_DIR):
    path = os.path.join(DOCS_DIR, filename)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
            documents.append({"name": filename.lower(), "text": text})
print(f"Loaded {len(documents)} documents.")

doc_map = {doc["name"]: doc for doc in documents}

@app.post("/ask")
async def ask(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()
    language = body.get("language", "").strip()
    print(f"Received query: {query} | Language: {language}")

    # Ask which files are relevant
    file_list_prompt = f"""
    You are a multilingual legal assistant.

    Given the user query below, select which of the following English legal documents are most relevant.
    Respond ONLY with a comma-separated list of filenames (e.g., file1.txt, file2.txt). Do not write full sentences.

    Query: "{query}"

    Available Documents:
    {chr(10).join([f"- {doc['name']}" for doc in documents])}
    """.strip()

    print("Sending file selection prompt to Ollama...")
    async with httpx.AsyncClient() as client:
        file_response = await client.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": file_list_prompt,
            "stream": False
        })

    # We get the filenames from the response and clean them by trimming whitespace, punctuation, and converting to lowercase
    selected_filenames = file_response.json().get("response", "")
    selected_keys = [f.strip().lower().strip('.') for f in selected_filenames.split(",")]
    print(f"LLM selected: {selected_keys}")

    # We now build a big context block, we only combine the selected documents. Each section is labeled with the filename.  
    selected_texts = "\n\n".join([
        f"[{doc_map[key]['name']}]\n{doc_map[key]['text']}"
        for key in selected_keys if key in doc_map
    ]) or "No legal documents found."

    # Final prompt
    full_prompt = f"""
    You are a multilingual legal assistant. Respond in **{language}**.

    All documents are in English. Your job is to find relevant content and translate/rephrase it in **{language}**.

    Use the context below to answer the question.
    Always try to answer using the context.
    Refer to the source filename at the top of each section (e.g., [oregonrentersrights.txt]) where appropriate.
    If no relevant information is found, say "Information not available."

    Keep answers short and clear. Do not exceed 300 characters. Prioritize clarity and relevance.

    Context:
    {selected_texts}

    Question:
    {query}
    """.strip()

    print(f"Sending final prompt to Ollama ({len(full_prompt)} chars)")

    # SOURCE: https://www.python-httpx.org/async/
    async def stream_generator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": True
            }) as response:
                print(f"Ollama response status: {response.status_code}")
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk
        yield "[[END_OF_STREAM]]"

    return StreamingResponse(stream_generator(), media_type="text/plain")

if __name__ == "__main__":
    config = Config()
    config.bind = ["0.0.0.0:3000"]
    asyncio.run(serve(app, config))
