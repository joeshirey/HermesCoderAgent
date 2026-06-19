---
name: harness-claude-code
description: "Dispatch patterns for Claude Code as the coding engine. Default harness."
version: 1.0.0
metadata:
  hermes:
    tags: [harness, claude-code, dispatch, default]
    related_skills: [implementer, harness-antigravity, harness-opencode]
---

# Claude Code Harness

Dispatch patterns for using Claude Code (`claude -p`) as the coding engine.

## One-Shot Command

```
claude -p '<prompt>' --model <model-per-routing-table>
```

Claude Code print mode runs a single prompt non-interactively and returns the result. It uses Vertex AI authentication on this machine — no API key needed in the command.

**Model routing:** always pass `--model` on claude-code dispatches, selected by the task's triage size. The canonical values live in `config.yaml` under `coding.model_*` (coordinator scripts read them automatically); keep this table in sync with it.

| Triage size / task | Model | Config key |
|---|---|---|
| XS / S implementation, simple edits, fix loops | `claude-sonnet-4-6` | `model_standard` |
| M implementation | `claude-opus-4-8` | `model_elevated` |
| L / XL implementation, security-sensitive work | `claude-fable-5` | `model_premium` |
| Final review gate (handled by `final_review.py`) | `claude-fable-5` | `model_premium` |

Per-task independent code reviews go to the **antigravity** harness (cross-vendor fresh eyes — see `skills/harness/antigravity/`), not claude-code; fall back to the read-only template below with `model_standard` only if agy is unavailable. High-volume text passes (humanizer, triage, summaries, drafting) run on `model_fast` (Gemini Flash via opencode) inside the support scripts — never dispatch those here manually.

## Dispatch Templates

### Implementation task

```
terminal(
    command="claude -p '<self-contained task prompt>' --allowedTools 'Read,Edit,Write,Bash' --max-turns 15 --model <model-per-size>",
    workdir="<project-dir>",
    timeout=300
)
```

### Simple file edit

```
terminal(
    command="claude -p 'In <file>, update <function> to <change>. Run existing tests to verify.' --allowedTools 'Read,Edit,Bash' --max-turns 10 --model claude-sonnet-4-6",
    workdir="<project-dir>",
    timeout=120
)
```

### New feature

```
terminal(
    command="claude -p 'Implement <feature> as described: <spec>. Create files in <location>. Write tests in <test-location>. Follow existing patterns in <example-file>.' --allowedTools 'Read,Edit,Write,Bash' --max-turns 20 --model <model-per-size>",
    workdir="<project-dir>",
    timeout=300
)
```

### Bug fix

```
terminal(
    command="claude -p 'Fix bug: <description>. Reproduce with: <repro-steps>. Root cause is likely in <file>. Add a regression test.' --allowedTools 'Read,Edit,Bash' --max-turns 15 --model <model-per-size>",
    workdir="<project-dir>",
    timeout=180
)
```

### Refactor

```
terminal(
    command="claude -p 'Refactor <component>: <goal>. Preserve all existing behavior. Run tests after each change.' --allowedTools 'Read,Edit,Bash' --max-turns 20 --model <model-per-size>",
    workdir="<project-dir>",
    timeout=300
)
```

### Read-only task (review, analysis)

```
terminal(
    command="claude -p '<review prompt>' --allowedTools 'Read,Bash' --max-turns 10 --model claude-sonnet-4-6",
    workdir="<project-dir>",
    timeout=120
)
```

### Independent code review

```
terminal(
    command="claude -p 'You are an independent code reviewer. Review this git diff for security concerns and logic errors.

SECURITY (auto-FAIL): hardcoded secrets, shell injection, SQL injection, path traversal, eval with user input.
LOGIC (auto-FAIL): wrong conditionals, missing error handling for I/O, off-by-one, race conditions.
SUGGESTIONS (non-blocking): missing tests, style, performance, naming.

Run: git diff HEAD~1 HEAD
Report: list security concerns, logic errors, and suggestions.' --allowedTools 'Read,Bash' --max-turns 10 --model claude-sonnet-4-6",
    workdir="<project-dir>",
    timeout=120
)
```

### Fix loop (targeted fixes only)

```
terminal(
    command="claude -p 'Fix ONLY these specific issues. Do NOT refactor or change anything else:
<list of issues>
' --allowedTools 'Read,Edit,Bash' --max-turns 10 --model claude-sonnet-4-6",
    workdir="<project-dir>",
    timeout=120
)
```

## Flags Reference

| Flag | Purpose | When to Use |
|------|---------|-------------|
| `--allowedTools` | Restrict which tools Claude Code can use | Always — limit scope per task |
| `--max-turns` | Cap iterations to prevent runaway tasks | Always — default 15, lower for simple tasks |
| `--model` | Pin the model for the dispatch | Always — per the Model routing table (config `coding.model_*`) |
| `--dangerously-skip-permissions` | Auto-approve all tool use | When running unattended via coordinator |
| `--append-system-prompt` | Inject additional system context | When adding tech-specific guidance |

## Strengths

- Fine-grained tool control via `--allowedTools`
- Turn limits prevent runaway tasks
- System prompt injection for context enrichment
- Excellent code generation quality (Claude Opus)

## Limitations

- No built-in timeout flag (use Hermes terminal timeout)
- Working directory is implicit (set via Hermes `workdir`)

## Pitfalls & Gotchas

- **Claude Fable 5 Fallback:** Claude Fable 5 (`model_premium`) is currently unstable/broken or may be unconfigured on Vertex AI deployments. If any automated tool, script (such as `final_review.py`), or manual L/XL dispatch fails while using Fable, immediately configure the fallback to `claude-opus-4-8` (`model_elevated`) as the premium coding engine to bypass the outage:
  ```bash
  hermes config set coding.claude_model claude-opus-4-8
  hermes config set coding.model_premium claude-opus-4-8
  ```
- **Hangs on File Writing:** When orchestrating Claude Code via print-mode (`claude -p`), file-writing dispatches will freeze/halt waiting for confirmation unless `--dangerously-skip-permissions` is explicitly appended. Always append this flag for unattended or automated implementations.
- **Lowercase Tool Names Hang:** Avoid passing lowercase or invalid tool names (like `'Read,Edit,Write,Bash'`) to `--allowedTools` when calling Claude Code (`claude -p`), as this causes immediate hangs. Use exact camelcase tool names (e.g. `ReadFile`, `WriteFile`, `EditFile`, `Bash`, `Glob`, `Grep`) or omit the `--allowedTools` flag entirely.
- **`--max-turns` starvation:** If a print-mode task halts abruptly without committing or completing the requested output, you likely hit the turn limit. Check `git status` to verify the workspace state. For multi-file refactors, complex bug fixes, or test-writing sessions, increase `--max-turns` to **25-40** to prevent premature exits.
- **Global Settings:** To prevent Claude Code from appending `Co-Authored-By` trailers to git commits, set `"includeCoAuthoredBy": false` in `~/.claude/settings.json`. This is preferred over adding the instruction to every prompt.
- **Shell Backtick Command Substitution Trap:** When calling Claude Code (`claude -p`) or any CLI tool via the terminal tool within double-quoted command strings, avoid using unescaped backticks (`` `...` ``) in your prompt. The host shell interprets backticks inside double quotes as active command substitutions, throwing errors like `/bin/bash: command substitution: line ...` and `/bin/bash: command not found`. Always wrap your prompt strings in **single quotes** (`claude -p '...'`) or escape every backtick meticulously as `\``.
