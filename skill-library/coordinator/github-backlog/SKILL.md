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

### Backlog Status State Machine (`backlog:*`)

The state labels are mutually exclusive (applying one automatically removes any prior `backlog:*` label) and dictate the issue's lifecycle:

* **`backlog:needs-triage`**: Fresh human-entered issues that lack classification (no `type:*` or other metadata labels) or precise scope. These are candidates for the nightly triage sweep.
* **`backlog:draft-suggestion`**: Automated agent ideas harvested from code comments (`TODO`/`FIXME`), unoptimized runtime warnings, or out-of-scope feedback during a session. They are parked in an inbox buffer to avoid bloat and **suffer a strict 30-day auto-decay rule** (automatically closed as "not planned" if unreviewed or ungroomed for 30 days).
* **`backlog:groomed`**: Fully triaged, structured, and enriched issues (carrying complete `type:`, `severity:`, `effort:`, `risk:` labels and an RFC-formatted template body). These are active backlog items.
* **`backlog:blocked`**: Groomed issues that cannot be implemented yet because they have unresolved dependencies (defined in their invisible `relations-metadata` JSON blocks).
* **`backlog:ready`**: Fully unblocked groomed issues whose dependencies are completely closed, automatically transitioned and commented on by the closed-loop cascade runner.

*For details on prefix-aware conflict resolution and cleaning up duplicate labels within these namespaces, see [duplicate_labels_resolution.md](references/duplicate_labels_resolution.md).*

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

* Never operate on a repo that has not opted in.
* Never push a mutation past the autonomy gate without `--confirm` when gated.
* `create`/`enrich`/`triage` never close or merge — creation, enrichment, and comments only.
* `groom` never merges and never deletes. It may close **only** stale-past-grace and
  confirmed-duplicate issues, **only** behind the gate (`--confirm`/push-draft/full), never in
  default `gated`, and never when `--no-close` is set. Closes use `--reason "not planned"`.

## Troubleshooting & Pitfalls

### 1. Sequential & Bulk Creation/Triage Timeouts

* **Problem**: Running multiple sequential `create` or `enrich` commands, or a bulk `triage --limit <N>` command (for multiple issues) in a single `terminal()` call can easily trigger tool execution timeouts. Because each issue creation/triage triggers an LLM-backed harness call to research, draft an RFC body, and humanize prose, a single issue's processing can take **100–150 seconds**. A batch of 3+ issues will easily exceed standard terminal timeout limits.
* **Solution**:
  * **Bypassing LLM Passes for Instant Creations (Recommended for Bulk Additions)**: If you are adding several known issues at once, append the `--no-harness` and `--no-humanize` flags to the `create` command. This completely bypasses the heavy LLM research and humanization stages, allowing the backlog tool to classify, create, and label each issue on GitHub almost instantly, completely eliminating timeout risks.
  * **Single Issue per Call (Recommended)**: For bulk additions or triage, invoke the backlog tool once per issue (using `--limit 1` for triage) in independent, discrete `terminal()` commands with a generous timeout (e.g. `timeout=250` or `timeout=300`). This saves progress incrementally after each issue, prevents cascading timeouts, and ensures highly reliable execution.
  * **Automated Incremental Script**: Alternatively, use the included support script `scripts/triage_loop.py` to run an unbuffered, sequential, self-healing background loop that processes all issues incrementally until the backlog is fully triaged and groomed. **Always run this script as an asynchronous background terminal task (`background=true, notify_on_complete=true`) so it runs autonomously without blocking the parent turn or triggering a foreground terminal timeout.** **Pro-tip**: Run this loop using `terminal(background=true, notify_on_complete=true)` so the execution runs completely asynchronously in the background, bypassing any parent turn/command timeouts.
  * **Instant Bulk Creation (Bypass Harness & Humanizer)**: When bulk-logging clearly specified checklists (e.g., from design docs or NEXT_STEPS files) where deep research/humanization is unnecessary, append the `--no-harness` and `--no-humanize` flags. This bypasses the heavy LLM loops entirely, creating the issues on GitHub virtually instantly (while still applying correct namespaced labels and classification metadata) and completely eliminating timeout risk.
  * **Avoid sequential bulk creations or triage in `execute_code`**: These will quickly hit its strict 5-minute execution limit.

### 2. Incremental Python Looping Workaround for Bulk Triage

* **Problem**: When a repository has a large backlog of untriaged issues (e.g., 20+), running them sequentially using standard tools can still be slow and easily interrupted, and doing them in a single batch command is highly susceptible to total timeout failure (since writes only commit at the very end).
* **Solution**: Create and run a lightweight, self-healing Python wrapper (like `triage_loop.py`) that executes `triage --limit 1 --confirm --json` inside an unbuffered loop (using `python3 -u`). This commits each triaged issue incrementally to the remote, logs progress in real-time, and can be started as an asynchronous background task with zero risk of transaction loss if interrupted.

### 3. Selective Humanization of Backlog Descriptions

* **Requirement**: Often, users expect the **Objective & Business Value** of an issue to be written in an accessible, highly articulate, humanized voice for general business stakeholders, while expecting the **Technical Context** and **Implementation Guidelines** to remain in their raw, precise, machine-analyzed state.
* **Solution**: Patch the core backlog script (`draft_issue_body` in `github_backlog.py`) to bypass `_humanize_text` calls on the `technical` sections, reserving humanization solely for the `objective` block.
  * **Avoid sequential bulk creations or triage in `execute_code`**: These will quickly hit its strict 5-minute execution limit.
  * **Avoid sequential bulk creations or triage in `execute_code`**: These will quickly hit its strict 5-minute execution limit.

### 2. Selective Humanization & Detailed Objectives

* **Problem**: Running the prose humanizer across the entire issue body can strip out critical technical specifics (like line numbers, parameter names, or file paths) and make the Technical Context or Implementation Guidelines sections feel overly generic or watered-down.
* **Solution**: Only run the prose humanizer on the **Objective & Business Value** section. This allows the objective to be highly articulate, detailed, and clear for both developers and non-technical stakeholders, while keeping technical context sections in their raw, precise, machine-analyzed state. This behavior is implemented in the backlog tool by bypassing humanization of the technical research block.

### 3. Dynamic Length & Relative Verbosity

* **Problem**: Writing overly verbose descriptions for small, routine tasks creates noise, while writing overly concise descriptions for massive architectural overhauls leaves critical context behind.
* **Solution**: The length and verbosity of the *Objective & Business Value* section must always scale relative to the issue's estimated effort (LOE), complexity, and risk level.
  * **Effort S (Small):** Keep it extremely concise (exactly 2 to 4 sentences in a single short paragraph). Focus strictly on a quick, clear definition of the goal.
  * **Effort M (Medium):** Keep it concise (exactly 1 to 2 short paragraphs).
  * **Effort L (Large):** Write a thorough, 2 to 3 paragraph description. Detail the system motivation, dependencies, and operational impact.
  * **Effort XL (Extra Large):** Write a comprehensive multi-paragraph description (3 to 5 paragraphs), expanding on background context, architectural significance, and long-term value.
  * **High-Risk / Critical Severity:** Append a dedicated focus sentence or paragraph highlighting safety, security, and stability implications.

### 4. Namespace-Wide Label Conflicts

* **Problem**: If the conflict resolver only filters the `backlog:*` namespace, re-triaging or enriching an issue can leave duplicate/conflicting labels from other namespaces (e.g., both `effort:L` and `effort:XL`, or `risk:high` and `risk:low`) on the issue simultaneously.
* **Solution**: Ensure strict mutual exclusivity across *all* namespaced categories (`type:`, `severity:`, `effort:`, `risk:`, `impact:`, `confidence:`, and `backlog:`). For each category, extract the new label's prefix (e.g., `effort:`) and explicitly identify and remove any *other* existing labels sharing that prefix.
  1. **Selective Humanization**: Only run the prose humanizer on the **Objective & Business Value** section. This keeps technical context sections in their raw, precise, machine-analyzed state.
  2. **Relative Verbosity**: Scale the description's paragraph and sentence count directly to the estimated Effort, Risk, and Severity of the task:
     * **S (Small) Effort**: Restrict to exactly **2 to 4 sentences** in a single paragraph. Focus on a quick, clear definition of the goal.
     * **M (Medium) Effort**: Restrict to exactly **1 to 2 short paragraphs** focusing on the immediate objective and direct business value.
     * **L (Large) Effort**: Write a thorough **2 to 3 paragraph** description detailing the system/architectural motivation, the ultimate goal, and operational impact.
     * **XL (Extra Large) Effort**: Write a highly detailed, comprehensive **3 to 5 paragraph** analysis of the background, architectural significance, and long-term value.
     * **High-Risk / Critical Severity**: When a task is high-risk or critical, dedicate a specific sentence or short paragraph strictly to highlighting safety, security, or stability implications.

### 3. Scaled Verbosity Based on Effort & Complexity

* **Problem**: Backlog descriptions can become overly verbose and tedious to read for small, simple tasks (S/M effort), while lacking crucial context and architectural background for complex ones (L/XL effort).
* **Solution**: Dynamically scale the length and depth of the drafted **Objective & Business Value** section based directly on the task's estimated effort, risk, and severity:
  * **Effort S**: 2 to 4 sentences in a single short paragraph, focusing strictly on a quick, clear definition of the goal. No multiple paragraphs.
  * **Effort M**: Exactly 1 to 2 short paragraphs, focusing clearly on the objective and immediate business value.
  * **Effort L**: A thorough 2 to 3 paragraph description, explaining the system motivation, ultimate goal, and operational impact.
  * **Effort XL**: A highly comprehensive multi-paragraph description (3 to 5 paragraphs) detailing background, architectural significance, and long-term value.
  * **High Risk / Critical Severity**: Append a specific paragraph/sentence highlighting the safety, security, and stability implications of the work.
  * **Selective Humanization:** Only run the prose humanizer on the **Objective & Business Value** section. This keeps technical context sections in their raw, precise, machine-analyzed state.
  * **Scaled Objectives (LOE Gated):** Scale the length and detail of the drafted objective based on the estimated **Effort** and **Risk**:
    * **Effort S:** Extremely concise (exactly 2 to 4 sentences in a single short paragraph).
    * **Effort M:** Concise (exactly 1 to 2 paragraphs focusing on immediate value).
    * **Effort L:** Thorough (2 to 3 paragraphs detailing system motivation and operational impact).
    * **Effort XL:** Highly comprehensive (3 to 5 paragraphs covering architectural background and long-term values).
    * **High-Risk/Critical Severity:** Always append a specific safety and stability focus statement.

### 3. Namespaced Label Mutual Exclusivity & Cleanup

* **Problem**: When re-triaging or updating an issue, previous classifications (e.g. `effort:L` vs `effort:XL`) could end up both assigned to the issue simultaneously, creating conflicting metadata.
* **Solution**: The conflict resolver `_conflicting_states` is generalized across all namespaced categories (`type:`, `severity:`, `effort:`, `risk:`, `impact:`, `confidence:`, `backlog:`). Applying a new classification automatically cleanses and removes any older, duplicate labels in those categories.

### 3. Effort-Relative Objective Verbosity

* **Problem**: Generating a uniform, highly verbose objective section for every issue makes simple tasks (effort `S`) feel bloated and noisy, while lacking the deep background required for complex architectural overhauls (effort `XL`).
* **Solution**: Scale the length and detail of the **Objective & Business Value** section proportionally to the task's estimated **Effort (LOE)**, **Risk**, and **Severity**:
  * **Effort S**: Extremely concise (exactly 2 to 4 sentences in a single short paragraph). Quick, clear definition of the goal.
  * **Effort M**: Concise (exactly 1 to 2 short paragraphs) focusing clearly on the objective and immediate business value.
  * **Effort L**: Thorough (exactly 2 to 3 paragraphs) explaining technical motivation, ultimate goal, and business impact.
  * **Effort XL**: Comprehensive (3 to 5 paragraphs) detailing background context, architectural significance, and operational necessity.
  * **High-Risk / Critical Severity**: Always append a specific focus paragraph or sentence highlighting safety, security, and stability implications.
  * Only run the prose humanizer on the **Objective & Business Value** section. This keeps technical context sections in their raw, precise, machine-analyzed state.
  * **Dynamic Verbosity Sizing**: The length and depth of the generated Objective & Business Value description must scale proportionally with the estimated **Effort (LOE)**, **Risk**, and **Severity** of the task to avoid bloating simple tasks:
    * **S-sized Effort**: Exactly 2 to 4 sentences in a single short paragraph. Extremely concise definition of the immediate goal.
    * **M-sized Effort**: Exactly 1 to 2 paragraphs focusing clearly on immediate objective and business value.
    * **L-sized Effort**: 2 to 3 thorough paragraphs explaining the system/technical motivation and operations impact.
    * **XL-sized Effort**: Detailed, multi-paragraph context (3 to 5 paragraphs) elaborating on background, architectural significance, and long-term values.
    * **High-Risk / Critical Severity**: Automatically append or dedicate a focused section/sentences highlighting safety, security, and stability implications.

### 2. GCP SDK & Environment Configuration for Antigravity Engine

* **Problem**: When using `antigravity` (agy) as the backlog research or LLM engine, calls will fail if the Google Cloud SDK path is unconfigured or credentials cannot be resolved.
* **Solution**: Always append `/Users/you/Downloads/google-cloud-sdk/bin` to the command environment's `$PATH` and ensure the active GCP project is set via `GOOGLE_CLOUD_PROJECT` and `CLOUDSDK_CORE_PROJECT` env variables (e.g., `your-gcp-project-id`).

## Repository Research Notes & References

Per-repo backlog research (file paths, schema details, architectural pitfalls discovered during triage) is **project memory** and lives in each repo at `docs/hermes/backlog-research.md`, linked from that repo's `AGENTS.md`. Consult it when triaging or grooming that repo's backlog; write new research findings there, not into this skill.
