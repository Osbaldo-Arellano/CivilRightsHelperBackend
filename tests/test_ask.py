import os
import sys
import shutil
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class FakePostResponse:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


class FakeStreamResponse:
    def __init__(self, lines, status_code=200):
        self.status_code = status_code
        self._lines = lines
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def aiter_lines(self):
        for line in self._lines:
            await asyncio.sleep(0)
            yield line

# Source: https://stackoverflow.com/questions/70995419/how-to-mock-an-async-instance-method-of-a-patched-class 
class FakeAsyncClient:
    def __init__(self, *, file_list_text, stream_lines):
        self._file_list_text = file_list_text
        self._stream_lines = stream_lines
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def post(self, url, json):
        return FakePostResponse({"response": self._file_list_text})
    def stream(self, method, url, json):
        return FakeStreamResponse(self._stream_lines)


# helper: allow passing files to exist at import time
def import_app_with_tmp_docs(tmp_path: Path, files=None):
    """
    Create tmp_path/legalDocuments with files before importing the app,
    then copy app into tmp and import it from file.
    """
    files = files or {"law.txt": "Some legal text."}

    # prepare docs first (loaded at import)
    docs_dir = tmp_path / "legalDocuments"
    docs_dir.mkdir(exist_ok=True)
    for p in docs_dir.glob("*"):
        p.unlink()
    for name, text in files.items():
        (docs_dir / name).write_text(text, encoding="utf-8")

    # copy and import app
    project_root = Path(__file__).resolve().parents[1]
    src = project_root / "main.py"
    if not src.exists():
        src = project_root / "index.py"
    dst = tmp_path / "main.py"
    shutil.copy(src, dst)
    os.chdir(tmp_path)
    sys.modules.pop("main", None)

    spec = importlib.util.spec_from_file_location("main", dst)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

def test_ask_happy_path(tmp_path):
    main = import_app_with_tmp_docs(tmp_path)

    # first POST returns one filename, stream sends two small chunks
    def client(*args, **kwargs):
        return FakeAsyncClient(
            file_list_text="law.txt",
            stream_lines=['{"response":"Hi"}', '{"response":"!"}'],
        )

    with patch.object(main, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = client

        client = TestClient(main.app)
        r = client.post("/ask", json={"query": "hello?", "language": "en"})
        assert r.status_code == 200
        assert r.text == "Hi![[END_OF_STREAM]]"

def test_ask_no_matching_docs(tmp_path):
    main = import_app_with_tmp_docs(tmp_path)

    # Replace what helper made, was getting: 'Cannot create a file when that file already exists'
    docs_dir = tmp_path / "legalDocuments"
    for p in docs_dir.glob("*"):
        p.unlink()
    (docs_dir / "unrelated.txt").write_text("Some unrelated text.", encoding="utf-8")

    def client(*args, **kwargs):
        return FakeAsyncClient(
            file_list_text="nonexistent.txt",
            stream_lines=['{"response":"No docs"}'],
        )

    with patch.object(main, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = client

        client = TestClient(main.app)
        r = client.post("/ask", json={"query": "test", "language": "en"})
        assert r.status_code == 200
        assert "No docs" in r.text
        assert r.text.endswith("[[END_OF_STREAM]]")

def test_ask_multiple_docs_in_context(tmp_path):
    main = import_app_with_tmp_docs(tmp_path, files={
        "doc1.txt": "First document content.",
        "doc2.txt": "Second document content.",
    })

    captured = {}

    class CapturingClient(FakeAsyncClient):
        def stream(self, method, url, json):
            captured["stream_json"] = json
            return FakeStreamResponse(['{"response":"Answer"}'])

    def client(*args, **kwargs):
        return CapturingClient(
            file_list_text="doc1.txt, doc2.txt",
            stream_lines=['{"response":"Answer"}'],
        )

    with patch.object(main, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = client

        client = TestClient(main.app)
        r = client.post("/ask", json={"query": "Combine info", "language": "en"})
        assert r.status_code == 200
        assert "Answer" in r.text
        assert r.text.endswith("[[END_OF_STREAM]]")

        prompt = captured["stream_json"]["prompt"]
        assert "[doc1.txt]" in prompt
        assert "[doc2.txt]" in prompt

def test_ask_empty_query_and_language(tmp_path):
    main = import_app_with_tmp_docs(tmp_path)

    def client(*args, **kwargs):
        return FakeAsyncClient(
            file_list_text="law.txt",
            stream_lines=['{"response":"Fallback"}'],
        )

    with patch.object(main, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = client
        client = TestClient(main.app)
        r = client.post("/ask", json={})  # no query and no language
        assert r.status_code == 200
        assert "Fallback" in r.text
        assert r.text.endswith("[[END_OF_STREAM]]")

def test_ask_empty_file_list(tmp_path):
    main = import_app_with_tmp_docs(tmp_path)

    def client(*args, **kwargs):
        return FakeAsyncClient(
            file_list_text="",  # nothing selected
            stream_lines=['{"response":"No selection"}'],
        )

    with patch.object(main, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = client
        client = TestClient(main.app)
        r = client.post("/ask", json={"query": "any", "language": "en"})
        assert r.status_code == 200
        assert "No selection" in r.text
        assert r.text.endswith("[[END_OF_STREAM]]")

def test_ask_filename_with_trailing_dot(tmp_path):
    main = import_app_with_tmp_docs(tmp_path, files={
        "doc1.txt": "Content."
    })

    def client(*args, **kwargs):
        return FakeAsyncClient(
            file_list_text="doc1.txt.",  # trailing dot
            stream_lines=['{"response":"Trimmed ok"}'],
        )

    with patch.object(main, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.side_effect = client
        client = TestClient(main.app)
        r = client.post("/ask", json={"query": "q", "language": "en"})
        assert r.status_code == 200
        assert "Trimmed ok" in r.text
        assert r.text.endswith("[[END_OF_STREAM]]")





