---
name: humanizer-gate
description: Enforcement gate for all external prose. Strips AI slop patterns and calibrates to user voice before commits, PRs, docs, and chat summaries.
version: 1.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [humanizer, prose, writing, quality, slop-filter, enforcement]
    related_skills: [humanizer, complexity-triage, local-model-router]
---

# Humanizer Gate

Intercept all human-facing writes and filter through the humanizer gateway.

## When to trigger

Before ANY of these writes:

- Git commit messages
- GitHub PR titles and descriptions
- Documentation files (README, CHANGELOG, guides)
- Chat summaries sent to the user

## When to skip (bypass)

- Internal dispatch prompts to the coding engine
- Kanban task notes and internal status updates
- Cron job output (internal)
- Any context where --bypass is appropriate

## Dispatch

```
terminal(
    command="python3 ~/.hermes-coder/scripts/humanizer_gateway.py --text '<draft>' --type commit --repo '<project-dir>'",
    workdir="~/.hermes-coder",
    timeout=180
)
```

For longer text, pipe via stdin:

```
terminal(
    command="echo '<draft>' | python3 ~/.hermes-coder/scripts/humanizer_gateway.py - --type doc --repo '<project-dir>'",
    workdir="~/.hermes-coder",
    timeout=180
)
```

## Artifact type behavior

| Type | Behavior |
|------|----------|
| commit | Aggressive: lowercase, active verb, strip all fluff, max 72 chars |
| pr | Moderate: preserve template structure, strip body fluff |
| doc | Full: voice calibration + LLM anti-AI pass (via `claude -p`) + rule filtering |
| chat | Light: strip obvious slop, preserve conversational tone |

## LLM pass (default harness)

The LLM anti-AI pass runs through the default coding harness (`claude -p`), not a local model. Local models are intentionally not used for this work (see SOUL.md). Because the pass shells out to the harness it can take longer than a rule-only run — call with `timeout=180`.

## Fallback (harness unavailable)

Exit code 3 means the LLM harness was unreachable (or timed out). The gateway still outputs rule-filtered text to stdout. This is safe to use — rule-based filtering catches the most egregious patterns without LLM assistance. Log a warning but do not block the write.

## Integration with humanizer skill

This gate enforces the patterns documented in the `creative/humanizer` SKILL.md. The gateway script compiles 29 patterns into regexes for rule-based filtering. The LLM pass sends the rule-filtered draft to `claude -p` as a single text-in/text-out rewrite (no tools, `--max-turns 2`), guided by the same anti-AI tells from the SKILL.md self-check workflow.
