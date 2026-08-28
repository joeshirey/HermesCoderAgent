# Capability: Quality loop

The machinery that turns "the engine produced some code" into "the code is sized, fixed,
debugged systematically, and remembered." These pieces wrap each dispatch so quality is
enforced rather than hoped for.

## The pieces

### Complexity triage (sizing)

Before planning, every task is sized S/M/L/XL. The size sets a **tool budget** (max skills,
max turns) and a routing recommendation. S-sized tasks skip full planning and dispatch
directly; larger tasks get the full loop. Certain keywords (security, auth, crypto, schema
change, race condition) force the heavier treatment.

- **Script:** [`scripts/dynamic_curator.py`](../../scripts/dynamic_curator.py)
- **Skill:** [`complexity-triage`](../../skill-library/coordinator/complexity-triage/SKILL.md)

### Auto-healer (fix loop)

When a review/check fails, the auto-healer parses the failure (pytest/ruff/eslint/tsc/go-vet),
builds escalating fix prompts, and retries up to 3× before escalating to the user with
structured findings. The coordinator runs this before manually re-dispatching.

- **Script:** [`scripts/auto_healer.py`](../../scripts/auto_healer.py)
- **Skill:** [`auto-healing`](../../skill-library/coordinator/auto-healing/SKILL.md)

### Systematic debugger (no guess-and-check)

For bug fixes, the coordinator runs the debugger instead of dispatching a speculative fix.
It enforces reproduction → root-cause tracing → a failing regression test *before* any
production edit, then hands the fix to the auto-healer.

- **Script:** [`scripts/systematic_debugger.py`](../../scripts/systematic_debugger.py)
- **Skills:** [`systematic-debugger`](../../skill-library/coordinator/systematic-debugger/SKILL.md)
  (coordinator) and the deeper
  [`software-development/systematic-debugging`](../../skill-library/software-development/systematic-debugging/SKILL.md)
  (root-cause tracing, test-pollution bisection via `find-polluter.sh`).
- **Design note:** [`SYSTEMATIC_DEBUGGER.md`](SYSTEMATIC_DEBUGGER.md).

### Retrospective (memory loop)

After a struggle (auto-healer escalation/multi-retry, or any debugger session), the lesson
is captured. Before each dispatch, relevant prior lessons for that repo are injected into
the prompt so the team stops repeating mistakes.

- **Script:** [`scripts/retrospective.py`](../../scripts/retrospective.py)
- **Skill:** [`retrospective`](../../skill-library/coordinator/retrospective/SKILL.md)

### Parallel dispatch (throughput, safely)

When a plan has 2+ tasks touching disjoint files with no ordering dependency, they run
concurrently — each isolated in its own git worktree + branch. The coordinator reviews each
branch and merges sequentially. **Never auto-merges.**

- **Script:** [`scripts/parallel_dispatch.py`](../../scripts/parallel_dispatch.py)
- **Skill:** [`parallel-dispatch`](../../skill-library/coordinator/parallel-dispatch/SKILL.md)

## How they chain in the workflow

`triage` (size + budget) → inject `retrospective` lessons → dispatch (or `parallel_dispatch`
the batch, or run the `systematic_debugger` for bugs) → review → on failure run `auto_healer`
→ after a struggle, `retrospective` capture. See the Workflow section of
[`SOUL.md`](../../coordinator-core/SOUL.md).

## Config

The `triage`, `auto_healing`, `systematic_debugger`, `retrospective`, and
`parallel_dispatch` blocks in
[`config.sample.yaml`](../../coordinator-core/config.sample.yaml).

## Guardrails

- Don't manually retry a failed check more than once without the auto-healer.
- Don't skip the systematic debugger for bugs in favor of guess-and-check.
- Don't skip retrospective capture after a real struggle.
- Don't auto-merge parallel branches — review each, merge sequentially.
