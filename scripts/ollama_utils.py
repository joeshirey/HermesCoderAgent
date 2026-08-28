#!/usr/bin/env python3
"""Shared Ollama client library. Stdlib-only (no pip dependencies)."""

import json
import sys
import time
import urllib.request
import urllib.error
from typing import Optional


class OllamaConnectionError(Exception):
    """Raised when Ollama is unreachable."""


class OllamaAPIError(Exception):
    """Raised on non-2xx API responses."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


MODEL_REGISTRY: dict[str, dict] = {
    "gemma4:latest": {
        "display_name": "Gemma 4 8B",
        "parameter_size": "8B",
        "capabilities": [
            "formatting",
            "filtering",
            "simple-analysis",
            "rewriting",
            "classification",
        ],
        "max_context": 8192,
        "recommended_max_tokens": 2048,
        "good_for": [
            "humanizer-pass",
            "triage-classification",
            "commit-rewriting",
            "slop-detection",
        ],
        "not_good_for": [
            "multi-file-reasoning",
            "complex-architecture",
            "deep-debugging",
        ],
    },
    # Future models:
    # "gemma4:27b": { ... },
    # "qwen3-coder:30b": { ... },
    # "deepcoder:14b": { ... },
}


def get_model_info(model_name: str) -> Optional[dict]:
    return MODEL_REGISTRY.get(model_name)


class OllamaClient:
    """Stdlib HTTP client for the Ollama REST API."""

    def __init__(self, base_url: str = "http://localhost:11434", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self, method: str, path: str, body: Optional[dict] = None
    ) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.URLError as e:
            raise OllamaConnectionError(
                f"Cannot reach Ollama at {self.base_url}: {e.reason}"
            ) from e
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise OllamaAPIError(e.code, body_text) from e
        except TimeoutError as e:
            raise OllamaConnectionError(
                f"Timeout connecting to Ollama at {self.base_url}"
            ) from e

    # -- Health & Discovery --

    def is_healthy(self) -> bool:
        try:
            self._request("GET", "/api/version")
            return True
        except (OllamaConnectionError, OllamaAPIError):
            return False

    def get_version(self) -> Optional[str]:
        try:
            resp = self._request("GET", "/api/version")
            return resp.get("version")
        except (OllamaConnectionError, OllamaAPIError):
            return None

    def list_models(self) -> list[dict]:
        resp = self._request("GET", "/api/tags")
        models = resp.get("models", [])
        result = []
        for m in models:
            name = m.get("name", "")
            size_bytes = m.get("size", 0)
            entry = {
                "name": name,
                "size_gb": round(size_bytes / (1024**3), 1),
                "modified_at": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", ""),
                "parameter_size": m.get("details", {}).get("parameter_size", ""),
                "quantization": m.get("details", {}).get("quantization_level", ""),
            }
            registry_info = get_model_info(name)
            if registry_info:
                entry["registry"] = registry_info
            result.append(entry)
        return result

    def has_model(self, model_name: str) -> bool:
        try:
            models = self.list_models()
            return any(m["name"] == model_name for m in models)
        except (OllamaConnectionError, OllamaAPIError):
            return False

    # -- Generation --

    def chat(
        self,
        model: str,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> dict:
        msgs = list(messages)
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        body = {
            "model": model,
            "messages": msgs,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        resp = self._request("POST", "/api/chat", body)
        msg = resp.get("message", {})
        return {
            "content": msg.get("content", ""),
            "model": resp.get("model", model),
            "eval_count": resp.get("eval_count", 0),
            "total_duration_ms": resp.get("total_duration", 0) // 1_000_000,
            "done_reason": resp.get("done_reason", ""),
        }

    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            body["system"] = system
        resp = self._request("POST", "/api/generate", body)
        return {
            "content": resp.get("response", ""),
            "model": resp.get("model", model),
            "eval_count": resp.get("eval_count", 0),
            "total_duration_ms": resp.get("total_duration", 0) // 1_000_000,
            "done_reason": resp.get("done_reason", ""),
        }


def get_default_model(client: Optional[OllamaClient] = None) -> Optional[str]:
    """Return the first available model from the registry that Ollama has loaded."""
    if client is None:
        client = OllamaClient()
    try:
        available = {m["name"] for m in client.list_models()}
    except OllamaConnectionError:
        return None
    for name in MODEL_REGISTRY:
        if name in available:
            return name
    return None


# -- CLI test mode --

def _cli_main():
    if len(sys.argv) < 2:
        print("Usage: ollama_utils.py health|models|chat <prompt>", file=sys.stderr)
        sys.exit(2)

    cmd = sys.argv[1]
    client = OllamaClient()

    if cmd == "health":
        version = client.get_version()
        if version:
            print(f"OK: Ollama v{version}")
            sys.exit(0)
        else:
            print("FAIL: Ollama unreachable", file=sys.stderr)
            sys.exit(1)

    elif cmd == "models":
        try:
            models = client.list_models()
            print(json.dumps(models, indent=2))
        except OllamaConnectionError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "chat":
        if len(sys.argv) < 3:
            print("Usage: ollama_utils.py chat <prompt>", file=sys.stderr)
            sys.exit(2)
        prompt = sys.argv[2]
        model = get_default_model(client)
        if not model:
            print("FAIL: No registered model available", file=sys.stderr)
            sys.exit(1)
        start = time.time()
        try:
            resp = client.chat(model, [{"role": "user", "content": prompt}])
            elapsed = time.time() - start
            print(resp["content"])
            print(
                f"\n--- {resp['model']} | {resp['eval_count']} tokens | {elapsed:.1f}s ---",
                file=sys.stderr,
            )
        except OllamaConnectionError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _cli_main()
