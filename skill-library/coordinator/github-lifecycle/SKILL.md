---
name: github-lifecycle
description: Branch, commit, push, and open PRs with humanized messages, then monitor GitHub Actions CI. Per-project autonomy gating; blocks direct pushes to the default branch and pushes with a dirty tree. Never auto-merges.
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [github, git, pr, ci, delivery, commit, autonomy, humanizer]
    related_skills: [implementer, devops, reviewer, humanizer-gate]
---

# GitHub Lifecycle

End-to-end delivery: turn finished, reviewed work into commits, pushes, PRs, and CI feedback.

## When to trigger

After work has passed Quality and Reviewer checks and is ready to ship:

- Committing reviewed changes on a feature branch
- Pushing and opening a (draft) PR
- Watching GitHub Actions CI and alerting when the PR is ready for merge

Do NOT use for:

- Local-only experiments that won't be delivered
- Merging PRs — this tool never merges; that is always the user's manual action
- Drafting prose by hand — the tool drafts commit/PR messages from the diff and humanizes them internally

## Autonomy levels

Remote-mutating actions (`push`, `pr`) respect a per-project autonomy setting.
Precedence: `--autonomy` flag > `<repo>/.hermes-github.yaml` (`autonomy:`) > `config.yaml` `github.autonomy` > default `gated`.

| Level | push / pr behavior |
|-------|--------------------|
| `gated` (default) | Blocks; returns an `awaiting_confirmation` preview. Re-invoke with `--confirm` after the user approves. |
| `push-draft` | Pushes and opens **draft** PRs unattended; never marks ready. |
| `full` | Pushes, opens PRs, and (with `--ready`) marks ready-for-review — no confirmation. |

`commit` is always allowed — it is local-only.

## Dispatch

Commit (local; drafts + humanizes the message from the staged diff):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_lifecycle.py commit --repo '<project-dir>' --engine opencode --branch '<branch>' --json", workdir="~/.hermes-coder", timeout=600)
```

Message drafting is a support pass — `--engine opencode` (Gemini Flash) is the default for `commit`/`pr`; if opencode is unavailable, fall back to `--engine claude-code` (the tool also degrades to a deterministic message on its own).

```
```

**Pre-commit hygiene gate.** Before committing, the tool inspects the staged files. Staged
**secrets/credentials** (`.env`, `*.pem`/`*.key`/`*.p12`, `id_rsa`, `credentials.json`, …)
**block** the commit (status `blocked`, exit 1) with a `hygiene` report and suggested
`.gitignore` lines — fix it (`git rm --cached` + add to `.gitignore`) and re-commit, or pass
`--skip-hygiene` only for a deliberate false positive. **Build/dependency junk**
(`node_modules/`, `dist/`, `vendor/`, `.DS_Store`, `*.log`, …), a **missing `.gitignore`**,
and **hardcoded absolute machine/home paths in staged file content** (`/Users/<name>/…`,
`/home/<name>/…`, `C:\Users\<name>\…` — e.g. a Makefile pointing at `/Users/alice/go/bin/templ`)
only **warn** — the commit proceeds, but surface the warnings so the path can be made portable
(`~`, `$HOME`, or a tool-resolved path like `$(go env GOPATH)/bin`). Tilde/`$HOME` paths are
portable and never flagged; generated/lock files (`package-lock.json`, `go.sum`, …), binaries,
and vendored trees are skipped by the content scan. `.env.example`/`.env.sample` and `*.pub`
are never flagged. On a `blocked` result, do not push — resolve the hygiene issue first.

Push (gated — add `--confirm` only after user approval; pass `--force` when updating a rebased feature branch):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_lifecycle.py push --repo '<project-dir>' --force --json", workdir="~/.hermes-coder", timeout=180)
```

**Always push through this tool — never a raw `git push`.** The `push` subcommand enforces two
hard guards *before* the autonomy gate, each returning `"status": "blocked"` (exit 1) and
touching nothing remote:

- **Protected-branch guard.** Refuses to push when the current branch is the default/protected
  branch (`main`/`master`/the configured `default_base`). Feature work reaches the default branch
  only via a human-merged PR. A deliberate direct push requires `--allow-protected` — which still
  must clear the autonomy gate (`--confirm` when gated) and should only be used after explicit
  user approval.
- **Clean-tree guard.** Refuses to push when the working tree has uncommitted or untracked files,
  so locally-created deliverables (deploy scripts, generated docs, config) are never left off the
  remote. Commit everything intended first.

A raw `git push` via the terminal bypasses all of this — don't do it. If you have rebased a feature branch, run `push` with the `--force` flag instead, which translates into a safe, tracking `git push --force-with-lease`. Never force-push on protected branches, and only force-push feature branches after explicit rebase coordination or user instruction.
user explicitly instructs it.

Open PR (gated; draft unless autonomy=full and `--ready`). **Always pass `--issue <N>` when the
work resolves a backlog issue** — it adds `Closes #N` to the PR body so GitHub closes the
issue automatically when the PR merges (we never auto-merge — the human merges, GitHub
closes). Branch-name inference is only a backstop: if `--issue` is omitted the number is inferred
from an `issue-42-…`/`42-…`/`gh-42` branch, but a descriptive branch like `feat/firestore-integration`
yields nothing (the issue silently stays open), and a bare embedded digit like `oauth2` is never
matched. So don't rely on inference — thread the known issue number through explicitly.

```
terminal(command="python3 ~/.hermes-coder/scripts/github_lifecycle.py pr --repo '<project-dir>' --engine opencode --base main --issue <N> --json", workdir="~/.hermes-coder", timeout=180)
```

CI status (one-shot) / CI watch (blocking):

```
terminal(command="python3 ~/.hermes-coder/scripts/github_lifecycle.py ci-status --repo '<project-dir>' --json", workdir="~/.hermes-coder", timeout=60)
terminal(command="python3 ~/.hermes-coder/scripts/github_lifecycle.py ci-watch --repo '<project-dir>' --json", workdir="~/.hermes-coder", timeout=1900)
```

## The gated confirmation flow

1. Dispatch `push` or `pr`. If autonomy is `gated`, the tool returns `"status": "awaiting_confirmation"` and a `command_preview` — and does NOT touch the remote.
2. Surface the `command_preview` to the user and ask for approval.
3. On approval, re-run the same command with `--confirm`.

Do not pass `--confirm` preemptively. Do not change `--autonomy` to bypass the gate unless the user told you that project is allowed to run more autonomously.

### ⚠️ Strict Main Branch Protection

Never push code or merge commits directly to the `main` branch under any circumstance without the user's explicit prior permission. Even when performing post-merge repository hygiene or resolving untracked file mismatches, always ask the user for confirmation or open a dedicated Pull Request first. Pushing to `main` without consent is a critical violation of workflow boundaries.

### Strict Branch Safety Rule

- **Never push code or merge commits directly to the `main` or `master` branch under any circumstance without explicit user permission.** Even when correcting a merge mismatch, synchronizing missing files, or resolving repository hygiene issues, you must always open a Pull Request first or request direct confirmation before pushing to production branches.

## CI monitoring

- `ci-status` returns the current state immediately and exits — use it for a quick check.
- `ci-watch` blocks, polling every `ci_poll_interval` seconds until CI is terminal or `ci_watch_timeout` is hit.
- When either returns `"status": "ready_for_merge"`, alert the user that the PR is green and mergeable. **Never merge it yourself.**

## Pitfalls & Critical Verification

### The "Untracked Files" Push Leak

- **The Issue**: When running multi-step coding engine dispatches (especially in XL-sized tasks), some build tools or scripts may create final deliverables (such as `deploy.sh`, `DEPLOYMENT.md`, or static config files) on disk during the final stages. If the final coordinator `commit` step is skipped, these files will remain **untracked** locally. Running `push` or `pr` will result in a successful run, but those files will be completely absent from the remote GitHub branch and PR!
- **Enforced Solution**: The `push` subcommand now hard-blocks (`status: "blocked"`) when the working tree is dirty, so the leak can't ship silently. Don't rely on the guard alone, though: always run `git status` explicitly after the final task of a plan, and `git add` + commit every intended file before invoking `push`/`pr`.

## Reading the output

JSON output (`--json`):

- `status`: `done`, `awaiting_confirmation`, `failed`, `ci_pass`, `ci_fail`, `ci_running`, `not_mergeable`, `ready_for_merge`
- `action`: which subcommand ran
- `details`: human-readable result (commit sha, PR url, CI summary)
- `command_preview`: exact remote commands the tool would run (only when `awaiting_confirmation`)
- `error`: failure reason (only when `failed`)

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success / CI green / ready for merge |
| 1 | Awaiting confirmation (gated) or local action failed |
| 2 | Invalid arguments / nothing to commit |
| 3 | Infrastructure error (no gh, not authenticated, no remote, git error) |
| 4 | CI failed or PR not mergeable |
| 5 | CI still running at watch timeout |

## Safety and Hygiene

- **Strict Fork Targeting Rule:** When working inside a fork, never push or submit Pull Requests directly to the upstream parent repository under any circumstance without explicit user instructions. When creating a PR via the GitHub CLI, explicitly target the fork using `--repo <fork-owner>/<repo>` (e.g. `gh pr create --repo <fork-owner>/<repo>`) so the PR is created on the fork and does not go upstream. Each fork's `AGENTS.md` names its upstream.
- **Strict Rule:** Never, under any circumstance, push code directly to the `main` or `master` branch. Always checkout a feature branch, commit, push, and open a Pull Request. Any merging into `main` must be performed solely by the user or with explicit prior permission.
- Always use the humanizer gateway to polish PR/commit descriptions before delivery.
- Respect the project's autonomy level and never bypass confirmation gates when in `gated` mode.

## Relationship to the humanizer gateway

This tool calls `humanizer_gateway.humanize()` internally for commit (`commit`) and PR (`pr`) prose, so the Humanize workflow step is already covered for git deliverables. The LLM pass runs through the default harness (`claude -p`); if that harness is unavailable, the rule-filtered text is still used. Commits are always authored as the repository owner only — any `Co-Authored-By` trailer is stripped.

## Pitfalls & Best Practices

### Parallel Migration Heads and Alembic Linearization (Rebase Conflict)

- **The Issue**: When rebasing a feature branch on top of `main` after another developer's migration PR was merged, you may encounter a merge conflict on existing parent migrations or get an Alembic `Multiple head revisions are present for given argument 'head'` error on startup. This happens because both branches created new migrations branching from the same common ancestor, creating parallel heads in the Alembic graph.
- **The Solution**:
  1. **Accept Upstream Parent Migrations**: During `git rebase`, if a parent migration file conflicts, discard your local version and checkout the version from `main` (`git checkout origin/main -- path/to/parent_migration.py`) since the parent migration must match canonical history.
  2. **Linearize Your New Migration**: Open your newly created migration file and update its `down_revision` variable to point to the newly merged migration ID (the latest one from `main`) instead of the common ancestor. This linearizes the graph, making the upstream migration run first, followed by your new migration.
  3. **Non-Interactive Rebase Continue**: When running `git rebase --continue`, prepend `env GIT_EDITOR=true` (or equivalent) to allow Git to commit and complete the rebase automatically without freezing or hanging on interactive terminal editor prompts.

### Line-Ending Auto-Conversion Blocking clean-tree Guards (CRLF/LF)

- **The Issue**: On macOS and Windows hosts, running tests, syncing templates, or merging upstream changes can trigger Git to auto-convert line endings (CRLF $\leftrightarrow$ LF). This leaves one or more files perpetually "modified" in your working copy, which hard-blocks subsequent branch switching or remote pushes through the clean-tree safety check (`status: "blocked"`, `Working tree is not clean`). Even stashing (`git stash push -u`) may immediately reproduce the modification on checkout/read.
- **The Solution**:
  1. **Stage and Commit Directly**: Instead of fighting the automatic conversion with hard resets or force checkouts, stage and commit the line-ending normalizations directly (`git add <file> && git commit -m "chore(git): normalize line endings"`). This integrates the line-ending changes cleanly and returns the working tree to a perfectly clean status.
  2. **Never Attempt Force Resets**: Avoid running destructive `git reset --hard` commands if safety filters or approvals are active, as they will be blocked by non-interactive environment hooks. Commitment is always the safest path to a clean tree.

### The Staging-Commit Verification Gap

When coordinating multi-stage coding tasks (where some steps write configuration files, deployment scripts, or documentation), some intermediate tasks might not be automatically staged or committed.

- **The Trap**: Invoking `push` or `pr` on a branch that appears to be "up to date" (e.g. because only the first stage's `Dockerfile` was committed) will push the branch *without* the newly generated files (leaving them as untracked files in the local workspace).
- **The Rule**: Always run a local commit check (or `git status`) *explicitly* after completing the final task in an implementation plan, ensuring every single generated asset and config is fully staged and committed *before* triggering any remote push.
