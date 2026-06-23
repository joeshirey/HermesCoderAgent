---
name: retrospective
description: Capture a reusable lesson after an auto-heal struggle or debugger session, and inject relevant prior lessons into future dispatch prompts. Per-repo memory loop.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [retrospective, memory, lessons, learning, inject, capture, dispatch, harness]
    related_skills: [implementer, quality, reviewer]
---

# Retrospective / Memory Loop

The coding engine has no memory between dispatches — every prompt is self-contained. When a task needed multiple auto-heal retries or a full debugger session, the root cause and lesson would evaporate. This tool **captures** that lesson per-repo and **injects** the relevant ones into future dispatches so the team stops repeating mistakes.

## When to trigger

**Inject (before every dispatch):**

- Right before sending any implementation/fix task to the engine, pull matching prior lessons and append them to the prompt.

**Capture (after a struggle or PR review feedback):**

- An auto-healer run that **escalated** or needed **more than one attempt**.
- Any completed **systematic-debugger** session (reads its `.hermes-debug/<id>.json` journal).
- **Inline PR review comments:** When the user provides feedback via inline comments or review threads on pull requests, systematically capture those lessons-learned (such as code-safety gates, type-checking constraints, or styling pitfalls) and document them directly under `## Project memory (hermes)` in the project's `AGENTS.md` file, as well as preserving them using retrospective captures where applicable.

Do NOT use for:
Do NOT use for:

- Clean, first-try work — capture self-gates and returns `status: skipped` when there was no real struggle.
- Storing arbitrary notes — lessons come only from heal reports and debug journals.

## Dispatch

Inject (pull lessons, append the `snippet` to the dispatch prompt):

```
terminal(command="python3 ~/.hermes-coder/scripts/retrospective.py inject --repo '<project-dir>' --task '<task summary>' --json", workdir="~/.hermes-coder", timeout=30)
```

Capture from an auto-heal report (pipe the healer's `--json` straight in):

```
terminal(command="python3 ~/.hermes-coder/scripts/auto_healer.py --repo '<project-dir>' --check '<test cmd>' --engine <active-harness> --json | python3 ~/.hermes-coder/scripts/retrospective.py capture --source heal --repo '<project-dir>' --task '<task>' --json", workdir="~/.hermes-coder", timeout=600)
```

Capture from a debugger journal:

```
terminal(command="python3 ~/.hermes-coder/scripts/retrospective.py capture --source debug --bug-id '<id>' --repo '<project-dir>' --engine <active-harness> --json", workdir="~/.hermes-coder", timeout=60)
```

List stored lessons (inspection):

```
terminal(command="python3 ~/.hermes-coder/scripts/retrospective.py list --repo '<project-dir>' --json", workdir="~/.hermes-coder", timeout=30)
```

## How lessons are stored and matched

- One JSON per lesson under `<repo>/.hermes-lessons/`, mirroring `.hermes-debug/`.
- A `dedupe_key` (hash of trigger + root cause) prevents storing the same lesson twice — a repeat returns `status: duplicate`.
- `inject` scores each stored lesson by keyword overlap between the new task and the lesson's `tags`: `score = |task_words ∩ tags| / |task_words|`. Lessons scoring at or above `match_threshold` (config, default 0.05) are kept, sorted high-to-low, capped at `max_inject` (default 3).

## Injecting the snippet per harness

The injector emits a plain-text `snippet`. Append it through the active harness's context mechanism:

- **claude-code:** `--append-system-prompt '<snippet>'`
- **antigravity:** prepend the snippet to the task prompt
- **opencode:** write the snippet to a file and attach with `-f <file>`

Skip injection entirely when the snippet is empty.

## Reading the output

`capture` (`--json`):

- `status`: `captured` | `duplicate` | `skipped` | `error`
- `lesson_id`, `trigger`, `root_cause`, `lesson`, `tags`, `via` (`llm` | `rules`), `stored`

`inject` (`--json`):

- `lessons`: matched lessons with scores
- `snippet`: ready-to-append text (empty string when no matches)

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (lesson captured via LLM / inject emitted / list ok) |
| 1 | Nothing notable to capture (no struggle) |
| 2 | Invalid arguments / missing source / journal not found |
| 3 | LLM harness unavailable — rules-only lesson still stored |

## Graceful degradation

`capture` summarizes the evidence into a root cause + lesson via the active coding harness (resolved from `--engine`/`coding.default_engine`). If the harness is unavailable it falls back to a rules-only lesson assembled from the structured journal/heal fields and exits 3 — the lesson is still stored. `inject` needs no LLM, so it is unaffected by the harness being down.
