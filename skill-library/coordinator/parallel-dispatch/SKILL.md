---
name: parallel-dispatch
description: Run independent, file-disjoint plan tasks concurrently, each isolated in its own git worktree + branch. Collects per-task results; never auto-merges.
version: 1.0.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [parallel, concurrency, dispatch, worktree, batch, git, multi-task]
    related_skills: [implementer, architect, reviewer]
---

# Parallel Multi-Task Dispatching

The coordinator normally dispatches plan tasks one at a time. When a feature decomposes into
**independent, file-disjoint** modules (e.g. backend API + frontend mockup + DB migration), that
serial loop wastes wall-clock time. This tool fires the batch concurrently — each task isolated in
its own git worktree + branch — and collects the results. You still decide what is independent;
the script only runs the mechanics safely.

## When to trigger

Use it when **all** of these hold:

- The plan has 2+ tasks that touch **disjoint** files/directories.
- The tasks have **no ordering dependency** (none needs another's output).
- The target is a git repository.

Do NOT use it for:

- Tasks with sequential dependencies (build the schema, then the code that uses it).
- Tasks that edit the **same** files (worktrees isolate them, but the merge becomes a conflict).
- A single task — just dispatch it normally.

## Before building the batch

Inject prior lessons into **each** task prompt first (the normal retrospective step), then
assemble the spec. The script dispatches the prompts verbatim — it does no injection itself.

## Spec format

```json
{"tasks": [
  {"id": "api", "prompt": "<self-contained task>", "scope": ["src/api/**"], "max_turns": 20},
  {"id": "ui",  "prompt": "<self-contained task>", "scope": ["src/ui/**"],  "max_turns": 20}
]}
```

`id`: unique, `^[A-Za-z0-9_-]+$` (also the worktree/branch name). `prompt`: non-empty,
self-contained. `scope`: optional path globs — advisory; surfaces an overlap warning and guides
the merge review. `max_turns`: optional (default 15).

## Dispatch

```
terminal(command="echo '<spec-json>' | python3 ~/.hermes-coder/scripts/parallel_dispatch.py --repo '<project-dir>' --engine <active-harness> --max-parallel 3 --json", workdir="~/.hermes-coder", timeout=1800)
```

Dry run (validate + print the planned worktree paths and dispatch commands; creates/dispatches
nothing — use it to sanity-check a batch before committing engine time):

```
terminal(command="echo '<spec-json>' | python3 ~/.hermes-coder/scripts/parallel_dispatch.py --repo '<project-dir>' --dry-run --json", workdir="~/.hermes-coder", timeout=60)
```

## How isolation works

- Worktrees are created **serially** (`git worktree add -b <prefix><id> <wt-dir>/<id> <base>`) to
  avoid git index/ref lock races, then dispatched **concurrently** (capped at `--max-parallel`).
- Each engine runs with its `cwd` set to its own worktree — zero in-tree collision.
- The tool **never merges and never deletes existing branches**. Worktrees are kept after the run
  because they hold the uncommitted work.

## Merge-back workflow (your job)

1. Read the `BatchReport`; for each `success` result, review its branch with the Quality and
   Reviewer lenses.
2. Merge the reviewed branches **sequentially** into the base — resolve conflicts as they arise.
   **Never auto-merge.**
3. After a branch is merged, clean up its worktree: `git worktree remove <worktree-path>`.
4. For `failed`/`timeout`/`error` results, inspect `output_tail`/`error` and re-dispatch or
   auto-heal as usual.

## Reading the output (`--json`)

`BatchReport`: `engine`, `repo`, `base_ref`, `dry_run`, `total`, `succeeded`, `failed`,
`warnings[]`, and `results[]` of `DispatchResult` — `id`, `branch`, `worktree`, `status`
(`success|failed|timeout|error`, or `dry-run`), `returncode`, `duration_s`, `output_tail`,
`error`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All dispatches succeeded (or dry-run completed) |
| 1 | One or more dispatches failed — report still emitted |
| 2 | Invalid arguments / not a git repo / bad spec |
