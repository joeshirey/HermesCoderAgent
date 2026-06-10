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
claude -p '<prompt>' --model claude-fable-5
```

Claude Code print mode runs a single prompt non-interactively and returns the result. It uses Vertex AI authentication on this machine — no API key needed in the command.

**Model:** always pass `--model claude-fable-5` on claude-code dispatches. The canonical value lives in `config.yaml` under `coding.claude_model` (the coordinator scripts read it from there automatically); keep these templates in sync with it.

## Dispatch Templates

### Implementation task

```
terminal(
    command="claude -p '<self-contained task prompt>' --allowedTools 'Read,Edit,Write,Bash' --max-turns 15 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=300
)
```

### Simple file edit

```
terminal(
    command="claude -p 'In <file>, update <function> to <change>. Run existing tests to verify.' --allowedTools 'Read,Edit,Bash' --max-turns 10 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=120
)
```

### New feature

```
terminal(
    command="claude -p 'Implement <feature> as described: <spec>. Create files in <location>. Write tests in <test-location>. Follow existing patterns in <example-file>.' --allowedTools 'Read,Edit,Write,Bash' --max-turns 20 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=300
)
```

### Bug fix

```
terminal(
    command="claude -p 'Fix bug: <description>. Reproduce with: <repro-steps>. Root cause is likely in <file>. Add a regression test.' --allowedTools 'Read,Edit,Bash' --max-turns 15 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=180
)
```

### Refactor

```
terminal(
    command="claude -p 'Refactor <component>: <goal>. Preserve all existing behavior. Run tests after each change.' --allowedTools 'Read,Edit,Bash' --max-turns 20 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=300
)
```

### Read-only task (review, analysis)

```
terminal(
    command="claude -p '<review prompt>' --allowedTools 'Read,Bash' --max-turns 10 --model claude-fable-5",
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
Report: list security concerns, logic errors, and suggestions.' --allowedTools 'Read,Bash' --max-turns 10 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=120
)
```

### Fix loop (targeted fixes only)

```
terminal(
    command="claude -p 'Fix ONLY these specific issues. Do NOT refactor or change anything else:
<list of issues>
' --allowedTools 'Read,Edit,Bash' --max-turns 10 --model claude-fable-5",
    workdir="<project-dir>",
    timeout=120
)
```

## Flags Reference

| Flag | Purpose | When to Use |
|------|---------|-------------|
| `--allowedTools` | Restrict which tools Claude Code can use | Always — limit scope per task |
| `--max-turns` | Cap iterations to prevent runaway tasks | Always — default 15, lower for simple tasks |
| `--model` | Pin the model for the dispatch | Always — `claude-fable-5` (config `coding.claude_model`) |
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

- **Hangs on File Writing:** When orchestrating Claude Code via print-mode (`claude -p`), file-writing dispatches will freeze/halt waiting for confirmation unless `--dangerously-skip-permissions` is explicitly appended. Always append this flag for unattended or automated implementations.
- **Lowercase Tool Names Hang:** Avoid passing lowercase or invalid tool names (like `'Read,Edit,Write,Bash'`) to `--allowedTools` when calling Claude Code (`claude -p`), as this causes immediate hangs. Use exact camelcase tool names (e.g. `ReadFile`, `WriteFile`, `EditFile`, `Bash`, `Glob`, `Grep`) or omit the `--allowedTools` flag entirely.
- **`--max-turns` starvation:** If a print-mode task halts abruptly without committing or completing the requested output, you likely hit the turn limit. Check `git status` to verify the workspace state. For multi-file refactors, complex bug fixes, or test-writing sessions, increase `--max-turns` to **25-40** to prevent premature exits.
- **Global Settings:** To prevent Claude Code from appending `Co-Authored-By` trailers to git commits, set `"includeCoAuthoredBy": false` in `~/.claude/settings.json`. This is preferred over adding the instruction to every prompt.
- **Shell Backtick Command Substitution Trap:** When calling Claude Code (`claude -p`) or any CLI tool via the terminal tool within double-quoted command strings, avoid using unescaped backticks (`` `...` ``) in your prompt. The host shell interprets backticks inside double quotes as active command substitutions, throwing errors like `/bin/bash: command substitution: line ...` and `/bin/bash: command not found`. Always wrap your prompt strings in **single quotes** (`claude -p '...'`) or escape every backtick meticulously as `\``.
