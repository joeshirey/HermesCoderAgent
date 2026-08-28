---
name: auto-healing
description: Automated fix loop for failed Quality/Reviewer checks. Parses failures, builds escalating prompts, dispatches through the active harness up to 3 times.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [auto-healing, retry, fix-loop, quality, testing, escalation]
    related_skills: [implementer, quality, reviewer, systematic-debugger]
---

# Auto-Healing

Automated retry loop when Quality or Reviewer checks fail. Replaces manual re-dispatch.

## When to trigger

After ANY of these:

- Test suite fails after a coding engine dispatch
- Linter/formatter check fails (ruff, eslint, flake8)
- Type checker fails (tsc, mypy, pyright)
- Build fails (go build, cargo build)

Do NOT trigger for:

- Architecture or design review feedback (those need human judgment)
- Security review findings (those need security skill review)
- First-time implementation (use the coding engine directly)

## Dispatch

```
terminal(
    command="python3 ~/.hermes-coder/scripts/auto_healer.py --repo '<project-dir>' --check '<test command>' --engine <active-harness> --json",
    workdir="~/.hermes-coder",
    timeout=600
)
```

The `--engine` flag must match the active session harness (claude-code, antigravity, or opencode).

The `--check` command is the exact command that failed:

- pytest: `"pytest -x"` or `"pytest tests/test_specific.py -x"`
- ruff: `"ruff check ."`
- eslint: `"npx eslint src/"`
- tsc: `"npx tsc --noEmit"`
- go: `"go vet ./..."`

## Reading the output

JSON output (`--json` flag):

- `status`: `"clean"` (checks already passing), `"healed"` (fixed), or `"escalated"` (all attempts failed)
- `attempts`: array of attempt details (prompt summary, output, success)
- `remaining_failures`: structured list of still-broken items (only when escalated)
- `escalation_reason`: why it gave up (only when escalated)

## Escalation behavior

The auto-healer uses 3-tier escalation matching the implementer skill's framework:

1. **Attempt 1 (targeted):** Fix only the specific issues listed
2. **Attempt 2 (context-enriched):** Adds file context, prior attempt analysis
3. **Attempt 3 (simplified):** Breaks remaining failures into single-file fixes

If all 3 attempts fail, the status is `"escalated"`. At that point:

- Report the structured findings to the user
- Include the remaining failures and what was tried
- Do NOT attempt more fixes without user guidance

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Healed or already clean |
| 1 | Escalated (all attempts failed) |
| 2 | Invalid arguments |
| 3 | Check command itself errored (infrastructure problem) |
