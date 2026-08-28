# Capability: Humanizer

A gateway that strips "AI slop" from any outward-facing prose — commit messages, PR
descriptions, docs, chat summaries — before it leaves the system, so deliverables read like
a person wrote them.

## How it works

The gateway runs two passes:

1. **Rule filter** — deterministic removal of common AI tells (filler transitions,
   hedging, over-structured boilerplate, em-dash tics, etc.).
2. **LLM rewrite** — an anti-AI rewrite that routes through the active coding harness
   (resolved from `--engine` / `coding.default_engine` via
   [`harness_llm.py`](../../scripts/harness_llm.py)), optionally matched to a cached voice
   sample.

If the LLM harness is unavailable (exit 3), the **rule-filtered output is still safe to
use** — the gateway fails open.

## Where it's applied

- Gated artifact types: `commit`, `pr`, `doc`, `chat`.
- Bypassed for internal traffic: `internal-dispatch`, `kanban-note`, `cron-output`.

The [github-delivery](../github-delivery/README.md) tool calls the humanizer **internally**
for commit/PR prose, so git deliverables need no separate humanizer call.

## Components

- **Script:** [`scripts/humanizer_gateway.py`](../../scripts/humanizer_gateway.py)
- **Skill:** [`humanizer-gate`](../../skill-library/coordinator/humanizer-gate/SKILL.md)
- **Design note:** [`HUMANIZER_SPEC.md`](HUMANIZER_SPEC.md)
- **Config:** the `humanizer` block in
  [`config.sample.yaml`](../../coordinator-core/config.sample.yaml) (gated artifacts, bypass
  contexts, voice-cache TTL, `fallback: rules-only`).

## Guardrails

- Run every external-facing artifact through the gateway before writing it.
- Skip it for internal dispatches and cron output.
- Treat the rules-only fallback as acceptable when the harness is down — never block a
  delivery on the LLM pass.
