#!/usr/bin/env python3
"""Ollama manager: health checks, model listing, readiness probing.

Usage:
    python3 ollama_manager.py status     # JSON system status
    python3 ollama_manager.py health     # one-line OK/FAIL, exit 0/1
    python3 ollama_manager.py models     # JSON model array with registry info

Exit codes:
    0  Success / healthy
    1  Ollama unreachable or no registered models available
    2  Invalid arguments
"""

import json
import sys

from ollama_utils import (
    OllamaClient,
    OllamaConnectionError,
    MODEL_REGISTRY,
    get_default_model,
)


def cmd_status(client: OllamaClient) -> dict:
    version = client.get_version()
    healthy = version is not None

    models_available = []
    default_model = None

    if healthy:
        try:
            models_available = client.list_models()
            default_model = get_default_model(client)
        except OllamaConnectionError:
            healthy = False

    ready = healthy and default_model is not None

    return {
        "ollama_healthy": healthy,
        "ollama_version": version,
        "models_available": models_available,
        "registered_models": list(MODEL_REGISTRY.keys()),
        "default_model": default_model,
        "ready": ready,
    }


def cmd_health(client: OllamaClient) -> int:
    version = client.get_version()
    if version:
        default = get_default_model(client)
        if default:
            print(f"OK: Ollama v{version}, default model: {default}")
        else:
            print(f"OK: Ollama v{version}, but no registered models loaded")
        return 0
    else:
        print("FAIL: Ollama unreachable", file=sys.stderr)
        return 1


def cmd_models(client: OllamaClient) -> int:
    try:
        models = client.list_models()
        print(json.dumps(models, indent=2))
        return 0
    except OllamaConnectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1


def main():
    if len(sys.argv) < 2:
        cmd = "status"
    else:
        cmd = sys.argv[1]

    client = OllamaClient()

    if cmd == "status":
        result = cmd_status(client)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ready"] else 1)
    elif cmd == "health":
        sys.exit(cmd_health(client))
    elif cmd == "models":
        sys.exit(cmd_models(client))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Usage: ollama_manager.py status|health|models", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
