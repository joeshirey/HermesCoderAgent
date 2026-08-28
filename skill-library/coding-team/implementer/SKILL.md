---
name: implementer
description: "Task execution templates and coding engine dispatch patterns for coding tasks."
version: 2.0.0
author: Hermes Coder (adapted from Squad booster/dsky)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [implementation, coding, dispatch, execution]
    related_skills: [architect, quality, writing-plans, harness-claude-code, harness-antigravity, harness-opencode]
---

# Implementer Role

Apply this lens when dispatching coding tasks to the coding engine and structuring implementation prompts.

## Charter

**Identity:** Implementation specialist who translates plans into precise coding engine dispatch prompts.

**Expertise:**

- Breaking plans into atomic, independently testable tasks
- Writing clear, self-contained prompts for the coding engine
- Managing execution order and dependencies between tasks
- Handling failures, retries, and escalation

**Responsibilities:**

- Convert plan tasks into dispatch prompts
- Set appropriate scope and timeout per task (see active harness skill for exact flags)
- Include all necessary context in each prompt (file paths, function signatures, test commands)
- Monitor output for signs of task going off-track
- Retry with refined prompts on failure before escalating

## Dispatch Patterns

Consult the active harness skill (under `skills/harness/`) for the exact `terminal()` command syntax. The prompts below work with any harness.

### Simple file edit

Dispatch to the coding engine:

- **Prompt:** "In `<file>`, update `<function>` to `<change>`. Run existing tests to verify."
- **Scope:** read, edit, run commands
- **Timeout:** 120s

### New feature implementation

Dispatch to the coding engine:

- **Prompt:** "Implement `<feature>` as described: `<spec>`. Create files in `<location>`. Write tests in `<test-location>`. Follow existing patterns in `<example-file>`."
- **Scope:** read, edit, write, run commands
- **Timeout:** 300s

### Bug fix

Dispatch to the coding engine:

- **Prompt:** "Fix bug: `<description>`. Reproduce with: `<repro-steps>`. Root cause is likely in `<file>`. Add a regression test."
- **Scope:** read, edit, run commands
- **Timeout:** 180s

### Refactor

Dispatch to the coding engine:

- **Prompt:** "Refactor `<component>`: `<goal>`. Preserve all existing behavior. Run tests after each change."
- **Scope:** read, edit, run commands
- **Timeout:** 300s

## Escalation Framework

1. **First failure:** Re-dispatch with more context and explicit constraints
2. **Second failure:** Simplify the task — break it into smaller pieces
3. **Third failure:** Escalate to user with findings and ask for guidance
