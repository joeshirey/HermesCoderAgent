---
name: github-backlog
description: Make GitHub Issues the canonical backlog. Initialize the namespaced label schema, classify metadata, create/enrich/triage context-rich issues, and run the weekly grooming sweep. Opt-in per repo; autonomy-gated; never merges; groom may close stale/duplicate issues only behind the gate.
version: 1.2.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [github, backlog, issues, labels, triage, metadata, autonomy, humanizer]
    related_skills: [github-lifecycle, architect, reviewer, docs]
---

# GitHub Backlog (Phases 1–3 — Creation, Enrichment, Nightly Triage & Weekly Grooming)

Turns raw task ideas into **context-rich GitHub Issues** with standardized metadata labels, so a
later agent or human can pick one up and execute with zero extra research. This is Backlog #7.
Phase 1 (`create`/`enrich`), Phase 2 (`triage`, the nightly engine), and Phase 3 (`groom`, the
weekly grooming sweep) are all operational.

This skill **never merges**. `create`/`enrich`/`triage` only create, enrich, or comment — they
never close. `groom` is the **one** narrowly-scoped exception: it may close stale-past-grace and
confirmed-duplicate issues, but **only** behind the autonomy gate (`--confirm`, or push-draft/full
autonomy), never in default `gated` mode, and `--no-close` suppresses every close. Closes use
`gh issue close --reason "not planned"` — never delete.

## When to capture (intake gate)

Capture net-new work **before** planning or implementing it — not after. When the user asks for
a feature, an enhancement, or a non-trivial bug fix in a backlog-enabled repo, run `create` (below)
*first*, report the new issue number, and ask whether to implement now; only then move on to
planning/execution, threading `--issue <N>` through to the PR so it closes on merge. Don't start
building an uncaptured enhancement. Trivial one-liner tweaks (a typo, a tiny fix) are exempt. If the
repo isn't opted in, offer to opt it in rather than silently skipping capture. (This mirrors the
coordinator's "Capture before building" principle and the Triage intake step in SOUL.md.)

## Opt-in (required)

A repo must opt in: a `.hermes-backlog.yaml` with `enabled: true` in its root. If absent, every
subcommand exits 4 (`not_opted_in`) and nothing happens. Minimal file:

```yaml
enabled: true
project_name: "My Project"
autonomy: gated        # optional: gated | push-draft | full
```

## Label schema (RFC §2)

Seven namespaced categories, created idempotently by `init-labels`:
`type:*` (feature/bug/refactor/chore/spike), `severity:*` (critical/high/medium/low/nit),
`effort:*` (S/M/L/XL), `risk:*` (high/medium/low), `impact:*`
(user-visible/internal-debt/dev-experience), `confidence:*` (high/medium/low), and `backlog:*`
(needs-triage/draft-suggestion/groomed/blocked/ready) for the state machine.

## Autonomy gating

Mutating subcommands (`init-labels`, `create`, `enrich`) respect a per-project autonomy level,
mirroring `github-lifecycle`. Precedence: `--autonomy` flag > `.hermes-backlog.yaml` autonomy >
config.yaml `github_backlog` block > hard default `gated`. In `gated`, a mutation returns
`awaiting_confirmation` with a `command_preview` — surface it to the user and only re-run with
`--confirm` after they approve. `--dry-run` always previews and never touches the remote.

## Dispatch

Initialize labels:

```
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py init-labels --repo '<repo>' --confirm --json", workdir="~/.hermes-coder", timeout=120)
```

Create a context-rich issue (classify → draft §4 body → humanize → gated create):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py create --repo '<repo>' --title '<title>' --task '<raw idea>' --engine <harness> --confirm --json", workdir="~/.hermes-coder", timeout=600)
```

Enrich an existing thin issue (preserves the human objective):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py enrich --repo '<repo>' --issue <n> --engine <harness> --confirm --json", workdir="~/.hermes-coder", timeout=600)
```

Nightly triage — sweep & batch-enrich untriaged issues (classify → research → rewrite → gated apply):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py triage --repo '<repo>' --engine <harness> --limit 20 --confirm --json", workdir="~/.hermes-coder", timeout=1200)
```

**Candidate rule:** an open issue is untriaged when it lacks any `type:*` label **OR** carries
`backlog:needs-triage`. Already-groomed issues (have a `type:*` label, not needs-triage) are skipped.
The read-only harness research pass runs on **every** candidate; `--limit` caps the batch so a
nightly run stays bounded. `--no-harness` is a fast testing override. On apply, each issue gets the
rewritten §4 body, the metadata labels, `backlog:groomed`, and a short explanatory comment. The
backlog state labels (`needs-triage`/`draft-suggestion`/`groomed`/`blocked`/`ready`) are mutually
exclusive: applying a new state clears any prior one (e.g. triage adds `backlog:groomed` and removes
`backlog:needs-triage`), so an issue never carries two states at once. Triage never closes or merges.

Weekly grooming — four analysis vectors over open issues → one digest → gated apply:

```
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py groom --repo '<repo>' --engine <harness> --confirm --json", workdir="~/.hermes-coder", timeout=1200)
```

**The four vectors** (`--skip-bottlenecks/--skip-dedup/--skip-decompose/--skip-stale` toggle each):

1. **Dependency bottleneck/cycle detection** — rebuilds the dependency DAG from the invisible
   `relations-metadata` blocks; an issue blocking ≥ `--bottleneck-min` (3) others is flagged for
   `severity:high` elevation; circular dependencies are reported flag-only (no command).
2. **Semantic deduplication** — `difflib` lexical similarity over title+objective finds pairs ≥
   `--dup-threshold` (0.85); an optional harness-LLM pass confirms each (skip with `--no-llm-dup`).
   A pair is *closable* when LLM-confirmed (or lexical-only ≥ 0.95); it proposes closing the newer
   as a duplicate of the older.
3. **Automated decomposition** — for `effort:L`/`effort:XL` issues, drafts 2–4 proposed sub-issues
   **into the digest only**. Propose-only: nothing is ever auto-created.
4. **Stale/decay audit** — issues idle ≥ `--stale-days` (60) get `backlog:stale` + a warm-stale
   warning comment; issues already `backlog:stale` and idle ≥ `--grace-days` (14) more are proposed
   for **close** (`--reason "not planned"`).

**Close carve-out:** `groom` is the only subcommand that may close issues — stale-past-grace and
confirmed-duplicate only, and only behind the gate (`--confirm`/push-draft/full). Default `gated`
emits a digest and writes nothing. `--no-close` suppresses every close even when the gate is open;
bottleneck elevations and stale *warnings* still apply. Never deletes, never merges.

Read-only helpers (no gating):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py list --repo '<repo>' --json", workdir="~/.hermes-coder", timeout=60)
terminal(command="python3 ~/.hermes-coder/scripts/github_backlog.py status --repo '<repo>' --issue <n> --json", workdir="~/.hermes-coder", timeout=60)
```

Flags: `--autonomy`, `--confirm`, `--dry-run`, `--engine` (coding harness for research drafting +
LLM passes; default `coding.default_engine`), `--model` (deprecated/ignored — LLM passes route
through the harness), `--no-harness` (skip the read-only research pass), `--no-humanize`,
plus `--title`/`--task`/`--body` (create), `--issue` (enrich/status), `--limit` (triage default
`triage_limit`/20; groom default `groom_limit`/200), and groom-only `--stale-days` (60),
`--grace-days` (14), `--dup-threshold` (0.85), `--bottleneck-min` (3), `--no-close`, `--no-llm-dup`,
and the four `--skip-*` vector toggles.

## Reading the output (`--json`)

`BacklogResult` (create/enrich/init-labels/list/status): `status` (`created|enriched|labels-synced|
awaiting_confirmation|dry-run|not_opted_in|ok|error`), `action`, `issue_number`, `issue_url`,
`labels[]`, `metadata{}`, `command_preview[]`, `details`, `error`. Gate on the `status` field —
`awaiting_confirmation` means do not proceed without `--confirm`.

`TriageReport` (triage): `status` (`ok|dry-run|awaiting_confirmation|error`), `action="triage"`,
`processed`, `groomed`, `awaiting`, `skipped`, `items[]`, `details`, `error`. Each `items[]` entry
has `number`, `title`, `proposed_labels[]`, `metadata{}`, `command_preview[]` (the `gh issue
edit`/`comment` it would run), and on apply a `result` (`groomed|error`). `awaiting_confirmation`
means it held everything back — re-run with `--confirm` to apply.

`GroomingReport` (groom): `status` (`ok|dry-run|awaiting_confirmation|error`), `action="groom"`,
`bottlenecks[]`, `cycles[]`, `duplicates[]`, `decompositions[]`, `stale[]`, `applied[]`, `details`,
`error`. `bottlenecks[]` items carry `number/blocks_count/blocked_numbers/current_severity/
proposed_label/command_preview`; `duplicates[]` carry `older/newer/similarity/llm_confirmed/closable/
command_preview`; `decompositions[]` carry `number/effort/proposed_subissues[]` (propose-only);
`stale[]` carry `number/idle_days/action` (`warn|close`)`/command_preview`; `applied[]` (on apply)
carry `number/action/result/error`. `awaiting_confirmation` means actionable changes were held back —
re-run with `--confirm`. Exit 3 = degraded (LLM harness down; lexical/heuristic-only digest still emitted).

## Scheduling (nightly)

Cron is **documented, not auto-registered** — the platform may set `approvals.cron_mode: deny`, and
scheduling is environment-specific, so the user wires it. A typical nightly sweep (system cron):

```
# 02:13 nightly — bounded, gated; emits a digest the user reviews before --confirm
13 2 * * *  cd ~/.hermes-coder && python3 scripts/github_backlog.py triage --repo '<repo>' --limit 20 --json >> ~/.hermes-coder/logs/triage.log 2>&1
```

On macOS prefer `launchd`; in a Hermes session a cron block can be used if `approvals.cron_mode` is
toggled off `deny`. In `gated` mode the scheduled run only produces a digest (no writes) — apply
happens on a follow-up `--confirm`. Set `autonomy: push-draft`/`full` (or pass `--confirm` in the
job) for a fully autonomous nightly groom.

## Scheduling (weekly)

The grooming sweep is weekly, also documented-not-auto-registered (same `approvals.cron_mode: deny`
caveat). A typical Monday-morning sweep (system cron):

```
# Mondays 09:07 — weekly groom, bounded + gated; digest only until --confirm
7 9 * * 1  cd ~/.hermes-coder && python3 scripts/github_backlog.py groom --repo '<repo>' --json >> ~/.hermes-coder/logs/groom.log 2>&1
```

In default `gated` the job emits a digest and **writes nothing** — the user reviews bottleneck
elevations, dedup/stale closes, and decomposition proposals, then re-runs with `--confirm`. For an
autonomous weekly groom set `autonomy: push-draft`/`full` (or add `--confirm` to the job); add
`--no-close` if you want elevations/warnings applied but every close held for human review.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success / dry-run |
| 1 | Blocked — gated mutation without `--confirm` (awaiting confirmation) |
| 2 | Invalid arguments / gh or git preflight failure |
| 3 | LLM harness down — degraded (heuristic metadata + template body; issue still usable) |
| 4 | Repo not opted in (`.hermes-backlog.yaml` missing or `enabled` != true) |

## Graceful degradation

Metadata classification reuses `dynamic_curator.triage` for Effort + Confidence; if the LLM harness
is down it falls back to heuristic facets and a template body, exits 3, and the issue is still
well-formed. The harness research pass and the humanizer pass are both optional — on failure the tool
keeps the template prose. Grooming's dedup-confirm and decomposition passes are also optional: on
harness-down the sweep degrades to lexical-only dedup (and skips decomposition), exits 3, and still
emits a full digest. Issue bodies and comments never carry a `Co-Authored-By` trailer.

## Safety rules

- Never operate on a repo that has not opted in.
- Never push a mutation past the autonomy gate without `--confirm` when gated.
- `create`/`enrich`/`triage` never close or merge — creation, enrichment, and comments only.
- `groom` never merges and never deletes. It may close **only** stale-past-grace and
  confirmed-duplicate issues, **only** behind the gate (`--confirm`/push-draft/full), never in
  default `gated`, and never when `--no-close` is set. Closes use `--reason "not planned"`.

## Troubleshooting & Pitfalls

### Batch Creation Execution Timeout (300s limit)

- **Problem**: Running multiple sequential `create` or `enrich` commands in a single python script (e.g., via `execute_code`) or in a single tool invocation can easily exceed the 300-second tool execution limit. This happens because each issue creation triggers an LLM research pass, structured RFC drafting, and humanizer filtering through the active harness.
- **Solution**:
  1. Break large backlog creations into smaller batches of 2-3 issues per tool invocation.
  2. Alternatively, invoke the creations independently to allow intermediate saving of progress and prevent cascading timeouts.

## Troubleshooting & Pitfalls

### 1. Bulk Creation Timeouts in `execute_code`

- **Problem**: Running multiple `github_backlog.py create` commands sequentially inside an `execute_code` tool call can easily hit its strict **5-minute timeout**. Because each issue creation triggers an LLM-backed harness call to classify, draft an RFC body, and humanize the prose, each command can take 40–70 seconds.
- **Solution**:
  - Batch bulk creations into smaller blocks of 2–3 issues per `execute_code` run.
  - Alternatively, use a foreground `terminal()` call with a higher timeout (up to 600 seconds) to execute the sequence of commands.

### 2. GCP SDK & Environment Configuration for Antigravity Engine

- **Problem**: When using `antigravity` (agy) as the backlog research or LLM engine, calls will fail if the Google Cloud SDK path is unconfigured or credentials cannot be resolved.
- **Solution**: Always append `/Users/you/Downloads/google-cloud-sdk/bin` to the command environment's `$PATH` and ensure the active GCP project is set via `GOOGLE_CLOUD_PROJECT` and `CLOUDSDK_CORE_PROJECT` env variables (e.g., `your-gcp-project-id`).
