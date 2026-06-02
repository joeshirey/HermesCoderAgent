---
name: writing-plans
description: "Write implementation plans: bite-sized tasks for coding engine dispatch."
version: 2.0.0
author: Hermes Coder (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, design, implementation, workflow, documentation]
    related_skills: [subagent-driven-development, test-driven-development, requesting-code-review]
---

# Writing Implementation Plans

## Overview

Write comprehensive implementation plans assuming the implementer (Claude Code) has zero context for the codebase. Document everything: which files to touch, complete code, testing commands, docs to check, how to verify. Give them bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

The coding engine receives each task as a self-contained one-shot prompt — it cannot see the plan or prior tasks. Every task must be fully self-contained.

**Core principle:** A good plan makes implementation obvious. If the coding engine has to guess, the plan is incomplete.

## When to Use

**Always use before:**

- Implementing multi-step features
- Breaking down complex requirements
- Any work that will involve multiple coding engine dispatches

**Don't skip when:**

- Feature seems simple (assumptions cause bugs)
- Working on a small change (planning takes 2 minutes, debugging takes hours)

## Bite-Sized Task Granularity

**Each task = one focused coding engine dispatch.**

Every task should be completable in a single coding engine dispatch. If a task needs more, break it down further.

**Too big:**

```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**

```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## Plan Document Structure

### Header (Required)

```markdown
# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]
**Architecture:** [2-3 sentences about approach]
**Tech Stack:** [Key technologies/libraries]
**Project Directory:** [Absolute path to project root]

---
```

### Task Structure

Each task follows this format:

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py`
- Test: `tests/path/to/test_file.py`

**Dispatch Prompt:**
```
[The exact prompt to pass to the coding engine, including all context needed]
```

**Scope:** read, edit, write, run commands
**Timeout:** 180

**Verification:**
Run: `pytest tests/path/test.py -v`
Expected: PASS
````

## Writing Process

### Step 1: Understand Requirements

Read and understand the feature requirements, constraints, and acceptance criteria.

### Step 2: Explore the Codebase

Use terminal and file tools to understand the project structure, existing patterns, and conventions.

### Step 3: Design Approach

Decide on architecture, file organization, dependencies, and testing strategy.

### Step 4: Write Tasks

Create tasks in order:

1. Setup/infrastructure: **Always** make the very first task of any project initialization include creating and committing a robust `.gitignore` file. Build dependencies (like `node_modules/`), compiled binaries, local caches, and temporary files must be ignored *before* other feature files are staged.
2. Core functionality (TDD for each)
3. Edge cases
4. Integration
5. Cleanup/documentation

### Step 5: Write Dispatch Prompts

For each task, write the exact prompt for the coding engine. Include:

- **Exact file paths** (not "the config file" but `src/config/settings.py`)
- **Complete context** (the coding engine can't see previous tasks)
- **Exact test commands** with expected output
- **Verification steps**

### Step 6: Review the Plan

Check:

- [ ] Tasks are sequential and logical
- [ ] Each task is completable in one coding engine dispatch
- [ ] Dispatch prompts are self-contained (no references to "the plan" or "previous task")
- [ ] File paths are exact
- [ ] Test commands are exact with expected output
- [ ] DRY, YAGNI, TDD principles applied

## Execution Handoff

After completing the plan:

**"Plan complete. Ready to execute using subagent-driven-development — I'll dispatch the coding engine per task with two-stage review (spec compliance then code quality). Shall I proceed?"**

## Principles

### Scaffolding & Repository Hygiene

When starting a new project or adding sub-projects, always configure a robust `.gitignore` file before running any package managers (like `npm install`, `go mod`, `cargo build`) or compiling templated assets. If dependency folders like `node_modules/`, local `.cache/` folders, or transient test/build binaries are accidentally tracked, they clutter commits and pollute the remote repository. If any slip through, immediately run `git rm -r --cached <paths>` to untrack them.

### Self-Contained Prompts

The coding engine has no memory between dispatches. Each prompt must include all context needed: file paths, function signatures, project conventions, related code snippets.

### DRY (Don't Repeat Yourself)

Extract shared utilities. Don't copy-paste validation in 3 places.

### YAGNI (You Aren't Gonna Need It)

Implement only what's needed now. No speculative features.

### TDD (Test-Driven Development)

Every task that produces code includes the full TDD cycle in its dispatch prompt:

1. Write failing test first
2. Run to verify failure
3. Write minimal code
4. Run to verify pass

### Repository Hygiene First

When initializing a new repository, directory structure, or toolchain, always establish a comprehensive `.gitignore` file as the very first step. Never stage or commit changes without checking that dependency directories (such as `node_modules/`), compiled binaries, local tools caches (e.g. `tmp/` or test/run artifacts), or credentials are kept untracked. If files are accidentally tracked, run `git rm -r --cached <files>` immediately to untrack them before any pull request is merged.

## Remember

```
Bite-sized tasks (one coding engine dispatch each)
Self-contained prompts (no external context)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
```

**A good plan makes implementation obvious.**
