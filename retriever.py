import requests

response = requests.post(
    "http://localhost:11434/api/generate",
    json={"model": "mistral", "prompt": "Hello, who are you?"}
)

print(response.json())
