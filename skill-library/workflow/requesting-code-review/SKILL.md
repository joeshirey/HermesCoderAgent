---
name: requesting-code-review
description: "Pre-commit verification: security scan, quality gates, independent code review."
version: 2.0.0
author: Hermes Coder (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, security, verification, quality, pre-commit]
    related_skills: [subagent-driven-development, writing-plans, test-driven-development]
---

# Pre-Commit Code Verification

Automated verification pipeline before code lands. Static scans, baseline-aware quality gates, an independent Claude Code review, and a fix loop.

**Core principle:** No agent should verify its own work. Fresh context finds what you miss.

## When to Use

- After implementing a feature or bug fix, before `git commit` or `git push`
- When user says "commit", "push", "ship", "done", "verify", or "review"
- After completing a task with 2+ file edits in a git repo
- After each task in subagent-driven-development (the two-stage review)

**Skip for:** documentation-only changes, pure config tweaks, or when user says "skip verification".

## Core Verification Principles

### 1. Never Verify Your Own Work Exclusively (Fresh Context)

Local unit and integration tests are essential, but they often execute within mock conditions that you designed, which can mask conceptual defects. Always subject complex or logic-heavy changes (such as authentication updates, live pollers, or rules hardening) to an independent, fresh-context code review pass to find hidden gaps like:

- **Unsafe Logic Fallbacks:** Check if default fallback values or unauthenticated requests accidentally inherit high-privilege roles (like defaulting a bypass to `admin` instead of `user`).
- **Weak Environmental Guards:** Check if local-only dev utilities (like bypasses or seeding scripts) are gated solely on `debug` mode. Ensure they are multi-gated using local-only signatures (such as `settings.is_sqlite and settings.debug`) to physically lock them out of production-grade contexts.

### 2. Trace the Fix End-to-End (Source to Sink)

Before declaring a feature or bug fix complete, trace the entire data flow from where it is produced (Source) to where it is consumed or stored (Sink). Ask yourself:

- *How does this code behave across all execution paths?* (e.g. Does a live-leaderboard fix inadvertently run or modify data during the authoritative final-results path?)
- *Are all database-level referential integrity and foreign-key constraints met?* SQLite may let invalid foreign key references (such as seeding an invitation with a nonexistent user ID) slide by default, whereas real database engines (PostgreSQL) will strictly reject them and fail. Always seed valid parent records first.

---

## Step 1 — Get the diff

```bash
terminal(command="git diff --cached", workdir="<project>")
```

If empty, try `git diff` then `git diff HEAD~1 HEAD`.

## Step 2 — Static security scan

Scan added lines for security concerns:

```bash
terminal(command="git diff --cached | grep '^+' | grep -iE '(api_key|secret|password|token|passwd)\\s*=\\s*[\"'\\''\"]{1}[^\"'\\''\"]{6,}'", workdir="<project>")
```

Check for: hardcoded secrets, shell injection (`os.system`, `subprocess.*shell=True`), dangerous eval/exec, unsafe deserialization (`pickle.loads`), SQL injection.

## Step 3 — Run tests and linting

Run the project's test suite and linting tools. Compare against baseline (stash changes, run, pop) to identify only NEW failures.

```bash
terminal(command="<test-command>", workdir="<project>")
```

## Step 4 — Coordinator self-review

Quick scan using the Reviewer role skill checklist:

- [ ] No hardcoded secrets or credentials
- [ ] Input validation on user-provided data
- [ ] SQL queries use parameterized statements
- [ ] No debug print/console.log left behind
- [ ] No commented-out code
- [ ] New code has tests

## Step 5 — Independent code review

Dispatch a fresh coding engine instance to review the diff. It has no context about how the changes were made. See the active harness skill (under `skills/harness/`) for the exact independent code review dispatch template.

- **Prompt:** "You are an independent code reviewer. Review this git diff for security concerns and logic errors. SECURITY (auto-FAIL): hardcoded secrets, shell injection, SQL injection, path traversal, eval with user input. LOGIC (auto-FAIL): wrong conditionals, missing error handling for I/O, off-by-one, race conditions. SUGGESTIONS (non-blocking): missing tests, style, performance, naming. Run: `git diff HEAD~1 HEAD`. Report: list security concerns, logic errors, and suggestions."
- **Scope:** read-only, run commands (no file modifications)
- **Timeout:** 120s

## Step 6 — Evaluate results

Combine results from Steps 2, 3, 4, and 5.

**All passed:** Proceed to commit.

**Any failures:** Report what failed, then proceed to fix loop.

## Step 7 — Fix loop (max 2 cycles)

Dispatch the coding engine to fix ONLY the reported issues. See the active harness skill for the fix loop dispatch template.

- **Prompt:** "Fix ONLY these specific issues. Do NOT refactor or change anything else: `<list of issues>`"
- **Scope:** read, edit, run commands
- **Timeout:** 120s

After fix, re-run Steps 1-6. If still failing after 2 cycles, escalate to user.

## Step 8 — Commit

```bash
terminal(command="git add -A && git commit -m '[verified] <description>'", workdir="<project>")
```

The `[verified]` prefix indicates independent review approved this change.

## Remember

```
Get diff -> Static scan -> Tests -> Self-review -> Independent review -> Fix -> Commit
No agent verifies its own work
Max 2 fix cycles, then escalate
```
