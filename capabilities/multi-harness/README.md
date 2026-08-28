# Capability: Multi-harness dispatch

Swap the coding engine without touching coordinator logic. The coordinator drives a coding
*harness* through its one-shot, non-interactive mode; the harness is pluggable.

## Why it exists

The coordinator owns judgment (plan, size, review, ship). The engine that actually writes
code is a stateless executor. Putting it behind a thin adapter means you can run the same
coordinator on top of Claude Code today and Antigravity tomorrow — engine choice is a
config flag, not a rewrite. This is what keeps the rest of the repo harness-neutral.

## How routing works

Two distinct paths use the harness:

1. **Code dispatch.** The coordinator builds a self-contained prompt and calls the active
   harness's CLI via the terminal tool. The exact command templates (flags, timeouts,
   permission-skipping) live in the per-harness skills.
2. **LLM support passes.** Triage summaries, humanizer rewrites, retrospective lessons,
   security audits, and backlog grooming all need an LLM too. They route through
   [`scripts/harness_llm.py`](../../scripts/harness_llm.py) — `resolve_engine()` picks the
   engine (`--engine` flag > `coding.default_engine`), `harness_generate()` runs the pass,
   and `strip_fences()` cleans the output. If the engine is down it raises
   `HarnessUnavailable`, and each caller falls back to a rules-only result rather than
   failing the task.

The default engine is set by `coding.default_engine` in
[`config.sample.yaml`](../../coordinator-core/config.sample.yaml). Switching mid-session is
a user instruction ("use antigravity") that selects the matching harness skill.

## Components

- **Script:** [`scripts/harness_llm.py`](../../scripts/harness_llm.py) — the single LLM
  choke point.
- **Skills:**
  - [`skill-library/harness/claude-code`](../../skill-library/harness/claude-code/SKILL.md) — `claude -p` (default)
  - [`skill-library/harness/antigravity`](../../skill-library/harness/antigravity/SKILL.md) — `agy -p`
  - [`skill-library/harness/opencode`](../../skill-library/harness/opencode/SKILL.md) — `opencode run`
- **Contract:** the "Harness Selection" and "Coding Engine Integration" sections of
  [`coordinator-core/SOUL.md`](../../coordinator-core/SOUL.md).

## Guardrails

- Always one-shot / non-interactive mode; `workdir` set to the project.
- Every prompt must be fully self-contained — the engine has no memory between dispatches.
- No `Co-Authored-By` trailers on commits.

## Adopting this piece

Pick one harness skill, set `coding.default_engine` to match, and make sure
`harness_llm.py` can invoke that CLI. Everything else (triage, delivery, audit) will route
its LLM passes through it automatically. To add a new engine, write a new harness skill with
its dispatch templates and teach `resolve_engine()` about it.
