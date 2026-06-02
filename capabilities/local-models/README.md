# Capability: Local models (optional)

Optional routing of LLM-backed support passes (and S-sized dispatches) to a **local** model
instead of the cloud harness, to cut cost and latency on iterative, token-heavy work.

> **Currently off by default.** In the live setup this is disabled under a standing "no
> local models for now" directive — the current machine is too slow. The plumbing is shipped
> and documented so it can be re-enabled on capable hardware. Treat this capability as
> opt-in.

## How it would work

- The triage step ([`dynamic_curator.py`](../../scripts/dynamic_curator.py)) can recommend
  routing S-sized tasks to a local model via its `routing` field.
- [`ollama_manager.py`](../../scripts/ollama_manager.py) /
  [`ollama_utils.py`](../../scripts/ollama_utils.py) manage local-model health and calls.
- The coordinator verifies health first (`ollama_manager.py health`) and **falls back to
  cloud silently** if the local model is unavailable.

While the "no local models" directive stands, the coordinator routes *all* work — dispatches
and every support pass (humanizer, triage, retrospective, audit, grooming) — through the
active cloud harness, and ignores triage's `local` routing suggestion.

## Components

- **Scripts:** [`scripts/ollama_manager.py`](../../scripts/ollama_manager.py),
  [`scripts/ollama_utils.py`](../../scripts/ollama_utils.py)
- **Skill:** [`local-model-router`](../../skill-library/coordinator/local-model-router/SKILL.md)
- **Design note:** [`LOCAL_OSS_STRATEGY.md`](LOCAL_OSS_STRATEGY.md)
- **Config:** the `ollama` block in
  [`config.sample.yaml`](../../coordinator-core/config.sample.yaml) (shipped with
  `enabled: false`).

## Adopting this piece

Set `ollama.enabled: true`, point `base_url` at your local server, declare your model(s) and
what they're `good_for` / `not_good_for`, and let triage route S-sized work locally. Keep the
silent cloud fallback so a slow or down local model never blocks a task.
