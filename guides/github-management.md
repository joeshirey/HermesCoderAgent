# Guide: GitHub management

How finished, reviewed work reaches GitHub — and how the backlog is tracked there. Two
halves sit behind the **same per-project autonomy gate**:

- **Delivery** — commit, push, PR, CI feedback ([github-delivery capability](../capabilities/github-delivery/README.md)).
- **Backlog** — the backlog as context-rich GitHub Issues ([github-backlog capability](../capabilities/github-backlog/README.md)).

This guide is the connective overview; the per-command behavior, tables, and edge cases live
in those two capability READMEs.

## Authentication

GitHub auth is **not** stored in `.env`. Authenticate the `gh` CLI once with your own
account and the lifecycle/backlog scripts inherit the credentials:

```bash
gh auth login
```

(See the [GitHub CLI docs](https://cli.github.com/manual/) for SSH vs HTTPS, scopes, etc. —
not duplicated here.) Every `git`/`gh` call is list-form `subprocess`, never `shell=True`.

## Per-repo configuration (set during onboarding)

A repo's GitHub behavior is read from two flat-YAML files in its root, written when the repo
is first [onboarded](../skill-library/coordinator/repo-onboarding/SKILL.md):

- `.hermes-github.yaml` — `autonomy`, `default_base`, `skill_discovery`.
- `.hermes-backlog.yaml` — `enabled`, `project_name` (only if you opt the repo in).

If a repo was never onboarded, safe defaults apply (autonomy `gated`, backlog off). See the
[base-system guide](base-system-setup.md#step-6--first-touch-of-a-repo).

## Delivery

The coordinator only delivers work it has already planned and reviewed. Details and the full
autonomy table are in the [github-delivery README](../capabilities/github-delivery/README.md);
the essentials:

- **commit** is always local, and runs a **pre-commit hygiene gate** first — secrets/
  credentials **block** the commit; build junk, a missing `.gitignore`, and hardcoded
  machine paths in staged content **warn**. The commit message is drafted from the diff and
  [humanized](../capabilities/humanizer/README.md) before it lands.
- **push / pr** respect the repo's **autonomy level**
  (`gated` → returns a preview, re-invoke with `--confirm`; `push-draft` → unattended draft
  PRs; `full` → unattended ready PRs). Precedence: `--autonomy` flag > `.hermes-github.yaml`
  > config default > `gated`.
- **ci-status / ci-watch** report Actions status and alert when green + mergeable.

Two hard rules: the tool **never merges** (it alerts; the human merges), and on a `blocked`
commit it never pushes — fix the hygiene issue first.

**Closing issues:** when work resolves a backlog issue, pass `--issue <N>` to `pr` so
`Closes #N` is appended and GitHub closes the issue on merge. Branch-name inference is only a
backstop — thread the known number through explicitly. Script:
[`scripts/github_lifecycle.py`](../scripts/github_lifecycle.py); skill:
[`github-lifecycle`](../skill-library/coordinator/github-lifecycle/SKILL.md).

## Backlog

A repo participates **only** if `.hermes-backlog.yaml` has `enabled: true`; otherwise the
tool exits cleanly and files nothing. The four operations
([github-backlog README](../capabilities/github-backlog/README.md) has the full spec):

- **create** — classify metadata, draft an RFC-style body, humanize, open the issue.
- **enrich** — flesh an existing issue out to the template.
- **triage** (nightly) — sweep untriaged human-filed issues: classify, research, rewrite,
  label. **Only edits/comments — never closes.**
- **groom** (weekly) — dependency/dedup/decomposition/decay analysis, emitting one digest.

**Closing nuance:** completed issues close via `Closes #N` on a merged PR, not by the
backlog tool. The *only* path here that closes is `groom`, and only for stale-past-grace or
confirmed-duplicate issues, only behind the gate, using `gh issue close --reason "not
planned"` — never delete, never merge. Script:
[`scripts/github_backlog.py`](../scripts/github_backlog.py); skill:
[`github-backlog`](../skill-library/coordinator/github-backlog/SKILL.md).

## Scheduling

Nightly triage and weekly grooming are **documented, not auto-registered**. Wire your own
cron/launchd jobs deliberately if you want them — see the scheduling note in
[`deploy/README.md`](../deploy/README.md).

## Guardrails (from [SOUL.md](../coordinator-core/SOUL.md))

- Never auto-merge — alert when CI is green and let the human merge.
- Never push directly to `main`/`master`; never raw `git push` or force-push.
- Respect the autonomy gate; surface the command preview when `gated`.
- `create`/`enrich`/`triage` never close issues — only `groom`, within its narrow window.
- Never create or edit issues in a repo that hasn't opted in.
- Commits authored as the user only — no `Co-Authored-By` trailers.

## Related

- [GitHub delivery](../capabilities/github-delivery/README.md) ·
  [GitHub backlog](../capabilities/github-backlog/README.md) ·
  [Humanizer](../capabilities/humanizer/README.md)
- [Base system setup](base-system-setup.md) ·
  [Skill discovery, vetting, caching & execution](skill-discovery-and-vetting.md)
