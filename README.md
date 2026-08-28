# hermes-coder-reference

A **modular reference** for `hermes-coder` — an always-on AI coding *coordinator* that
plans, decomposes, delegates, and reviews software work but **never writes code itself**.
It dispatches self-contained prompts to a swappable coding *harness* (Claude Code,
Antigravity, or OpenCode) and wraps every dispatch in guardrails: complexity triage,
prior-lesson injection, a security-vetting pipeline for any third-party skill, an
auto-healing fix loop, a humanizer pass for all outward-facing prose, and a gated
GitHub delivery + backlog lifecycle.

> **This is a snapshot, not the live system.** It is a periodically refreshed, sanitized
> copy of a private working setup — published so others can adopt the *ideas and
> components* piece by piece. It is **not** the source of truth. See
> [SNAPSHOT.md](SNAPSHOT.md) for what that means and how the snapshot is produced.

> **Want to install it?** Clone this repo and open it in your coding agent (Claude Code,
> Antigravity, or OpenCode), then tell the agent:
> *"Read INSTALL.md and walk me through installing hermes-coder."*
> [`INSTALL.md`](INSTALL.md) is an agent-driven, interactive installer: the agent detects
> what's already on your machine, asks which harnesses and optional modules you want, and
> sets up your chosen home directory (it suggests `~/.hermes` for a coder-only box, or
> `~/.hermes-coder` alongside a general-purpose agent) for you (macOS/Linux).

## The core idea

A senior-engineer **coordinator** (its contract lives in
[`coordinator-core/SOUL.md`](coordinator-core/SOUL.md)) sits above a **coding engine**.
The coordinator owns judgment — planning, sizing, reviewing, shipping — and treats the
engine as a stateless executor it drives through one-shot CLI calls. Because the engine is
behind a thin harness abstraction, you can swap `claude -p` for `agy -p` or `opencode run`
without touching the coordinator logic.

Everything else in this repo is a **capability** that bolts onto that loop. Each is
independently useful; adopt the ones you want.

## Adopt by capability

Each capability is a documentation hub that points at the scripts (in
[`scripts/`](scripts/)), skills (in [`skill-library/`](skill-library/)), and design notes
that implement it.

| Capability | What it gives you | Start here |
|------------|-------------------|------------|
| Multi-harness dispatch | Swap the coding engine (claude-code / antigravity / opencode) behind one interface | [capabilities/multi-harness](capabilities/multi-harness/README.md) |
| Security pipeline | Ingest → audit → vault → sandbox for any third-party skill/tool; trust tiers | [capabilities/security-pipeline](capabilities/security-pipeline/README.md) |
| Dynamic tooling | Discover task-relevant skills from trusted indexes and inject them, reputation-gated | [capabilities/dynamic-tooling](capabilities/dynamic-tooling/README.md) |
| Quality loop | Complexity triage, auto-healer, systematic debugger, retrospective lessons, parallel dispatch | [capabilities/quality-loop](capabilities/quality-loop/README.md) |
| GitHub delivery | Gated commit/push/PR with a pre-commit hygiene gate and auto issue-close | [capabilities/github-delivery](capabilities/github-delivery/README.md) |
| GitHub backlog | Manage the backlog as context-rich GitHub Issues (triage, grooming, dedup) | [capabilities/github-backlog](capabilities/github-backlog/README.md) |
| Humanizer | Strip "AI slop" from commits/PRs/docs before they go out | [capabilities/humanizer](capabilities/humanizer/README.md) |
| Local models | Optional local-model routing (currently a documented "off by default") | [capabilities/local-models](capabilities/local-models/README.md) |

## Layout

```
coordinator-core/   The coordinator contract (SOUL.md), a slim sample config, .env.example
scripts/            Flat, importable Python engine (stdlib-only, ZERO pip) + its tests
capabilities/       One README per capability — the conceptual hubs that tie it together
skill-library/      Curated SKILL.md files (coordinator + coding-team roles + harnesses + dev skills)
guides/             Longer-form setup/architecture write-ups
deploy/             Genericized macOS always-on launchagent template
```

## Design constraints worth knowing

- **Stdlib-only Python, zero pip.** Every script in `scripts/` runs on a bare Python 3
  install. Config is parsed without PyYAML. Keep it that way if you extend it.
- **Harness-neutral core.** The coordinator and capabilities avoid baking in a specific
  engine; harness specifics are isolated under [`skill-library/harness`](skill-library/harness/)
  and [capabilities/multi-harness](capabilities/multi-harness/README.md).
- **Safety is structural, not advisory.** Third-party code is never injected or run
  directly — it goes through ingest → audit → vault → sandbox. The coordinator never
  auto-merges PRs and never closes issues except via the narrow grooming path.

## Getting your bearings

1. Read [`coordinator-core/SOUL.md`](coordinator-core/SOUL.md) — the whole behavior model.
2. Skim [`scripts/README.md`](scripts/README.md) — what each engine script does.
3. Pick a capability from the table above and read its README.

## Guides

End-to-end walkthroughs that tie the pieces together (they link to the files above rather
than duplicating them):

- [Setting up the base system](guides/base-system-setup.md) — the coordinator + harness
  concept; using one or more coding engines.
- [Skill discovery, vetting, caching & execution](guides/skill-discovery-and-vetting.md) —
  how third-party skills are discovered, audited, vaulted, sandboxed, and injected.
- [GitHub management](guides/github-management.md) — gated delivery and the GitHub-Issues
  backlog.

## Acknowledgements

This project builds on ideas and code from several open-source projects (all MIT-licensed):

- **[obra/superpowers](https://github.com/obra/superpowers)** — The systematic debugging
  methodology and workflow skills (TDD, code review, plan-writing) are adapted from this
  agentic skills framework. The `skill-library/software-development/` and
  `skill-library/workflow/` directories contain derivative works.
- **[bradygaster/squad](https://github.com/bradygaster/squad)** — The multi-agent
  coordination model and role-based skill decomposition (architect, implementer, reviewer,
  quality, security, devops, docs) were informed by Squad's agent-team patterns.
- **[blader/humanizer](https://github.com/blader/humanizer)** — The humanizer gateway
  and AI-slop filtering pipeline were informed by this Claude Code skill for stripping
  AI-generated writing tells. The `capabilities/humanizer/` design and
  `scripts/humanizer_gateway.py` are derivative works.

## License

MIT — see [LICENSE](LICENSE).
