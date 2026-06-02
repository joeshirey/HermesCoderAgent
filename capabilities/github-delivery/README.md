# Capability: GitHub delivery

Turn finished, reviewed work into commits, pushes, PRs, and CI feedback — behind a
per-project autonomy gate, with a pre-commit hygiene gate and automatic issue-close. This
tool **never merges**; the human merges.

## What it does

- **commit** (always local) — drafts + humanizes the message from the staged diff, then
  commits. Runs the hygiene gate first.
- **push** / **pr** (gated) — respect a per-project autonomy level.
- **ci-status** / **ci-watch** — report GitHub Actions status; alert when green and
  mergeable.

## Autonomy levels

Precedence: `--autonomy` flag > `<repo>/.hermes-github.yaml` > `config.yaml github.autonomy`
> default `gated`.

| Level | push / pr behavior |
|-------|--------------------|
| `gated` (default) | Blocks; returns an `awaiting_confirmation` preview. Re-invoke with `--confirm` after the user approves. |
| `push-draft` | Pushes + opens **draft** PRs unattended; never marks ready. |
| `full` | Pushes, opens PRs, and (with `--ready`) marks ready — no confirmation. |

## The pre-commit hygiene gate

Before committing, staged files are inspected:

- **Secrets/credentials** (`.env`, `*.pem`/`*.key`/`*.p12`, `id_rsa`, `credentials.json`, …)
  → **block** (status `blocked`, exit 1). Fix with `git rm --cached` + `.gitignore` and
  re-commit; `--skip-hygiene` only for a genuine false positive.
- **Build/dependency junk** (`node_modules/`, `dist/`, `vendor/`, `.DS_Store`, `*.log`),
  a **missing `.gitignore`**, and **hardcoded absolute machine/home paths in staged file
  content** (`/Users/<name>/…`, `/home/<name>/…`, `C:\Users\<name>\…`) → **warn** only. The
  commit proceeds, but surface the warnings so non-portable paths get replaced with `~`,
  `$HOME`, or a tool-resolved path (e.g. `$(go env GOPATH)/bin`).

Tilde/`$HOME` paths, `.env.example`/`.env.sample`, and `*.pub` are never flagged;
lock/generated files, binaries, and vendored trees are skipped by the content scan.

## Automatic issue-close

When work resolves a backlog issue, **always pass `--issue <N>`** to `pr` — it appends
`Closes #N` to the PR body so GitHub closes the issue when the PR merges (we never
auto-merge; the human merges, GitHub closes). Branch-name inference is only a backstop:
`issue-42-…`/`42-…`/`gh-42` branches resolve, but a descriptive branch like
`feat/firestore-integration` yields nothing and the issue silently stays open. Thread the
known number through explicitly.

## Components

- **Script:** [`scripts/github_lifecycle.py`](../../scripts/github_lifecycle.py)
- **Skill:** [`github-lifecycle`](../../skill-library/coordinator/github-lifecycle/SKILL.md)
- **Config:** the `github` block in
  [`config.sample.yaml`](../../coordinator-core/config.sample.yaml).
- **Tests:** [`scripts/test_github_lifecycle.py`](../../scripts/test_github_lifecycle.py)
  (branch inference, closing-keyword dedup, hygiene classification, machine-path content
  scan).

## Guardrails

- Never auto-merge — alert the user when CI is green and let them merge.
- Respect the autonomy gate; surface the `command_preview` when `gated`.
- On a `blocked` commit, never push — fix the hygiene issue first.
- Commits authored as the user only; no `Co-Authored-By` trailers.
