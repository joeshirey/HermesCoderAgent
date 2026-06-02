# RFC: Humanizer & Prose Calibration Gateway (Enforced Workflow)

This document specifies the design for a **Humanizer & Prose Calibration Gateway** in the `hermes-coder` profile, integrating the imported `humanizer` skill to ensure that all human-facing assets (PRs, commits, changelogs, docs) are completely free of "AI slop" and read with authentic, human-like rhythm and voice.

---

## 1. The Core Objective: Eradicating "AI Slop"

AI-generated text is highly recognizable due to specific tells: significance inflation ("pivotal moment"), superficial present-participle trailing clauses ("ensuring that..."), passive structures, and predictable, sterile rhythm.

In public repositories or collaborative settings, AI-written commit messages, PR descriptions, and documentation feel unnatural and can burn developer reputation.

### The Solution

We implement an automated **Humanizer Gateway** as part of the Coordinator’s dispatch pipeline. The Coordinator selectively intercepts human-facing prose drafts, parses them through the `humanizer` rule engine (adapted from [blader/humanizer](https://github.com/blader/humanizer)), and calibrates them to match the user’s writing voice before any external write occurs.

---

## 2. Selective Execution: What to Humanize (and What to Skip)

We do not run the humanizer on mechanical, internal transactions—only on external, human-facing artifacts:

| Artifact Type | Target Audience | Humanizer Gate | Formatting Goal |
|---|---|---|---|
| **Git Commits** | External Developers / Humans | **MANDATORY** | Short, lowercase, active verb, no fluff (e.g., `fix container mem limits` instead of `Fix: Optimize and resolve container memory bounds`). |
| **GitHub PRs** | Maintainers / Humans | **MANDATORY** | Concise, filled templates, factual diff details, zero marketing fluff. |
| **Code Documentation** | Developers / Users | **MANDATORY** | Varied sentence lengths, active voice, zero sign-of-AI vocabulary (no "pivotal", "testament", "delve"). |
| **Internal Comments** | Coding Agents / Sandboxes | **SKIP** | Keep dense, structured, and technically literal (JSON/Markdown specs). |
| **Gateway Chat Summaries** | You (The Human Partner) | **MANDATORY** | Labeled bullet points, natural friendly voice, no conversational filler or preambles. |

---

## 3. The Humanizer Pipeline Architecture

```
                  ┌─────────────────────────────────┐
                  │    Draft Asset (PR/Commit/Doc)  │
                  └────────────────┬────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │     Selective Gate Intercept    │
                  │ (Check if artifact is external) │
                  └────────────────┬────────────────┘
                                   │
                       No (Skip)   ├───────────────────────────────┐
                                   │ Yes (Process)                 │
                                   ▼                               ▼
                      ┌─────────────────────────┐     ┌─────────────────────────┐
                      │    Direct Output /      │     │  1. Voice Calibration   │
                      │    Mechanical Write     │     │     (Git Log Sample)    │
                      └─────────────────────────┘     └────────────┬────────────┘
                                                                   │
                                                                   ▼
                                                      ┌─────────────────────────┐
                                                      │  2. AI-Slop Filtering   │
                                                      │    (Rule-based checks)  │
                                                      └────────────┬────────────┘
                                                                   │
                                                                   ▼
                                                      ┌─────────────────────────┐
                                                      │   3. Double-Pass Polish │
                                                      │  ("Make it not obvious")│
                                                      └────────────┬────────────┘
                                                                   │
                                                                   ▼
                                                      ┌─────────────────────────┐
                                                      │   Write Final Asset     │
                                                      └─────────────────────────┘
```

---

## 4. Key Implementation Pillars

### A. Voice Calibration (Writing-Style Extraction)

Before drafting commits or PR descriptions, the Coordinator extracts your actual writing style dynamically:

- **Git Commit Harvesting:** Runs `git log -n 15 --oneline` on your active repository to analyze your actual commit patterns (e.g., lowercase style, length, active verbs).
- **Writing Sample Reference:** If a file exists at `~/.hermes-coder/writing_sample.txt`, the Coordinator reads it to map paragraph transitions, punctuation habits, and word choices.
- **The Core Rule:** *Always write down to the user's level of formality. If they use casual contractions, never use sterile, formal academic structures.*

### B. AI-Slop Filtering (Rule-Based Syntax Checks)

Using your imported `humanizer` skill, the Coordinator parses drafts against a strict **Blacklisted Vocabulary** list, stripping out these high-frequency AI-isms:

- *Significance Inflation:* "serves as a testament", "crucial role", "pivotal moment", "evolved landscape".
- *Generic Filler:* "delve", "tapestry", "foster", "cultivate", "ensure", "enrich", "testament".
- *Weak Trailing Clauses:* Any present participle clause (e.g., ending with `, ensuring that...` or `, highlighting...`) is broken into a separate, active sentence.

### C. The Anti-AI Double Pass

Before writing the final text, the Coordinator runs a quick, cheap local model pass (using **`gemma3n:e4b`** or **`gemma4:e4b`** locally) with a specialized dual-prompt:

1. **Pass 1 (Adversarial critique):** *"Analyze the draft below. Identify the top 2 elements that make it sound obviously AI-generated."*
2. **Pass 2 (Re-write):** *"Now, rewrite the draft to eliminate those 2 tells entirely. Vary sentence lengths, use active voice, and keep the tone conversational."*

---

## 5. Design Notes

- **Local caching:** Since humanizing is a quick editing task, the dual-pass filter can run entirely on a local model (when available) to preserve cloud tokens.
