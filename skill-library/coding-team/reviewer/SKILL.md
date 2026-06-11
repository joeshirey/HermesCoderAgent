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
- [ ] Code does what the spec says
- [ ] Edge cases handled
- [ ] Error handling appropriate (not over-engineered)

### Readability & Documentation

- [ ] **Update Documentation and Docstrings**: Verify that module-level docstrings, function comments, and API descriptions are fully updated to match new behavioral changes (e.g., if changing from a greedy solver to combinatorial, update the module docs).
- [ ] Clear naming (variables, functions, classes)
- [ ] Consistent style with existing codebase
- [ ] No unnecessary complexity or abstraction

### Maintainability

- [ ] **Uniform Return Contracts**: Ensure all function return paths return consistently structured, typed, and sorted collections across all branches.
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

## Dispatch Template

**Default harness for per-task independent reviews: antigravity** (`agy -p`, read-only) — a cross-vendor reviewer catches defects the Claude implementer is blind to, cheaply and with a large context window. Fall back to claude-code on `model_standard` only if agy is unavailable, and note the substitution. (The *final* pre-push review is different: `final_review.py` on `model_premium` — see the final-review skill.)

- **Prompt:** "Review the changes on branch `<branch>` vs `<base>`. Check: correctness, readability, test coverage, security, documentation. Report findings categorized as blocking/suggestion/nit."
- **Scope:** read-only, run commands (no file modifications)
- **Timeout:** 180s
