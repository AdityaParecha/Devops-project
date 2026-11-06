import requests
import json

class OllamaError(RuntimeError):
    pass

class OllamaClient:
    def __init__(self, base_url: str, timeout: int = 90):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def tags(self):
        r = self.session.get(f"{self.base_url}/api/tags", timeout=10)
        r.raise_for_status()
        return r.json().get("models", [])

    def systemone(self, model: str, state, questions: dict, timeout: int = None):
        """Call decision models such as Laya using Ollama's typed /v1/systemone API."""
        payload = {"model": model, "state": state, "questions": questions}
        try:
            r = self.session.post(f"{self.base_url}/v1/systemone", json=payload, timeout=timeout or self.timeout)
            r.raise_for_status()
            body = r.json()
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama System One request failed for {model}: {exc}") from exc
        except ValueError as exc:
            raise OllamaError(f"Ollama System One returned invalid JSON for {model}") from exc
        if not isinstance(body.get("answers"), dict):
            raise OllamaError(f"{model} response did not contain typed answers")
        return body

    def generate_json(self, model: str, prompt: str, system: str = ""):
        payload = {
            "model": model, "prompt": prompt, "system": system,
            "stream": False, "format": "json", "options": {"temperature": 0}
        }
        try:
            r = self.session.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout or self.timeout)
            r.raise_for_status()
            raw = r.json().get("response", "")
            return json.loads(raw)
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama generation request failed for {model}: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise OllamaError(f"{model} returned invalid JSON") from exc
