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

### Step 2: Explore the Codebase & Sync with Remote

- **Always Synchronize with the Remote First**: Before drafting any plan, proposing next steps, or recommending PR merges, checkout the default/target branch (`main` or `master`), pull the latest changes from the remote, and query the live status of active pull requests and issues on GitHub (`gh pr list`, `gh issue list`). The user or other agents may have merged PRs or mutated issue states out-of-band since your last session.
- **Clean Branch Hygiene & Planning File Preservation**: When transitioning from a "planning-only" phase (e.g., after a weekend code freeze) to the implementation phase, do NOT write code on top of dirty branches carrying unrelated experiments. Checkout `main`, pull the latest remote, and create a fresh working branch. To keep your drafted markdown plans and specifications immediately available on this fresh branch without bringing over unwanted draft code commits, use:
  `git checkout <spec-branch> -- docs/hermes/<plan-files>`
  This safely checks out only the planning documents from the old branch into your new, clean branch's working tree, keeping them staged and ready.
- **Inspect Project Structure**: Use terminal and file tools to understand the project structure, existing patterns, and conventions.

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

### Monorepo & Stale Compilation Hygiene

When planning or executing verification checks in TypeScript/JS or compiled-asset monorepos (such as `squad` or Go applications with generated views), always ensure that a complete, clean build is run (e.g. `npm run build`, `templ generate`) *before* executing the test runner. Running tests directly after making code edits in these environments will often execute against stale, outdated build artifacts (such as compiled JS in `dist/` or `out/`), resulting in false-negative test failures and misleading diagnostic paths.

### React Router Context and React Query Testing Pitfalls

When writing or executing tests for React components that leverage navigation or data-fetching hooks:
1. **React Router Context:** Any component rendering `<Link>` or using routing hooks (`useNavigate`, `useParams`) will crash during test renders with `TypeError: Cannot destructure property 'basename' of 'React.useContext(...)'` unless it is wrapped inside a router context. Always ensure the test wrapper wraps the component in `<MemoryRouter>` from `react-router-dom`.
2. **React Query Loading State Pitfall:** In React Query, during the initial render, query data is `undefined` before the mocked promise resolves. If a component renders a fallback message (e.g., "Loading..." or "No week open") during this loading phase, assertions like `expect(screen.getByText("No week open")).toBeInTheDocument()` will pass instantly—succeeding during the loading phase before the mock has actually resolved to its final state! To write robust tests, always assert against elements that *only* appear in the fully resolved state (e.g., using `await screen.findByText("Picks Locked")` or `await waitFor(...)` on resolved elements) to ensure the test waits for mock promise resolution.
3. **Date-dependent UI Testing Pitfalls (Timestamp Drift & Mock Clocks):** When a component or utility derives state by comparing the current system time (`new Date()`) against database/mock timestamps (e.g., a lock time or tournament start date), hard-coded mock timestamps in test files will eventually drift into the past relative to the system clock. This causes tests asserting on "upcoming" or "open" states to silently fail or change behavior. Always ensure mock timestamps in test fixtures are either dynamically generated relative to the current time (e.g., `new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()`) or set to a far-future static date (e.g., `2099-12-31`) to guarantee they never transition into the past.

### React Query Derived Defaults Pattern (Overriding State Sync Effects)

When developing filters or selectors driven by asynchronous server state, do NOT use `useEffect` hooks to synchronize server defaults into local state (this triggers performance-degrading double renders and strict ESLint exhaustive-deps errors).

Instead, leverage **derived values** computed on-the-fly during the render pass (e.g., `const effectiveId = selectedId || activeIdFromQuery || ""`).

For a complete reference, boilerplate code, and architectural guidelines, consult the support file:
`references/react_query_derived_defaults.md` (accessible via `skill_view(name='writing-plans', file_path='references/react_query_derived_defaults.md')`).

### Sequential Backlog Triage and Timeout Prevention

When executing bulk backlog mutations (such as triage or enrichment across multiple issues), running a single monolithic command (e.g. `triage --limit 20`) can easily exceed tool execution timeouts. Because each issue requires research, RFC-style drafting, and humanizing, a single issue can take 100–150 seconds. The most reliable and robust workflow is to execute the backlog tool with `--limit 1` inside sequential, discrete tool calls. This saves intermediate progress incrementally on each iteration and completely prevents cascading timeouts.

### Verification of Existing Function Signatures & API Contracts

When drafting implementation plans that direct a coding engine to consume or integrate with existing utility functions, model methods, or API clients:
- **Never Assume or Fabricate Signatures:** Do not guess, assume, or infer parameters, types, or return shapes of existing utilities (e.g. assuming `formatPickedValue(type, value)` accepts a third `options` argument). Writing incorrect method signatures in task dispatches will cause compilation failures, break TypeScript type-checking, and halt automated build execution.
- **Verify the Codebase First:** Always read the source files containing the target functions beforehand, verify their exact signatures and arguments, and reference the correct structure explicitly inside the task dispatches to ensure the build remains perfectly green and compatible.

## Handling External Peer-Reviews & Iterative Re-Planning

When a user or an external peer-reviewer (like a senior lead or another agent) provides critical feedback or a post-scoring audit on your plans or specifications:

1. **Deconstruct & Categorize Findings:**
   - **Hard Blockers / Prerequisites:** Issues that intersect or compromise the core security, auth, or concurrency state (like pre-lock leaks, dev backdoors, or token races) must be resolved **before** building the feature. Extend the plan's Phase 1 to cover them.
   - **Inline Quality Fixes:** Issues that can be solved directly within the feature's code paths (like KeyError fallbacks or cache purges) should be folded directly into the main task dispatches.
   - **CI & Deployment Gating:** Secure the pipeline (e.g., gating deployments on test success) early to prevent broken rollout states.

2. **Clean Branch Alignment:**
   - When proceeding from a plan/review phase to implementation, checkout `main` and pull the latest remote gold standard.
   - Delete any local merged or experimental branches to keep the git tree pristine.
   - Create a clean new implementation branch from remote main. To preserve your drafted plans and specifications from your spec branch without bringing over unwanted draft code commits, checkout only the plans:
     `git checkout <spec-branch> -- docs/hermes/<plan-files>`
   - This keeps your plans staged and accessible on your clean working branch.

3. **Prerequisites First, Local Verification Always:**
   - Execute the prerequisite cleanups as standalone, focused, well-tested commits before writing any feature code.
   - Verify every fix locally. Ensure both backend and frontend test suites are 100% green before pushing.

---

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
