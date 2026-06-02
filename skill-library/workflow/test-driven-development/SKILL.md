---
name: test-driven-development
description: "TDD: enforce RED-GREEN-REFACTOR in coding engine dispatches."
version: 2.0.0
author: Hermes Coder (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, tdd, development, quality, red-green-refactor]
    related_skills: [writing-plans, subagent-driven-development, requesting-code-review]
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Every coding engine dispatch that produces code MUST include TDD instructions.

## Red-Green-Refactor Cycle

### RED — Write Failing Test

Write one minimal test showing what should happen. Clear name, tests real behavior, one thing.

### Verify RED — Watch It Fail

**MANDATORY. Never skip.** Run the test, confirm it fails because the feature is missing.

### GREEN — Minimal Code

Write the simplest code to pass the test. Nothing more.

### Verify GREEN — Watch It Pass

Run the specific test (pass), then run ALL tests (no regressions).

### REFACTOR — Clean Up

After green: remove duplication, improve names, extract helpers. Keep tests green.

### Repeat

Next failing test for next behavior.

## Coding Engine Integration

Every implementation prompt to the coding engine must include TDD instructions. Consult the active harness skill (under `skills/harness/`) for the exact dispatch syntax. The TDD prompt template:

- **Prompt:** "Implement `<feature>` using strict TDD:
  1. Write a failing test FIRST in `<test-file>`
  2. Run the test to verify it fails: `<test-command>`
  3. Write minimal code to make the test pass
  4. Run the test to verify it passes
  5. Run the full test suite to check for regressions: `<full-test-command>`
  6. Refactor if needed (keep tests green)
  7. Commit with: `git add <files> && git commit -m '<message>'`"
- **Scope:** read, edit, write, run commands
- **Timeout:** 300s

## Coordinator Verification

After the coding engine completes, verify TDD was followed:

- [ ] Test files were created/modified BEFORE implementation files
- [ ] Tests cover the new behavior
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] All tests pass
- [ ] No regressions in existing tests

If the coding engine skipped TDD (wrote code before tests), re-dispatch with explicit TDD enforcement.

## Common Rationalizations (Don't Accept These)

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "Test hard = complex" | Hard to test = hard to use. Simplify the design. |

## Exceptions (User Must Explicitly Approve)

- Throwaway prototypes
- Generated code
- Configuration files
- Documentation-only changes

## Remember

```
Test first, always
Watch it fail
Minimal code to pass
Run all tests
No exceptions without user approval
```
