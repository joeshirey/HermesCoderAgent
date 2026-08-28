---
name: systematic-debugger
description: Enforced 4-phase debugging pipeline. Blocks source edits until bug is reproduced, traced, and hypothesis tested. Integrates with auto-healer for the fix phase.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, systematic, pipeline, tdd, root-cause, regression-test]
    related_skills: [systematic-debugging, auto-healing, quality, test-driven-development]
---

# Systematic Debugger

Programmatic enforcement of the 4-phase debugging methodology. Use this for ALL bug fix tasks.

## When to trigger

Before dispatching any bug fix to the coding engine. The systematic debugger replaces direct dispatch for:

- Test failures
- Bug reports
- Unexpected behavior
- Regression fixes

Do NOT use for:

- New feature implementation
- Refactoring (unless it's fixing broken behavior)
- Style/formatting issues (use auto-healer directly)

## Dispatch

```
terminal(
    command="python3 ~/.hermes-coder/scripts/systematic_debugger.py --bug '<bug description>' --repo '<project-dir>' --engine claude-code --json",
    workdir="~/.hermes-coder",
    timeout=1800
)
```

## Resuming an interrupted session

```
terminal(
    command="python3 ~/.hermes-coder/scripts/systematic_debugger.py --resume '<bug-id>' --repo '<project-dir>' --engine claude-code --json",
    workdir="~/.hermes-coder",
    timeout=1800
)
```

The bug-id is found in the initial output or in `<repo>/.hermes-debug/`.

## The 4 phases

| Phase | What happens | Source edits allowed? |
|-------|-------------|---------------------|
| 1. Reproduce | Run failing test/trigger error, confirm consistent | No |
| 2. Trace | Trace data flow backward to root cause | No |
| 3. Hypothesize | Form hypothesis, write failing regression test | Test files only |
| 4. Fix | Delegate to auto-healer with the regression test | Yes (via auto-healer) |

The debugger enforces read-only access in phases 1-2. If the coding engine modifies source files during these phases, the changes are automatically reverted and logged.

## Reading the output

JSON output includes the full debug journal:

- `bug_id`: unique identifier for this debug session
- `current_phase`: where the pipeline stopped
- `phases`: status and evidence for each phase
- `source_edit_violations`: any unauthorized source edits that were reverted

## Debug journal

Each debug session creates a persistent journal at `<repo>/.hermes-debug/<bug-id>.json`. This journal:

- Records evidence from each phase
- Enables `--resume` for interrupted sessions
- Provides post-mortem context for retrospectives

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Fixed (all phases completed, tests passing) |
| 1 | Escalated (auto-healer exhausted retries) |
| 2 | Invalid arguments |
| 3 | Reproduction failed (not a real bug or environment issue) |
| 4 | Hypothesis rejected (regression test didn't fail as expected) |

## Relationship to the systematic-debugging skill

This script enforces the methodology documented in `skills/software-development/systematic-debugging/SKILL.md`. The behavioral skill describes *what* to do; this script enforces *that you do it* by gating each phase programmatically.
