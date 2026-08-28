---
name: harness-antigravity
description: "Dispatch patterns for Antigravity CLI (agy) as the coding engine."
version: 1.0.0
metadata:
  hermes:
    tags: [harness, antigravity, agy, dispatch]
    related_skills: [implementer, harness-claude-code, harness-opencode]
---

# Antigravity Harness

Dispatch patterns for using Antigravity CLI (`agy`) as the coding engine.

## One-Shot Command

```
agy -p '<prompt>'
```

The `-p` / `--print` flag runs a single prompt non-interactively and prints the response.

## Dispatch Templates

### Implementation task

```
terminal(
    command="agy -p '<self-contained task prompt>' --dangerously-skip-permissions --print-timeout 5m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=300
)
```

### Simple file edit

```
terminal(
    command="agy -p 'In <file>, update <function> to <change>. Run existing tests to verify.' --dangerously-skip-permissions --print-timeout 3m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=180
)
```

### New feature

```
terminal(
    command="agy -p 'Implement <feature> as described: <spec>. Create files in <location>. Write tests in <test-location>. Follow existing patterns in <example-file>.' --dangerously-skip-permissions --print-timeout 8m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=480
)
```

### Bug fix

```
terminal(
    command="agy -p 'Fix bug: <description>. Reproduce with: <repro-steps>. Root cause is likely in <file>. Add a regression test.' --dangerously-skip-permissions --print-timeout 5m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=300
)
```

### Refactor

```
terminal(
    command="agy -p 'Refactor <component>: <goal>. Preserve all existing behavior. Run tests after each change.' --dangerously-skip-permissions --print-timeout 8m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=480
)
```

### Read-only task (review, analysis)

```
terminal(
    command="agy -p '<review prompt>' --dangerously-skip-permissions --print-timeout 3m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=180
)
```

### Independent code review

```
terminal(
    command="agy -p 'You are an independent code reviewer. Review this git diff for security concerns and logic errors.

SECURITY (auto-FAIL): hardcoded secrets, shell injection, SQL injection, path traversal, eval with user input.
LOGIC (auto-FAIL): wrong conditionals, missing error handling for I/O, off-by-one, race conditions.
SUGGESTIONS (non-blocking): missing tests, style, performance, naming.

Run: git diff HEAD~1 HEAD
Report: list security concerns, logic errors, and suggestions.' --dangerously-skip-permissions --print-timeout 3m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=180
)
```

### Fix loop (targeted fixes only)

```
terminal(
    command="agy -p 'Fix ONLY these specific issues. Do NOT refactor or change anything else:
<list of issues>
' --dangerously-skip-permissions --print-timeout 3m0s --add-dir <project-dir>",
    workdir="<project-dir>",
    timeout=180
)
```

## Flags Reference

| Flag | Purpose | When to Use |
|------|---------|-------------|
| `-p` / `--print` | One-shot non-interactive mode | Always for coordinator dispatch |
| `--print-timeout` | Timeout for print mode (e.g., `5m0s`) | Always — prevents hanging tasks |
| `--add-dir` | Add directory to workspace (repeatable) | Always — set project directory |
| `--dangerously-skip-permissions` | Auto-approve all tool use | When running unattended via coordinator |
| `--sandbox` | Restrict terminal access | For read-only review tasks |

## Strengths

- Simple, focused CLI interface
- Built-in timeout control via `--print-timeout`
- Sandbox mode for restricted execution

## Troubleshooting & Pitfalls

### Bash Single-Quote Evaluation Errors

- **Cause:** When running `agy -p '<prompt>'` or similar terminal wrappers, any single quotes (such as `customer's` or `'party_size'`) inside the prompt string will break the outer shell's single-quote matching, causing bash syntax errors like `unexpected token '('` or `Permission denied` when evaluating the command.
- **Solution:** Strip single quotes from the prompt entirely, use escaped double quotes (`\"`), or rewrite the prose to avoid single quotes (e.g. use "guest name" instead of "guest's name").

### "agent executor error: invalid project ID: """

- **Cause:** Antigravity backend service requires a valid GCP Project ID to run the agent executor. If the active workspace's configuration folder (e.g. `~/.antigravitycli`) maps to a workspace with no project associated, the client fails to resolve the project ID and sends an empty string or UUID, causing the backend executor to reject the call.
- **Solution:**
  1. Ensure that the correct GCP project is set in the active `gcloud` configuration:

     ```bash
     /Users/you/Downloads/google-cloud-sdk/bin/gcloud config set project <gcp-project-id>
     ```

  2. Verify that the SDK's `bin/` directory is appended to your environment `$PATH` so the silent authentication and keyring provider can resolve credentials and project state:

     ```bash
     export PATH=$PATH:/Users/you/Downloads/google-cloud-sdk/bin
     ```

  3. Ensure environment variables `GOOGLE_CLOUD_PROJECT` and `CLOUDSDK_CORE_PROJECT` are set to your active project ID (e.g., `your-gcp-project-id`).

### Bash Evaluation / Quote Parsing Errors on Dispatch

- **Cause:** When dispatching a prompt containing raw, unescaped single quotes (e.g. `customer's` or inline single-quoted selectors) to the `agy` CLI via a shell command, the shell's string parser can choke, causing bash evaluation syntax errors (like `syntax error near unexpected token '('` or `Permission denied`).
- **Solution:** Ensure that prompts passed to `agy` have all single quotes removed or re-written, or wrap the prompt in double quotes while avoiding raw nested single quotes that conflict with bash expansion.

### "Skill 'harness-antigravity' not found" Error

- **Cause:** The skill directory structure (`harness/antigravity/SKILL.md`) and the frontmatter name mismatch can cause standard `skill_view` calls with `harness-antigravity` or `antigravity` to fail.
- **Solution:** Load the skill by combining the category and directory name: `skill_view(name="harness:antigravity")`. Alternatively, fall back to reading the file directly using the `read_file` tool with the path `/Users/you/.hermes-coder/skills/harness/antigravity/SKILL.md`.

### Bash Syntax & Parsing Errors in Dispatch Prompts

- **Cause:** When calling `terminal()` with `agy -p '<prompt>'`, passing unescaped single quotes (e.g., `customer's`), backticks, or raw parentheses in the prompt text can cause Bash command evaluation or expansion errors, causing the terminal call to fail with syntax errors.
- **Solution:** Strip single quotes from prompt texts (e.g., `the customer name`), avoid raw backticks or unescaped parentheses in prompt descriptions, or wrap and escape prompts carefully before dispatching to avoid shell expansion conflicts.

## Limitations

- No tool allowlist — cannot restrict to read-only per invocation (use `--sandbox` as alternative for reviews)
- No max-turns control — task runs until complete or timeout
- No model selection flag — model configured at account level
- No system prompt injection — all context must go in the prompt
- Timeouts use Go duration format (`5m0s`) not seconds

## Monorepo Review Dispatch Pattern

For a high-level review of a complex multi-language monorepo, dispatch one comprehensive, read-only `agy -p` analysis task that explicitly scopes every sub-component (each language layer, infra, frontends) and asks for findings evaluated by **Impact, Level of Effort, and Risk**, consolidated into the repo's existing backlog format. Project-specific review case studies live in the reviewed project's own repo under `docs/hermes/`.
