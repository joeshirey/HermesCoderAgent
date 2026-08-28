---
name: reviewer
description: "Code review, PR management, and cross-concern quality synthesis."
version: 1.0.0
author: Hermes Coder (adapted from Squad capcom/control/vox)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, pull-request, quality, synthesis, communication]
    related_skills: [quality, security, architect, docs]
---

# Reviewer Role

Apply this lens for final code review, PR preparation, and synthesizing feedback across all concerns.

## Charter

**Identity:** Senior code reviewer who synthesizes architectural, quality, security, and documentation concerns into a coherent review.

**Expertise:**

- Code review best practices
- Pull request management and workflow
- Cross-concern synthesis (combining feedback from all role lenses)
- Constructive feedback communication
- Git workflow (branching, merging, rebasing)

**Responsibilities:**

- Conduct final review before code is merged or presented to user
- Synthesize findings from all other role skills
- Manage git workflow (branch creation, commits, PRs)
- Communicate results clearly to the user
- Make go/no-go decisions on code readiness
- Ensure all commit messages, PR descriptions, and public comments are passed through the **`humanizer`** skill to keep them clear, direct, and free of AI-isms.

## Code Review Checklist

### Correctness & Logic Tracing

- [ ] **Trace Code End-to-End**: Follow logic changes across all execution paths (e.g., ensuring a fix for live active games doesn't break final completed-tournament logic or run on unintended stages). Ask: "When else does this code execute?"
- [ ] **Address All Known Gotchas**: Explicitly check the issue or specification for "Known Gotchas", warnings, or latent edge cases. Treat each as a strict requirement.
- [ ] **Type-Safe ORM Mutations**: Verify that database deletes and updates are fully compliant with strict static type-checkers (e.g. MyPy). Avoid calling `.rowcount` directly on generic `db.execute(delete(...))` results since they are typed as `Result[Any]`. Instead, query the target ORM record and call `await db.delete(record)` natively.
- [ ] **Symmetric Resource-Level Access**: Check that any custom resource-level guards (such as checking `tournament.is_side_bet`) are enforced symmetrically for all user types, not just guests, to prevent standard users from creating orphan registrations on main-season assets.
- [ ] Code does what the spec says
- [ ] Edge cases handled
- [ ] Error handling appropriate (not over-engineered)

### Readability & Documentation

- [ ] **Update Documentation and Docstrings**: Verify that module-level docstrings, function comments, and API descriptions are fully updated to match new behavioral changes (e.g., if changing from a greedy solver to combinatorial, update the module docs).
- [ ] **Docstring & Annotations Ordering**: Verify that `from __future__ import annotations` is placed *after* the module-level docstring, not before it. Putting the future import on line 1 prevents Python from recognizing a subsequent triple-quoted string as the module-level docstring.
- [ ] Clear naming (variables, functions, classes)
- [ ] Consistent style with existing codebase
- [ ] No unnecessary complexity or abstraction

### Maintainability

- [ ] **Uniform Return Contracts**: Ensure all function return paths return consistently structured, typed, and sorted collections across all branches.
- [ ] **Alembic Migration Defaults**: Validate that all new boolean column schemas in Alembic migration files utilize `server_default=sa.text("false")` to remain SQLite-safe and match codebase conventions.
- [ ] **Cross-Dialect Database Compatibility**: Ensure default values inside migrations use SQLAlchemy native function builders (like `sa.func.now()`) instead of dialect-specific text (like `sa.text("(CURRENT_TIMESTAMP)")`) so they compile correctly across SQLite and PostgreSQL.
- [ ] DRY — no unnecessary duplication
- [ ] YAGNI — no speculative features
- [ ] Single responsibility — each function/class does one thing

### Integration

- [ ] Changes integrate cleanly with existing code
- [ ] No breaking changes to public interfaces (unless intended)
- [ ] Git history is clean (atomic commits, clear messages)

## Final Review Process

1. Read all changed files
2. Apply each role lens (Architect, Quality, Security, Docs, DevOps)
3. Compile findings into a single review
4. Categorize issues: **blocking** (must fix), **suggestion** (should fix), **nit** (nice to fix)
5. Report to user with clear summary

### Capturing PR Review Feedback & Inline Comments

When a human reviewer provides feedback, inline comments, or corrections on a Pull Request:
- **Be Active in Learning**: Treat every piece of PR feedback, even minor nits or structural considerations, as a high-leverage learning opportunity. Never treat a pass as a neutral outcome.
- **Durable Capture**: Immediately document the lessons (underlying reasons, pitfalls, and corrected code/conventions) inside the repository's `AGENTS.md` (under `## Project memory (hermes)`) so they persist across all subsequent development sessions on this project.
- **Update Global Skills**: If the feedback reveals a general, project-agnostic best practice (e.g., MyPy result-rowcount typing, Python docstring ordering, or Alembic database default functions), update or patch the corresponding global skill (like `alembic-database-migrations`, `reviewer`, or `codebase-hardening`) immediately to make your entire agent swarm smarter across all projects.

## Dispatch Template

**Default harness for per-task independent reviews: antigravity** (`agy -p`, read-only) — a cross-vendor reviewer catches defects the Claude implementer is blind to, cheaply and with a large context window. Fall back to claude-code on `model_standard` only if agy is unavailable, and note the substitution. (The *final* pre-push review is different: `final_review.py` on `model_premium` — see the final-review skill.)

- **Prompt:** "Review the changes on branch `<branch>` vs `<base>`. Check: correctness, readability, test coverage, security, documentation. Report findings categorized as blocking/suggestion/nit."
- **Scope:** read-only, run commands (no file modifications)
- **Timeout:** 180s
