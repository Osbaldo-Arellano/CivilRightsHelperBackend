# Backend (FastAPI + Ollama)

## What this service does

- Loads plain-text files from `legalDocuments/`.
- Asks the LLM to pick the most relevant files for a user question.
- Builds a small cited prompt using only the selected files.
- Streams the model’s answer back to the client and terminates with `[[END_OF_STREAM]]`.

## Requirements

- Python 3.10+ (tested on 3.11)
- Ollama running locally
- Model: `mistral` (default), or any chat-capable model you have pulled
- A folder `legalDocuments/` with one or more `.txt` files

## Quick start

```bash
# 1) clone & enter project
git clone <your-repo-url>
cd <your-repo>

# 2) create venv
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

# 3) install deps
pip install -r requirements.txt

# 4) pull model & start Ollama in another terminal
ollama pull mistral
ollama serve

# 5) put your .txt files in ./legalDocuments

# 6) run the API
python main.py
# server listens on http://0.0.0.0:3000
```

On startup you should see:  
`Loading legal documents...` and `Loaded N documents.`

## Configuration

Environment variables:

| Var            | Default                               | What it does            |
| -------------- | ------------------------------------- | ----------------------- |
| `OLLAMA_MODEL` | `mistral`                             | Model name to use       |
| `OLLAMA_URL`   | `http://localhost:11434/api/generate` | Ollama HTTP endpoint    |
| `DOCS_DIR`     | `legalDocuments`                      | Folder of context files |

You can also edit these constants at the top of `main.py`.

## API

### `POST /ask`

**Request body**

```json
{
  "query": "What protections exist for renters?",
  "language": "Spanish"
}
```

**Behavior**

1. The server first asks the model to select relevant files from the list of loaded documents.  
   It expects a comma-separated list of filenames in the response (e.g. `file1.txt, file2.txt`).

2. It builds a Context block using only those files. Each section starts with `[filename]`.

3. It streams the final answer as plain text chunks, ending with `[END_OF_STREAM]`.

**Streaming response**

- `text/plain` chunks, each chunk is a piece of the model output.
- The very last chunk is the terminator: `[END_OF_STREAM]`.

**cURL example**

```bash
curl -N -X POST http://localhost:3000/ask \
  -H "Content-Type: application/json" \
  -d '{"query":"What protections exist for renters?","language":"English"}'
```

Use `-N` to disable buffering so you can see tokens stream in.

## How document selection works

- The server sends a “file selection” prompt listing all filenames.
- The model replies with a comma-separated list.  
  The server:
  - lowercases names,
  - trims whitespace and trailing punctuation,
  - filters to files that actually exist.
- Only those files are included in the final prompt’s Context.

If the model returns unknown files, the context falls back to `No legal documents found.` (the answer still streams).

## Testing

### Backend tests (pytest)

If you’re keeping the Python tests from earlier work:

```bash
pip install -r requirements.txt
pytest -q
```

The tests:

- Fake the `httpx.AsyncClient` used by the app so **no network** is needed.
- Verify streaming (chunks + terminator).
- Verify that selected filenames end up in the **Context**.

### GitHub Actions

```yaml
name: Run Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - name: Check out code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          pip install pytest

      - name: Run tests
        run: pytest -q tests
```

## Troubleshooting

- **No documents loaded**  
  Ensure the `legalDocuments/` folder exists next to `main.py` and contains `.txt` files.
- **Ollama connection refused**  
  Make sure `ollama serve` is running and `OLLAMA_URL` matches `http://localhost:11434/api/generate`.
- **Model not found**  
  `ollama pull mistral` (or change `OLLAMA_MODEL` to one you have locally).
