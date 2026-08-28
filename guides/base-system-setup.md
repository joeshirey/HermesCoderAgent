# Guide: Setting up the base system

How to stand up the `hermes-coder` **coordinator** and wire it to one (or several) coding
**harnesses**. This guide is the connective tissue — it links to the authoritative files
and vendor docs rather than repeating them, so it can't drift out of sync with the things
it describes.

> **Snapshot, not an installer.** This repo is a sanitized reference, not a clone-and-run
> distribution (see [SNAPSHOT.md](../SNAPSHOT.md)). "Set up" here means *adopt these pieces
> into your own hermes home dir* — substitute your paths, bring your own keys.

## The shape of the system

A senior-engineer **coordinator** sits above a **coding engine**:

- The **coordinator** owns judgment — planning, sizing, reviewing, shipping. Its entire
  behavioral contract is [`coordinator-core/SOUL.md`](../coordinator-core/SOUL.md). It
  **never writes code itself.**
- The **harness** is the coding engine (Claude Code, Antigravity, OpenCode, …). The
  coordinator drives it through one-shot, non-interactive CLI calls and treats it as a
  stateless executor.

Because the engine lives behind a thin adapter, swapping `claude -p` for `agy -p` or
`opencode run` is a config flag, not a rewrite. The full rationale and mechanism are in the
[multi-harness capability](../capabilities/multi-harness/README.md); the per-engine command
templates live in [`skill-library/harness/`](../skill-library/harness/).

## Prerequisites

- A Mac or Linux machine that can stay on (for always-on use).
- An API key for your **coordinator** model (Gemini, Anthropic, or any OpenAI-compatible
  provider). This is the model that *plans and reviews* — separate from whatever model the
  harness uses to write code.
- At least one **harness CLI** installed and authenticated (see below).
- Optional: a messaging transport (e.g. Telegram) if you want to reach the agent remotely.

## Step 1 — Install the coordinator host

The coordinator runs inside the [Nous Research Hermes Agent](https://hermes-agent.nousresearch.com/)
runtime. Follow its install instructions, then point a **separate hermes home dir** at the
coordinator so it doesn't collide with any other agent you run:

```bash
export HERMES_HOME=~/.hermes-coder
```

## Step 2 — Install one or more harness CLIs

Install whichever engines you want to start with. You can add more later — the coordinator
doesn't care which one is active. **Authentication and provider setup live in each vendor's
own docs and in that engine's harness skill — this guide does not duplicate them:**

| Engine | Install & auth (vendor docs) | Dispatch templates (this repo) |
|--------|------------------------------|--------------------------------|
| Claude Code (default) | [docs.anthropic.com/claude-code](https://docs.anthropic.com/en/docs/claude-code) | [`skill-library/harness/claude-code`](../skill-library/harness/claude-code/SKILL.md) |
| Antigravity (`agy`) | [Gemini Code Assist](https://cloud.google.com/products/gemini/code-assist) | [`skill-library/harness/antigravity`](../skill-library/harness/antigravity/SKILL.md) |
| OpenCode | [github.com/opencode-ai/opencode](https://github.com/opencode-ai/opencode) | [`skill-library/harness/opencode`](../skill-library/harness/opencode/SKILL.md) |

Each harness skill carries the exact one-shot syntax, the per-task dispatch templates, a
flags table, and that engine's quirks (e.g. the `agy` GCP project-ID troubleshooting lives
in the antigravity skill, not here).

Two things every harness needs to dispatch unattended:

- It must run in **one-shot / non-interactive** mode without prompting for tool approval.
- Commits must carry **no `Co-Authored-By` trailers** (e.g. Claude Code:
  `includeCoAuthoredBy: false`).

Smoke-test whichever you installed, e.g. `claude -p 'say hello'`, `agy -p 'say hello'`, or
`opencode run 'say hello'`.

## Step 3 — Wire the coordinator

Three surfaces, all documented in
[`coordinator-core/README.md`](../coordinator-core/README.md):

- [`SOUL.md`](../coordinator-core/SOUL.md) — load as the coordinator's system prompt.
- [`config.sample.yaml`](../coordinator-core/config.sample.yaml) — copy the coordinator
  blocks into your config; set `coding.default_engine` to the harness you installed.
- [`.env.example`](../coordinator-core/.env.example) — copy to `.env`, fill in your
  coordinator-model key. (GitHub auth is **not** here — use `gh auth login`; see the
  [GitHub management guide](github-management.md).)

> Using Anthropic instead of Gemini as the *coordinator* model? Swap the provider/model in
> the config and set the matching key in `.env`. This is independent of which harness writes
> the code.

## Step 4 — Use one or more harnesses

The engine set at `coding.default_engine` is used unless you say otherwise. Switching is a
plain-English instruction mid-session — no restart, no file edit:

> "Use antigravity for this session" · "Use opencode for this task" · "Switch back to claude"

The coordinator loads the matching harness skill and applies its dispatch templates;
everything else (planning, two-stage review, TDD, escalation) is unchanged. The
per-engine capability comparison (tool allowlists, turn limits, timeouts, model override)
is maintained once, in the
[multi-harness capability README](../capabilities/multi-harness/README.md#how-routing-works) —
consult it there rather than memorizing it.

Note that LLM-backed *support passes* (triage, humanizer, retrospective, audits, backlog
grooming) route through the same active engine via
[`scripts/harness_llm.py`](../scripts/harness_llm.py), so picking a default engine
configures the whole system, not just code dispatch.

## Step 5 — Run it always-on (optional)

To keep the coordinator listening continuously, install the macOS LaunchAgent. The template
and step-by-step are in [`deploy/README.md`](../deploy/README.md) — it uses placeholders
(`{{HERMES_HOME}}`, `{{USER}}`, …) so nothing machine-specific is baked in. If you only
invoke the scripts directly, you don't need a long-running service at all.

## Step 6 — First touch of a repo

The first time the coordinator works in a new repo it **onboards** it: a short interview
that records the repo's autonomy, backlog opt-in, and external-skill-discovery policy, then
persists the answers so later commands honor them without re-asking. You can skip the
interview to accept safe defaults (gated, no backlog, local-only). The procedure is the
[`repo-onboarding` skill](../skill-library/coordinator/repo-onboarding/SKILL.md), backed by
[`scripts/repo_onboarding.py`](../scripts/repo_onboarding.py). These settings feed both the
[skill-discovery](skill-discovery-and-vetting.md) and [GitHub-management](github-management.md)
guides.

## Verify

```bash
# Coordinator never has a hardcoded engine outside the harness skills:
grep -rn "claude -p" coordinator-core/ skill-library/coding-team/ skill-library/workflow/
#   → nothing; the only matches live under skill-library/harness/claude-code/

# Harness skills present:
ls skill-library/harness/*/SKILL.md     # claude-code, antigravity, opencode
```

Then drive a trivial task end-to-end ("create a hello-world script and a test for it in
/tmp/…") and watch the coordinator plan → dispatch the active harness → review in two passes
→ report.

## Why the engine is pluggable

The coordinator's value is the *process* — decomposition, review, escalation — not which CLI
it calls. Different engines have different strengths (Claude Code's fine-grained tool/turn
control, Antigravity's built-in timeouts and sandbox, OpenCode's per-task model selection),
and new ones keep arriving. Keeping engine specifics isolated to a single skill file per
engine means adopting a new one is *one file*, not a rewrite — and you can A/B the same task
across engines by switching mid-session.

## Next

- [Skill discovery, vetting, caching & execution](skill-discovery-and-vetting.md)
- [GitHub management](github-management.md)

## Credits

- [Nous Research Hermes Agent](https://hermes-agent.nousresearch.com/) — the agent runtime.
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
  [Antigravity CLI](https://cloud.google.com/products/gemini/code-assist),
  [OpenCode](https://github.com/opencode-ai/opencode) — the coding engines.
- [Superpowers](https://github.com/obra/superpowers) — development-methodology skills that
  informed the workflow skills (systematic debugging, TDD, code review).
- [Squad](https://github.com/bradygaster/squad) — AI agent-team scaffolding that informed the
  role skills and multi-agent coordination patterns.
- [Humanizer](https://github.com/blader/humanizer) — AI-slop detection skill that informed
  the humanizer gateway and prose calibration pipeline.
- [hermes-webui](https://github.com/nesquena/hermes-webui) — a web interface for Hermes.
