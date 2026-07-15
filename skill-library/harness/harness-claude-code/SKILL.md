---
name: harness-claude-code
description: "Dispatch patterns for Claude Code as the coding engine. Default harness. Implementation dispatches go through dispatch_coder.py (writes the dispatch receipt the commit gate requires)."
version: 1.1.0
metadata:
  hermes:
    tags: [harness, claude-code, dispatch, default, dispatch-receipt]
    related_skills: [implementer, harness-antigravity, harness-opencode]
---

# Claude Code Harness

Dispatch patterns for using Claude Code (`claude -p`) as the coding engine. It uses Vertex AI
authentication on this machine — no API key needed in the command.

## Implementation dispatches: ALWAYS via dispatch_coder.py

Any dispatch that **edits repo files** goes through the wrapper — never a raw `claude -p`
terminal command, and never your own patch/write tools:

```
terminal(
    command="python3 ~/.hermes-coder/scripts/dispatch_coder.py --repo '<project-dir>' --tier <tier-per-size> --max-turns <N> --prompt '<self-contained task prompt>' --json",
    workdir="~/.hermes-coder",
    background=true
)
```

Why the wrapper is mandatory:

1. **Model comes from config** (`coding.model_<tier>` via `--tier`) — a freehand model id
   cannot fail the dispatch (unknown claude ids are auto-substituted with the configured model).
2. **It records the dispatch receipt** that `github_lifecycle.py commit` now requires —
   code committed without a receipt is mechanically **blocked** (see dispatch_receipts.py).
   Editing files inline and then trying to commit will not work.
3. Engine is claude-code only — implementation never lands on a Gemini engine.

For a long prompt, write it to a temp file and pass `--prompt-file '<path>'` instead
(avoids all shell-quoting traps).

**Tier routing** (matches `config.yaml` `coding.model_*` — the wrapper resolves it, never
hardcode a model id):

| Triage size / task | `--tier` | Currently resolves to |
|---|---|---|
| XS / S implementation, simple edits, fix loops | `standard` | `claude-sonnet-5` |
| M implementation | `elevated` | `claude-opus-4-8` |
| L / XL implementation, security-sensitive work | `premium` | `claude-opus-4-8` |
| Hand-picked hardest case (explicit, never a routing default; NOT for security-focused work — Fable's cyber classifiers can refuse) | `max` | `claude-fable-5` |
| Final review gate (handled by `final_review.py`) | (script-internal) | `model_premium` |
| PR review gate (handled by `pr_review_cycle.py`) | (script-internal) | `pr_review.model` (`claude-fable-5`, opus fallback) |

`--max-turns`: 10–15 for simple edits, 25 (default) for features/bug fixes, 25–40 for
multi-file refactors or test-writing (turn starvation shows up as an abrupt halt with a
dirty tree — check `git status`, then re-dispatch with a higher cap).

Reading the output (`--json`): `status` `done` / `failed` / `harness_unavailable`,
`output_tail` (engine's final text), `model`, `duration_secs`. On `failed`, inspect
`output_tail`/`error` and re-dispatch or auto-heal; do NOT fall back to editing files
yourself.

## Read-only dispatches (review, analysis)

No files are edited, so no receipt is needed — raw `claude -p` is fine here:

```
terminal(
    command="claude -p '<review/analysis prompt>' --allowedTools 'Read,Bash' --max-turns 10 --dangerously-skip-permissions",
    workdir="<project-dir>",
    timeout=300
)
```

Omit `--model` for read-only passes (CLI default is fine) or pass a `coding.model_*` value
from config — never a model id from memory.

Per-task independent code reviews go to the **antigravity** harness (cross-vendor fresh
eyes — see `skills/harness/antigravity/`); fall back to the read-only template above only
if agy is unavailable, and note it. High-volume text passes (humanizer, triage, summaries,
drafting) run on `model_fast` (Gemini Flash via opencode) inside the support scripts —
never dispatch those here manually.

## Flags Reference (raw `claude -p`, read-only use)

| Flag | Purpose | When to Use |
|------|---------|-------------|
| `--allowedTools` | Restrict which tools Claude Code can use | Always — limit scope per task |
| `--max-turns` | Cap iterations to prevent runaway tasks | Always |
| `--model` | Pin the model for the dispatch | Only with a `coding.model_*` value from config |
| `--dangerously-skip-permissions` | Auto-approve all tool use | Always when unattended |
| `--append-system-prompt` | Inject additional system context | When adding tech-specific guidance |

## Pitfalls & Gotchas

- **Never invent a model id.** `claude-3-5-sonnet`, `claude-sonnet-4-5@20250929`,
  `claude-sonnet-4-6` etc. are not deployed here and fail the dispatch (2026-07-10
  incident: three freehand ids in a row failed and the task silently degraded to inline
  coordinator edits). Model ids come from `config.yaml` `coding.*` only; the
  dispatch_coder/`harness_llm` path substitutes unknown ids automatically.
- **Hangs on File Writing:** print-mode file-writing dispatches freeze waiting for
  confirmation unless `--dangerously-skip-permissions` is appended (dispatch_coder adds it).
- **`--max-turns` starvation:** an abrupt halt with a dirty tree usually means the turn
  limit hit. Check `git status`, re-dispatch with 25–40 turns.
- **Global Settings:** `"includeCoAuthoredBy": false` in `~/.claude/settings.json` prevents
  `Co-Authored-By` trailers — preferred over per-prompt instructions.
- **Cohesive UI & Test Dispatches:** for UI changes, name both the component file and its
  test file in the same prompt so they move together.
- **Shell Backtick and `${var}` Expansion Trap:** in terminal command strings, unescaped
  backticks and `${...}` are interpreted by the host shell. Wrap prompts in single quotes;
  escape embedded single quotes as `'\''`. Better: use `--prompt-file` with dispatch_coder
  and skip quoting entirely.
