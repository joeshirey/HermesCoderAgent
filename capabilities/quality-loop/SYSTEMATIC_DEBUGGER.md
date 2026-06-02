# RFC: Programmatic Systematic Debugger (Enforced Workflow)

This document specifies the design for a **Programmatic Systematic Debugger** workflow within the `hermes-coder` profile, upgrading our existing `systematic-debugging` skill from a passive behavioral guideline into an enforced, programmatic pipeline.

---

## 1. The Core Problem: LLM "Guess-and-Check" Thrashing

When encountering bug reports or failing test suites, even advanced LLMs are highly susceptible to "guess-and-check" thrashing. They often propose a speculative fix, run the tests, fail, propose another slightly modified fix, and repeat—resulting in:

- High token costs and API delays.
- Symptom-level "band-aid" patches that mask the root cause.
- Fragile codebases prone to immediate regressions.

### The Solution

We transition the **Systematic Debugging** blueprint (adapted from [obra/superpowers](https://github.com/obra/superpowers)) into a **Programmatic Workflow wrapper**.

By wrapping execution in an enforced script or coordinator protocol, we programmatically block the coding engine from making edit calls on production code until it has **gathered empirical evidence, traced the data-flow, and verified a reproduction test case**.

---

## 2. Workflow vs. Skill: My Opinion & Recommendation

- **A Skill (Behavioral):** Tells the model *how* to think. (Crucial, but bypassable under pressure or due to model laziness).
- **A Workflow (Enforced/Programmatic):** Enforces *what* the model is allowed to do.

**My Recommendation: The Hybrid "Enforced Workflow" Architecture**
We should combine both. We load your rich `systematic-debugging` skill folder as the mental guide, but we implement a **Debugging Gatekeeper** script (`scripts/systematic_debugger.py`) that acts as a hard checkpoint. The Coordinator will reject any production file edits until the Gatekeeper script validates that the reproduction and data-flow tracing steps have been executed.

---

## 3. The 4-Phase Programmatic Pipeline

```
                       ┌─────────────────────────┐
                       │     Bug / Fail Event    │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ PHASE 1: REPRODUCTION   │
                       │ (Generate Trace Journal)│
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ PHASE 2: TRACING        │
                       │ (AST Lineage Tree)      │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ PHASE 3: HYPOTHESIS     │
                       │  (Write Failing Test)   │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ PHASE 4: SURGICAL FIX   │
                       │ (Apply and Dual-Verify) │
                       └─────────────────────────┘
```

### Phase 1: Programmatic Reproduction & Journaling

- **Action:** The Coordinator executes the test run or trigger command via `terminal()` in a sterile container/runner sandbox.
- **Evidence Logging:** Captures stdout, stderr, and the exact exit codes.
- **The "Debug Journal":** Compiles these diagnostics into a local structured JSON file (`~/.hermes-coder/debug_journal.json`). Production file writes are programmatically locked until this file is populated.

### Phase 2: Automated Data-Flow Tracing

- **Action:** Using the stack trace from the journal, the Coordinator runs a static analysis pass over the call chain:
  - Locates the file and line number where the exception occurred.
  - Recursively traces variables upstream (e.g., tracking where the failing variable was instantiated or passed).
  - Searches for identical patterns in the codebase to find "known good" configurations.
- **Bisection (Test Pollution):** If the failure is flaky or suspected to be test-pollution (where one test pollutes global state and breaks a subsequent test), the Coordinator executes the imported bisection tool:
  `~/.hermes-coder/skills/software-development/systematic-debugging/find-polluter.sh`

### Phase 3: Minimal Reproduction Test (The Hypothesis Gate)

- **The Core Rule:** *The coding engine is strictly forbidden from modifying production source files until it has written a test that reproduces the bug.*
- **Action:** The engine writes a targeted, minimal unit test case (following our `test-driven-development` skill).
- **Verification:** The Coordinator executes *only* this new test case.
  - **Expected Result:** Must fail (`RED`).
  - If the test passes or errors out on something else, the hypothesis is rejected, and the engine is forced back to Phase 1.

### Phase 4: Surgical Fix & Dual Verification

- **Action:** Once the hypothesis is proven by the failing test, the engine is unlocked to write the minimal, targeted fix in the source code.
- **The Dual-Verification Gate:**
  1. **Reproduction Check:** Runs the newly written test case. It must now pass (`GREEN`).
  2. **Regression Sweep:** Runs the *entire* project test suite. All tests must pass.
  - **Self-Healing Loop:** If any existing test fails, the Coordinator rolls back the change using filesystem checkpoints, appends the traceback to the `debug_journal.json`, and triggers a refined bug-fix dispatch.

---

## 4. Integration with Existing Backlog Enhancements

This systematic debugger integrates beautifully with our prior designs:

1. **Local Model Delegation (Item #8):**
   - Since debugging is highly iterative and token-heavy, we delegate the reproduction loop, trace-gathering, and unit-test writing to your local **`qwen3-coder-next`** or **`deepcoder:14b`** model.
   - This saves massive cloud costs while performing thorough research.
2. **Security Gateway (Item #6):**
   - If the debugging process requires tracing network payloads or executing arbitrary script boundaries, the container interface automatically routes execution into the secure, hyper-performant **Apple Containers** sandbox.

---

## 5. Implementation Status

The debugging assets (including `root-cause-tracing.md` and `find-polluter.sh`) live under
`skill-library/software-development/systematic-debugging/`. The orchestrator script
(`scripts/systematic_debugger.py`) handles JSON journaling, test bisection, and verification
loops. `SOUL.md` makes the debugger workflow the mandatory gateway for all bug dispatches.
