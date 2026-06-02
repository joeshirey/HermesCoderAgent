---
name: repo-onboarding
description: On first touch of an unconfigured repo, interview the user about its permissions — backlog-as-GitHub-Issues, remote autonomy for PRs/pushes, and external skill discovery — then persist the answers to the repo's two config files so every later command honors them without re-asking. Allow skip (safe defaults: gated / no backlog / local-only).
version: 1.0.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [onboarding, permissions, autonomy, backlog, skill-discovery, per-repo, config]
    related_skills: [github-lifecycle, github-backlog, skill-discovery]
---

# Repo Onboarding (first-touch permission interview)

The **first** time the coordinator works in a repo, establish its rules before doing any work.
Don't infer permissions silently — ask the user, persist the answers, then proceed. This closes the
gap where an agent pushes to `main` or starts building before anyone set the repo's boundaries.

A repo is **onboarded** once `.hermes-github.yaml` exists. Settings are stored across the two
existing per-repo files (no new file):

```
.hermes-github.yaml   autonomy, default_base, skill_discovery
.hermes-backlog.yaml  enabled, project_name
```

## When this runs

At the **start** of work in a repo, before Triage. Check state first:

```bash
python3 ~/.hermes-coder/scripts/repo_onboarding.py status --repo . --json
```

- `onboarded: true` → silently honor the stored settings; skip the interview.
- `onboarded: false` → run the interview below. The user may **skip** it.

## The interview (three questions)

Ask all three, in plain language. Map each answer to an `init` flag.

1. **Backlog as GitHub Issues?** Should I manage this repo's backlog as GitHub Issues
   (create/enrich/triage context-rich issues)? If yes, ask for a project name.
   → `--backlog true --backlog-project "<name>"` (or `--backlog false`).
2. **Remote autonomy for PRs/pushes?** How permissive should I be with the remote?
   - `gated` (default) — I draft pushes/PRs but wait for your `--confirm` each time.
   - `push-draft` — I may push branches and open **draft** PRs on my own; never ready-for-review.
   - `full` — I may push and open ready PRs autonomously. I **never** merge, and never push to
     `main`/`master` regardless of level.
   → `--autonomy {gated,push-draft,full}`.
3. **External skill discovery?** May I discover/vet skills from external curated indexes for tasks
   here, or keep to locally-vaulted skills only?
   → `--skill-discovery {external,local-only}`.

## Persist the answers

```bash
python3 ~/.hermes-coder/scripts/repo_onboarding.py init --repo . \
    --autonomy gated --backlog true --backlog-project "My Project" \
    --skill-discovery external
```

Then confirm the resulting settings back to the user (the command echoes them).

## Skip path (declined interview)

If the user declines, write the safe-default marker so the repo still counts as onboarded and is
never re-asked:

```bash
python3 ~/.hermes-coder/scripts/repo_onboarding.py init --repo . --skip
```

Safe defaults: `autonomy: gated`, `skill_discovery: local-only`, backlog `enabled: false`. The user
can re-run `init` later (with `--force`) to change any of these.

## Idempotency & changing settings

- Re-running `init` with the same values is a **no-op success**.
- `init` **refuses** (exit 1) to overwrite a value that already differs — surface the conflict to
  the user and only re-run with `--force` after they approve. `--force` rewrites only the keys you
  pass and preserves any others in the file.

## How the settings take effect

- **autonomy / default_base** → read by `github-lifecycle` and `github-backlog` via the existing
  resolvers (`--flag` > repo file > global config > `gated`).
- **backlog enabled/project_name** → the `github-backlog` opt-in (`enabled: true`).
- **skill_discovery** → `skill_discovery.discover(..., repo=.)` returns no external candidates when
  the repo is `local-only` (fail-open to locally-vaulted skills).

## What this skill does NOT do

- It never assumes permissions on an unconfigured repo — it asks, or applies safe defaults on skip.
- It never widens autonomy on its own; only the user's answers (or an explicit `--force`) change it.
- It writes only the two config files; it touches no git remote and runs no network calls.
