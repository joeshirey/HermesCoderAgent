# About this snapshot

This repo is a **periodic, sanitized snapshot** of a private, live `hermes-coder` setup. It
exists to share the design and components, not to be a runnable distribution.

## What "snapshot, not source of truth" means

- The **live system is authoritative.** It evolves continuously; this repo is re-cut from it
  every so often. Expect drift between a given snapshot and the current live system.
- **No installer, no clone-and-run.** Files are genericized references. Paths, secrets, and
  host-platform runtime config have been removed or replaced with placeholders. You adopt
  pieces into your own setup; you don't boot this directly.
- **Curated, not complete.** The live system carries ~120 skills and a host-agent runtime
  (messaging transports, TTS/STT, browser, providers). This snapshot ships only the coding
  coordinator, its engine scripts, and the curated skills that the coordinator references.

## What is deliberately excluded

Never copied into the snapshot:

- **Secrets / credentials:** `.env`, `auth.json`, `auth.lock`, any API keys or tokens.
- **State / runtime:** `*.db*`, `channel_directory.json`, `gateway_state.json`,
  `processes.json`, `*.pid`, `*.lock`, `*.key`, `*.pem`, `*.token`, `logs/`, `cache/`,
  `sessions/`, `memories/`, `*_cache.json`, `state-snapshots/`, `sandboxes/`,
  `audio_cache/`, `image_cache/`, `pairing/`, `lsp/`, `hooks/`, `bin/`, `cron/`.
- **Vetted-vault contents** and `.hermes-quarantine/` (downloaded third-party code).
- **Personal/working content:** the live backlog, personal notes/blogs, drafts.
- **Host-agent runtime:** the full `config.yaml` (messaging transports, providers, voice,
  browser) — only a slim `coordinator-core/config.sample.yaml` is shipped.
- **Most skills:** the ~90 non-coding skill categories (apple, media, social, smart-home,
  productivity, research, etc.).

## How a snapshot is produced (re-snapshot loop)

This is the repeatable procedure used to refresh the snapshot from the live system. It is a
**fresh copy into a clean directory** — never a clone of the live home dir (a clone would
drag along the credential-bearing git remote and history).

1. **Copy curated files only** into the snapshot tree:
   - the engine scripts + their tests → `scripts/`
   - the curated skills (coordinator, coding-team, harness, and the referenced dev skills)
     → `skill-library/` (mirroring their live subpaths so cross-references resolve)
   - `SOUL.md` → `coordinator-core/`
   - the design docs → next to the capability that owns them
2. **Scrub & genericize** (security-critical — see checklist below).
3. **Author / refresh** the value-add: top README, this file, the capability READMEs, the
   sample config and `.env.example`, the deploy template, and the guides.
4. **Verify** (see checklist below), then `git init` with **no remote** and commit.

## Automating the loop (fail-closed publisher)

Steps 1–2 and 4 are repetitive and security-critical, so the live system runs them as a
scheduled **fail-closed publisher**: it refreshes the snapshot daily and pushes only when
every gate passes. The script is part of the live system and is **not shipped here** (it
hard-codes live machine paths). The principles it enforces — adopt them in your own
automation:

- **Allowlist, never denylist.** It copies only an explicit list of curated files
  (engine scripts, the curated skills, `SOUL.md`). A brand-new secret file added to the
  live home dir tomorrow can never leak, because it is not on the list. The hand-authored
  value-add (READMEs, guides, this file, the sample config / `.env.example`, the deploy
  template, `LICENSE`) is **frozen** — re-syncing it would clobber the editorial
  genericization with raw live prose.
- **Never clone the live home dir.** Its `.git` remote can embed a credential
  (a PAT in the URL). A clone would drag that along. The publisher copies files into a
  separate repo whose `origin` is asserted to be exactly the clean public URL with **no
  credentials** (`@`, `ghp_`, `github_pat` in the remote URL → abort).
- **Gates run in order and any failure aborts before commit/push:** lint-source
  (auto-fix then verify) → allowlist-copy → genericize → scrub-scan → `py_compile` +
  unit tests → lint-snapshot. An all-green run is the only path to `git push`.
- **Markdown linting is two-stage and mandatory.** The live source is linted *first*
  (auto-fixed in place, then re-verified) so the authoritative system stays clean and
  the snapshot never inherits drift; the snapshot is then linted again before push as a
  backstop. The linter is a **hard dependency** — a missing linter aborts (it is not an
  optional warning), and any residual violation after auto-fix aborts. Config
  (`.markdownlint.json`) exempts hard tabs inside fenced code blocks
  (`MD010: {code_blocks: false}`) so indented code samples are not mangled, while still
  flagging stray tabs in prose.
- **Scan only what could ship.** The scrub respects `.gitignore` (it scans tracked +
  untracked-but-not-ignored files). Gitignored runtime junk (`cache/`, local editor
  config, `sessions/`, …) lives in the working tree but can never be committed, so
  scanning it would only produce false aborts.
- **Distinguish machine identity from intentional attribution.** A machine username or
  home path is *always* a leak. The owner's legal name is a leak in synced code/docs
  (genericized away there) but is **intentional** in attribution files (`LICENSE`
  copyright, `NOTICE`), which are exempt from the name check — never from the
  token/credential checks.

## Scrub checklist

Run before committing. Every grep must come back empty (except intentional placeholder
examples like `/Users/you/...` in test fixtures).

```bash
# No real username anywhere:
grep -rn "<your-username>" .

# No PAT / API-key / bot-token / generic-secret shapes:
grep -rnE "ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,}|xox[baprs]-|sk-[A-Za-z0-9]{20,}" .

# No credential-bearing URL (user:secret@host) — this is how a PAT hides in a git remote:
grep -rnE "://[^/[:space:]:@]+:[^/[:space:]@]+@" .

# No real absolute machine/home paths (placeholders like /Users/you are fine):
grep -rnE "/Users/[a-z]|/home/[a-z]" . | grep -v "/Users/you"

# Owner's real name only where it belongs (LICENSE/NOTICE copyright); nowhere in code/docs:
grep -rn "<owner-name>" . | grep -vE "(^|/)(LICENSE|NOTICE)"
```

Manual checks:

- **No git remote.** `git remote -v` must be empty. Adopters use their own
  `gh auth login` / SSH. The live PAT-bearing remote must never appear here.
- **No live secrets.** Only `coordinator-core/.env.example` (placeholder values) ships.
- **No live config.** Only `coordinator-core/config.sample.yaml` (slim, sanitized) ships.
- **Deploy template uses placeholders** (`{{HERMES_HOME}}`, `{{BINARY_PATH}}`, `{{USER}}`).

## Verify checklist

```bash
# Scripts still import as a flat package (import coupling intact):
python3 -m py_compile scripts/*.py

# Bundled tests run from the snapshot:
python3 -m unittest discover -s scripts -p 'test_*.py'   # expect OK

# Manifest spot-check: curated skills present, excluded content absent:
find skill-library -name SKILL.md | wc -l   # ~30
test ! -e BACKLOG.md && test ! -e .env && echo "excludes OK"
```
