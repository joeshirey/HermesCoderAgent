---
name: skill-ingest
description: End-to-end ingestion of a third-party skill/MCP source — fetch → quarantine → classify → audit → vault. A FAIL audit hard-blocks; Tier 2/3 needs --confirm (#6, Phase 4).
version: 1.1.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [ingestion, supply-chain, security, vetting, quarantine, audit, vault, skills, mcp]
    related_skills: [security, reviewer, security-auditor, vetted-vault, container-runner, skill-discovery]
---

# Skill Ingest

The "door" that makes the security guards load-bearing — the **only** sanctioned way a third-party
skill or MCP server enters the vault (Backlog #6, Phase 4). The pipeline:

```
fetch -> quarantine -> classify tier -> security audit
    FAIL      -> hard block (nothing vaulted)
    PASS/WARN -> vault (immutable lock-in copy)   [Tier 2/3 require --confirm]
```

Nothing fetched is ever executed during ingestion — the auditor is static + LLM only, and execution
happens later through the `container-runner` (sandboxed). The quarantine copy is always cleaned up;
the vault holds the kept copy.

## When to use

Only when a **non-local** skill/MCP source is being considered for injection. Local (Tier 1) skills
matched by the curator are auto-approved and bypass this path.

## Dispatch

```
terminal(command="python3 ~/.hermes-coder/scripts/skill_ingest.py ingest --source '<path-or-git-url>' --name '<tool>' --origin '<org>' --json", workdir="~/.hermes-coder", timeout=600)
```

After a human reviews a Tier 2/3 source (status `awaiting_confirmation`), re-run with `--confirm`.
Flags: `--source` (local path or git/http(s) URL), `--name` (required), `--origin`, `--confirm`,
`--static-only`, `--engine` (coding harness for the LLM audit pass; default `coding.default_engine`),
`--model` (deprecated/ignored — the audit uses the coding harness), `--json`.

## Reading the output (`--json`)

`IngestReport`: `name`, `source`, `tier`, `verdict`, `vaulted`, `vault_path`, `status`
(`approved|blocked|awaiting_confirmation|error`), `findings_summary` (static/llm FAIL/WARN counts +
`top_static`), `warning`, `command_preview`, `error`.

## Safety rules

- A `blocked` status (audit `FAIL`) hard-blocks — do not vault or inject the source.
- `awaiting_confirmation` (Tier 2/3) means a human must read the quarantined source before approval;
  only `--confirm` after the user signs off (there is no auto-approval of untrusted code).
- Execute a vaulted tool only via the `container-runner`, never on the host.
- **Provenance required — no fabricated skills.** A bare local-path `--source` is accepted only when
  it lives under a first-party root (`~/.hermes-coder/skills` or `scripts/`). Any other local path is
  rejected (exit 2): a skill must arrive via a real remote URL (verifiable provenance) or through
  `skill-discovery`, which clones from a verified remote before ingesting. This stops a hand-authored
  `SKILL.md` dropped in `/tmp` from being vaulted as if it were trusted. (Discovery sets an internal
  `trusted_local` flag for its temp clone; the CLI never exposes it.)

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Vaulted / approved |
| 1 | Blocked — audit FAIL, or Tier 2/3 awaiting `--confirm` |
| 2 | Invalid arguments / fetch failed |
| 3 | LLM harness unavailable during audit (static-only audit still gated the decision) |
