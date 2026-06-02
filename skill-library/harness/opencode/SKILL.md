---
name: harness-opencode
description: "Dispatch patterns for OpenCode as the coding engine."
version: 1.0.0
metadata:
  hermes:
    tags: [harness, opencode, dispatch]
    related_skills: [implementer, harness-claude-code, harness-antigravity]
---

# OpenCode Harness

Dispatch patterns for using OpenCode (`opencode run`) as the coding engine.

## One-Shot Command

```
opencode run '<prompt>' -m google-vertex/gemini-3.5-flash
```

The `run` subcommand executes a message non-interactively and returns the result.

## Dispatch Templates

### Implementation task

```
terminal(
    command="opencode run '<self-contained task prompt>' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=300
)
```

### Simple file edit

```
terminal(
    command="opencode run 'In <file>, update <function> to <change>. Run existing tests to verify.' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=120
)
```

### New feature

```
terminal(
    command="opencode run 'Implement <feature> as described: <spec>. Create files in <location>. Write tests in <test-location>. Follow existing patterns in <example-file>.' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=300
)
```

### Bug fix

```
terminal(
    command="opencode run 'Fix bug: <description>. Reproduce with: <repro-steps>. Root cause is likely in <file>. Add a regression test.' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=180
)
```

### Refactor

```
terminal(
    command="opencode run 'Refactor <component>: <goal>. Preserve all existing behavior. Run tests after each change.' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=300
)
```

### Read-only task (review, analysis)

```
terminal(
    command="opencode run '<review prompt>' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=120
)
```

### Independent code review

```
terminal(
    command="opencode run 'You are an independent code reviewer. Review this git diff for security concerns and logic errors.

SECURITY (auto-FAIL): hardcoded secrets, shell injection, SQL injection, path traversal, eval with user input.
LOGIC (auto-FAIL): wrong conditionals, missing error handling for I/O, off-by-one, race conditions.
SUGGESTIONS (non-blocking): missing tests, style, performance, naming.

Run: git diff HEAD~1 HEAD
Report: list security concerns, logic errors, and suggestions.' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=120
)
```

### Fix loop (targeted fixes only)

```
terminal(
    command="opencode run 'Fix ONLY these specific issues. Do NOT refactor or change anything else:
<list of issues>
' --dir <project-dir> --dangerously-skip-permissions -m google-vertex/gemini-3.5-flash",
    workdir="<project-dir>",
    timeout=120
)
```

## Flags Reference

| Flag | Purpose | When to Use |
|------|---------|-------------|
| `run` | One-shot non-interactive mode | Always for coordinator dispatch |
| `--dir` | Set working directory | Always — set project directory |
| `-m` | Override model (e.g., `-m google-vertex-anthropic/claude-opus-4-7`) | When a specific model is needed for a task |
| `--variant` | Reasoning effort (`high`, `max`, `minimal`) | For complex tasks needing deeper reasoning |
| `--dangerously-skip-permissions` | Auto-approve all tool use | When running unattended via coordinator |
| `--format json` | JSON output for programmatic parsing | When coordinator needs structured output |
| `-f` / `--file` | Attach file(s) to the prompt | When providing reference files |
| `--thinking` | Show model reasoning blocks | For debugging or complex analysis |

## Strengths

- Per-invocation model override via `-m`
- Reasoning effort control via `--variant`
- JSON output format for structured results
- File attachment support
- Thinking/reasoning block visibility

## Troubleshooting & Pitfalls

### "Ambiguous skill name 'opencode'" Error

- **Cause:** Multiple skill folders are named `opencode` (e.g. under `harness/` and `autonomous-ai-agents/`). The `skill_view` tool will refuse to guess and throw an ambiguity error.
- **Solution:** Load the skill using its categorized path directly:

  ```python
  skill_view(name="harness/opencode")
  ```

### Model NOT_FOUND Error on Default Model

- **Cause:** OpenCode has a default reasoning/planning model (e.g., `google-vertex-anthropic/claude-opus-4-7`) configured, which might not be enabled or accessible in your current Vertex AI project region, resulting in a `NOT_FOUND Requested entity was not found` error on invocation.
- **Solution:**
  1. List the available model list using `opencode models` to identify accessible Vertex AI models:

     ```bash
     opencode models
     ```

  2. Override the model on invocation using the `-m` or `--model` flag with an active, accessible model (e.g., `google-vertex/gemini-2.5-flash` or `google-vertex/gemini-3.5-flash`):

     ```bash
     opencode run "..." -m google-vertex/gemini-2.5-flash
     ```

## Limitations

- No tool allowlist — cannot restrict to read-only per invocation
- No max-turns control — task runs until complete
- No built-in timeout flag (use Hermes terminal timeout)
- No system prompt injection — all context must go in the prompt
