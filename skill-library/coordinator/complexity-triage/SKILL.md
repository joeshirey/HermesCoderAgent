---
name: complexity-triage
description: T-shirt sizing for tasks before dispatch. Runs heuristics and optionally LLM classification to determine task size (S/M/L/XL), recommend local vs cloud routing, and set tool budgets.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [triage, complexity, routing, dispatch, planning, t-shirt-sizing]
    related_skills: [local-model-router, writing-plans, architect, skill-discovery]
---

# Complexity Triage

Run before planning to classify task complexity and set dispatch parameters.

## When to use

Before every coding engine dispatch. The triage result determines:

- Whether to plan (M/L/XL) or dispatch directly (S)
- Which model to use (local gemma4 for S, cloud gemini-3.5-flash for M+)
- Tool budget (max skills, max MCP tools, max turns)
- Which skills to inject via --append-system-prompt

## Dispatch

```
terminal(
    command="python3 ~/.hermes-coder/scripts/dynamic_curator.py --task '<task summary>' --repo '<project-dir>'",
    workdir="~/.hermes-coder",
    timeout=30
)
```

## Reading the output

The script outputs JSON:

- `size`: S, M, L, or XL
- `confidence`: high, medium, or low
- `method`: heuristic, llm, or fallback
- `routing.engine`: "local" or "cloud"
- `routing.model`: model identifier
- `tool_budget`: max_skills, max_mcp_tools, max_turns
- `skill_matches`: top matched skills to inject

## Size definitions

| Size | Characteristics | Action |
|------|----------------|--------|
| S | Single file, trivial verb, CSS-only, typo | Skip planning, raw dispatch, local model OK |
| M | Multi-file logic, new component, helper utility | Plan, selective skill injection, cloud model |
| L | New feature, major refactor, multi-file integration | Full plan, full skill injection, cloud model |
| XL | Architecture change, system redesign | Full plan, architect review, cloud model |

**Every size dispatches to the coding engine.** Size never licenses the coordinator to edit repo
files itself — an S task is a *small dispatch*, not an inline edit. (2026-07-10: inline
implementation by the coordinator burned two full turn budgets and shipped below the quality bar.)

## Fallback

The triage LLM pass runs through the active coding harness (resolved from `--engine`/`coding.default_engine`). If the harness is unavailable, heuristic-only triage still works (exit code 3). If heuristics are inconclusive and no LLM is available, the script defaults to M sizing with cloud routing.
