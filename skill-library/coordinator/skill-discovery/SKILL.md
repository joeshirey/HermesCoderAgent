---
name: skill-discovery
description: Discover task-relevant skills from a curated allowlist of trusted indexes, reputation-gate them, vet through the #6 gateway (audit → vault → sandbox), and inject into the active harness (#11).
version: 1.2.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [discovery, injection, reputation, supply-chain, security, skills, harness, dispatch, vetting]
    related_skills: [security-auditor, vetted-vault, skill-ingest, container-runner, complexity-triage, local-model-router]
---

# Skill Discovery

Closes the loop between the dynamic-tooling security pipeline (#6) and the harness layer (#11). At
dispatch time the coordinator *discovers* the specialized skills a task needs from a **curated
allowlist of trusted indexes**, gates them by **source reputation**, vets them through the EXISTING
gateway (`security-auditor` → `vetted-vault` → `container-runner`), and *injects* the approved skills
into whichever harness is active. A documented weekly refresher re-pulls the indexes and checks
vaulted skills for updates.

This is an orchestrator: it reuses #6 by import and never re-implements audit/vault/sandbox. Nothing
fetched is executed on the host — the auditor is static + LLM only, and any executable scripts a
skill ships are run later, sandboxed, via the `container-runner`. **Scope: SKILL.md skills only.**
MCP-server discovery is a documented follow-on (different injection surface: process-spawn +
allowlist).

## Reputation drives policy

| Trust | Sources | Vault gate | Code sandbox |
|-------|---------|-----------|--------------|
| **trusted** | anthropic, google, firebase, openai, aws, microsoft | auto-vault on a clean audit (no `--confirm`) | no |
| **known** | huggingface, modelcontextprotocol | require human `--confirm` | yes |
| **unknown / community** | everything else (lobehub/browse.sh/clawhub, deferred/opt-in) | require human `--confirm` | yes |

A `FAIL` audit **hard-blocks** regardless of reputation. `vetted_vault.classify()` stays authoritative
for the on-disk registry tier; the reputation map in `scripts/skill_discovery.py` (`SOURCE_REPUTATION`)
drives the confirm-gate and sandbox decision. Discovery is **best-effort** — any fetch/audit/harness
failure falls open to **local-only injection** and never blocks a dispatch.

## Adding a new source

Widening discovery never loosens security — every discovered skill still passes the full gateway
(audit → vault → sandbox). To add a source:

1. **Reputation** — add the org to `SOURCE_REPUTATION` with its trust tier (`trusted`/`known`/
   `untrusted`). Trust decides auto-vault vs. human `--confirm` and whether shipped code is sandboxed.
2. **Allowlist** — add the index key to `allowlist_indexes` in `config.yaml`.
3. **Live source** — map the key → `(repo, scan_subdir)` in `INDEX_SOURCES` so `refresh --confirm`
   clones the repo, walks its `SKILL.md` files (parsing name/description/tags, including YAML folded
   `>-` scalars), and atomically writes the cache. Keys without an `INDEX_SOURCES` entry keep their
   snapshot and are not live-pulled.

Currently wired live: **anthropics/skills**, **google/skills** (firebase-basics, cloud-run-basics,
bigquery-basics, gcloud, GCP WAF skills…), **firebase/agent-skills** (firebase-firestore,
firebase-security-rules-auditor, firebase-auth-basics, firebase-data-connect-basics…),
**microsoft/skills** (Azure SDK skills, entra-agent-id, kql, microsoft-docs…; scattered across
`.github/skills` + `.github/plugins/*/skills`, so the whole repo is walked), and
**aws/agent-toolkit-for-aws** (aws-serverless, aws-iam, aws-cdk, amazon-bedrock, agents-* plugin
skills…; scattered across `skills/*` + `plugins/*/skills`, whole repo walked).

## When to use

After local skill matching, on **every M/L/XL** task. The read-only `discover` step always runs and
its result is always reported in the dispatch's skill ledger (even "no remote candidate matched") —
it is never skipped silently. Vet + inject only proceed when local (Tier 1) matches are thin; local
skills are auto-approved and need no discovery, but the discover run still happens and is reported.

## Dispatch

Discover ranked candidates (read-only, no writes):

```
terminal(command="python3 ~/.hermes-coder/scripts/skill_discovery.py discover --task '<task summary>' --json", workdir="~/.hermes-coder", timeout=30)
```

Vet (fetch → audit → reputation-gated vault → Tier-gated sandbox) the top candidate; `--confirm`
required to vault a known/untrusted source; trusted sources auto-vault:

```
terminal(command="python3 ~/.hermes-coder/scripts/skill_discovery.py vet --task '<t>' [--all] [--confirm] [--dry-run] --json", workdir="~/.hermes-coder", timeout=600)
```

Emit the per-harness injection spec for an approved vaulted skill:

```
terminal(command="python3 ~/.hermes-coder/scripts/skill_discovery.py inject --name '<vaulted>' --engine <active-harness> --json", workdir="~/.hermes-coder", timeout=30)
```

Per-harness injection mechanisms (mirrors SOUL.md): **claude-code** `--append-system-prompt`
(+ `--allowedTools` when a skill declares tools); **antigravity** prompt-prepend; **opencode** `-f`
context file.

Flags: `--task`, `--repo`, `--all` (vet all top-K, default top 1), `--confirm`, `--dry-run`,
`--name` (inject), `--engine` (default `coding.default_engine`), `--json`.

## Reading the output (`--json`)

- **discover** → `{task, count, candidates[]}`; each candidate has `name`, `score`, `trust`, `tier`,
  `sandbox_code`, `repo`, `identifier`, `source_org`, `description`.
- **vet** → `{task, results[]}`; each `VetResult` has `name`, `trust`, `tier`, `verdict`, `vaulted`,
  `vault_path`, `sandboxed`, `sandbox_status`, `status`
  (`approved|blocked|awaiting_confirmation|reused|dry-run|error`), `degraded`, `warning`,
  `command_preview`, `error`.
- **inject** → `{engine, mechanism, args|prompt_prefix|context_file, note}`.
- **refresh** → `{action, dry_run, pulled, degraded, allowlist, planned_indexes[]
  (each: index, repo, status, entries, cached_files), vaulted_update_candidates[], note}`.
  `--confirm` performs the live pull (clone → walk → cache); without it the run is report-only.

## Safety rules

- A `blocked` status (audit `FAIL`) hard-blocks — never vault or inject the source.
- `awaiting_confirmation` (known/untrusted) means a human must review before approval; only
  `--confirm` after the user signs off. Only **trusted** sources auto-vault.
- Execute a vaulted tool only via the `container-runner`, never on the host.

## Scheduling (weekly)

`refresh --confirm` live-pulls every wired source (`INDEX_SOURCES`): shallow-clones the repo, walks
its `SKILL.md` files → normalizes → atomically rewrites the cache. It also checks vaulted skills from
curated origins for upstream drift (gated `vetted_vault update` on change). Network-tolerant: a failed
pull keeps the stale cache and the run reports `degraded` (exit 3). It is **documented, not
auto-registered** (`approvals.cron_mode: deny`) — register manually if desired:

```
# Monday 09:00 local — live-pull curated indexes + vaulted update check
0 9 * * 1  cd ~/.hermes-coder && python3 scripts/skill_discovery.py refresh --confirm --json
```

Dry-run anytime (reports planned pulls + update candidates, mutates nothing):

```
terminal(command="python3 ~/.hermes-coder/scripts/skill_discovery.py refresh --dry-run --json", workdir="~/.hermes-coder", timeout=60)
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | ok / dry-run |
| 1 | held back (awaiting `--confirm`) or audit `FAIL` hard-block |
| 2 | invalid arguments / source not found |
| 3 | LLM harness unavailable during audit, or a network pull failed (degraded) |
