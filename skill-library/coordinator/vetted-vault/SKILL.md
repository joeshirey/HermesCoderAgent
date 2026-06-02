---
name: vetted-vault
description: Classify a skill/tool source into a trust tier, hash it (SHA-256), and pin approved sources in an immutable local vault. Safe groundwork for the #6 security gateway — no code execution.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [security, vetting, trust, reputation, sha256, vault, skills, mcp, supply-chain]
    related_skills: [security, architect, reviewer, skill-discovery]
---

# Vetted Vault / Trust Tiers

The registry + immutable vault at the center of the Dynamic Skill & Tool Injection security gateway
(Backlog #6). It classifies a source into a reputation tier, hashes its contents (SHA-256), and
maintains an immutable local registry + vault of approved sources.

**Phase 4 is now operational.** The previously-deferred risky pieces are live as sibling tools:
the [security-auditor](../security-auditor/SKILL.md) (static + LLM audit, never executes code), the
[container-runner](../container-runner/SKILL.md) (sandboxed, network-isolated execution), and
[skill-ingest](../skill-ingest/SKILL.md) (the fetch → audit → vault pipeline). This skill still
owns classify/hash/check/vault/list/status plus the **`update`** diff-audit lifecycle.

Today the gateway is still mostly dormant in practice: `dynamic_curator` only matches **local,
user-authored** skills, which classify as Tier 1 and are auto-approved. The machinery is ready the
moment a third-party skill or MCP server enters the picture.

## Trust tiers

- **Tier 1 — local / official:** path under `~/.hermes-coder/skills` or `~/.hermes-coder/scripts`.
  Auto-approved; audit bypassed (RFC line 119).
- **Tier 2 — trusted org:** `--origin` matches a configured `trusted_orgs` entry (google,
  anthropic, aws, microsoft, modelcontextprotocol, …).
- **Tier 3 — unknown / ad-hoc:** everything else.

## The safety rule

The [security-auditor](../security-auditor/SKILL.md) now gates ingestion (a `FAIL` hard-blocks via
`skill-ingest`), but it is **advisory, not a rubber stamp**: vaulting a Tier 2/3 source still
requires an explicit `--confirm`, and the tool warns that a **human must review the source first**.
A clean audit does not waive human review for untrusted code — do not pass `--confirm` until you (or
the user) have actually read it.

## Store locations (global — shared across repos)

- Registry: `~/.hermes-coder/vetted_tools.json` (keyed by tool name → entry).
- Vault: `~/.hermes-coder/vetted_vault/<name>/` (immutable approved copy; executions should run
  from here, never the remote/downloaded path — that lock-in is what Phase 4 will enforce).

## Dispatch

Classify a source:

```
terminal(command="python3 ~/.hermes-coder/scripts/vetted_vault.py classify --source '<path>' --origin '<org>' --json", workdir="~/.hermes-coder", timeout=30)
```

Check status before injecting a non-local skill/MCP:

```
terminal(command="python3 ~/.hermes-coder/scripts/vetted_vault.py check --source '<path>' --name '<tool>' --origin '<org>' --json", workdir="~/.hermes-coder", timeout=30)
```

Vault + approve (Tier 2/3 needs `--confirm` after manual review):

```
terminal(command="python3 ~/.hermes-coder/scripts/vetted_vault.py vault --source '<path>' --name '<tool>' --origin '<org>' --confirm --json", workdir="~/.hermes-coder", timeout=60)
```

Diff-audit an upstream change and (after review) replace the vault copy:

```
terminal(command="python3 ~/.hermes-coder/scripts/vetted_vault.py update --source '<upstream>' --name '<tool>' --confirm --json", workdir="~/.hermes-coder", timeout=600)
```

`update` re-hashes upstream; if unchanged → `up-to-date`. If changed, it runs the security-auditor
on the new tree and presents a diff card (`local_sha`, `upstream_sha`, `verdict`). A `FAIL` blocks
and leaves the vault copy intact. On `--confirm` + non-FAIL it **atomically** replaces the vault
copy and archives the previous version under `vetted_vault/.archive/<name>/<old_sha>/` for rollback.

Also: `hash`, `status` (check + full registry entry), `list`.

## How matching works

- `check`/`status` derive identity from the source basename (override with `--name`) and compute
  the SHA-256 over the file or directory tree (`.git`/`__pycache__` ignored).
- Approval is recognized first by **checksum** — an approved entry with a matching SHA under any
  name — then by name. A name match with a differing SHA reports `outdated` (re-vet the diff).

## Reading the output (`--json`)

- `classify`: `tier`, `label`.
- `check`/`status`: `status` (`approved|unknown|outdated|pending`), `tier`, `name`, `sha256`,
  `reason`; `status` also attaches the full `entry` when present.
- `vault`: `approved` with the stored `VaultEntry`, or `awaiting_confirmation` with a `warning`
  and `command_preview` (re-run that, adding `--confirm`, only after review).
- `update`: `up-to-date` | `outdated`/`awaiting_confirmation` (diff card + `command_preview`) |
  `updated` (`vaulted_path`, `archived_to`) | `blocked` (upstream audit FAIL, vault unchanged).
- `list`: `count` + `entries[]`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (classified / hashed / approved / vaulted / listed / up-to-date / updated) |
| 1 | Blocked — `unknown` source, unapproved Tier 2/3, outdated awaiting `--confirm`, or audit FAIL |
| 2 | Invalid arguments / source not found / fetch failed |
| 3 | LLM harness unavailable during an `update` audit (static-only verdict still gated) |

## Phase 4 (operational)

The previously-deferred pieces now ship as sibling tools, gated **on** in `config.yaml`
(`auditor_enabled: true`, `container_runner_enabled: true`):

- LLM + static **security auditor** — [security-auditor](../security-auditor/SKILL.md)
  (`security_auditor.py`). Never executes the source; `FAIL` hard-blocks.
- **Container runner** (Docker / Apple Containers) — [container-runner](../container-runner/SKILL.md)
  (`container_runner.py`). Network-isolated, read-only, resource-capped sandboxed execution.
- **Ingestion pipeline** — [skill-ingest](../skill-ingest/SKILL.md) (`skill_ingest.py`): fetch →
  quarantine → classify → audit → vault.
- **Upstream diff-audit lifecycle** — the `update` subcommand above.
