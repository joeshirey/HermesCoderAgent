# Capability: GitHub backlog management

Track the backlog as context-rich **GitHub Issues** rather than local files. The tool
classifies metadata, drafts RFC-style bodies, humanizes the prose, and keeps the backlog
healthy through triage and grooming — all behind the same autonomy gate as delivery.

## Opt-in per repo

A repo participates only if it has a `.hermes-backlog.yaml` with `enabled: true` in its
root. If a repo is not opted in, the tool exits 4 and no issues are filed there.

## What it does

- **init-labels** — sync the label taxonomy.
- **create** — classify metadata (Type/Severity/Effort/Risk/Impact/Confidence), draft the
  RFC §4 body, humanize, and open the issue.
- **enrich** — flesh out an existing issue to the §4 template.
- **triage** (nightly) — sweep untriaged human-filed issues (no `type:*` label or carrying
  `backlog:needs-triage`): classify → research → rewrite to the template → apply labels +
  a `backlog:groomed` comment, bounded by `--limit`. **Only edits/comments — never closes.**
- **groom** (weekly) — keep the backlog healthy via four analysis vectors: dependency
  bottleneck + circular-dependency detection (from the invisible `relations-metadata` DAG),
  lexical + optional LLM dedup, propose-only XL/L decomposition (drafted, never
  auto-created), and a stale/decay audit. Emits one grooming digest.

## Closing nuance

Completed issues are **not** closed by this tool — they close via `Closes #N` on a merged
PR (see [github-delivery](../github-delivery/README.md)). The **only** path that closes
issues here is `groom`, and only for **stale-past-grace** and **confirmed-duplicate**
issues, only behind the gate (`--confirm` or push-draft/full; default `gated` writes
nothing), and never with `--no-close`. Closes use `gh issue close --reason "not planned"` —
never delete, never merge.

## Components

- **Script:** [`scripts/github_backlog.py`](../../scripts/github_backlog.py)
- **Skill:** [`github-backlog`](../../skill-library/coordinator/github-backlog/SKILL.md)
- **Design note:** [`BACKLOG_MANAGEMENT.md`](BACKLOG_MANAGEMENT.md)
- **Config:** the `github_backlog` block in
  [`config.sample.yaml`](../../coordinator-core/config.sample.yaml) (autonomy, triage/groom
  limits, stale thresholds, dedup threshold).

## Guardrails

- Never create/edit issues in a repo that hasn't opted in.
- `create`/`enrich`/`triage` never close or merge — only `groom` closes, and only within the
  narrow stale/dup window behind the gate.
- Push past the autonomy gate only with `--confirm` when gated.
- Cron for nightly triage / weekly grooming is documented, **wired by the user, not
  auto-registered.**
