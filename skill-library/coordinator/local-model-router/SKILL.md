---
name: local-model-router
description: Route tasks to local Ollama models or cloud APIs based on triage output. Health-check aware with automatic cloud fallback.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [routing, ollama, local-model, cloud, dispatch, cost-optimization]
    related_skills: [complexity-triage, humanizer-gate, skill-discovery]
---

# Local Model Router

> **Status: paused.** Per the standing "no local models for now" directive (current machine too slow;
> revisit on capable hardware), do not route any work to local models. All dispatches and LLM-backed
> support passes go through the active cloud coding harness (`coding.default_engine`, override with
> `--engine`). The routing logic below is retained for when local models are re-enabled; until then,
> treat every task as cloud-routed and ignore `local` recommendations from triage.

Route coding tasks between local Ollama models and cloud APIs based on complexity triage results.

## Available models

### Local (Ollama)

- **gemma4:latest** (8B, Q4_K_M) — formatting, filtering, simple analysis, rewriting, classification
  - Good for: S-sized tasks, humanizer passes, triage classification, commit rewriting
  - Not good for: multi-file reasoning, complex architecture, deep debugging

### Cloud

- **gemini-3.5-flash** (default cloud model) — full reasoning, multi-file, architecture

## Health check

Before routing to local, always verify Ollama is healthy:

```
terminal(
    command="python3 ~/.hermes-coder/scripts/ollama_manager.py health",
    workdir="~/.hermes-coder",
    timeout=10
)
```

Exit 0 = healthy, proceed with local routing. Exit 1 = unhealthy, route everything to cloud.

## Routing rules

1. Triage says S + Ollama healthy → dispatch to local model
2. Triage says M/L/XL → always cloud
3. Triage says S but task mentions security/auth/crypto/migration → cloud override
4. Ollama unhealthy → all tasks to cloud (silent fallback, no error)

## Model selection for dispatch

Local model routing applies to:

- Humanizer gateway calls (internal, handled by the script itself)
- Triage LLM calls (internal, handled by the script itself)
- OpenCode dispatches (via `--api-base` and `-m` flags)

For claude-code dispatches, the model always uses Anthropic's cloud API. Triage output informs `--max-turns` and skill injection but does not change the model.

## Future extensibility

When larger models are added (gemma4:27b, qwen3-coder:30b), update:

1. `config.yaml` ollama.models section with new entry
2. `triage.routing.local_sizes` to include M
3. `scripts/ollama_utils.py` MODEL_REGISTRY with new capabilities
