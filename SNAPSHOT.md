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
  `processes.json`, `*.pid`, `*.lock`, `logs/`, `cache/`, `sessions/`, `memories/`,
  `*_cache.json`, `state-snapshots/`.
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

## Scrub checklist

Run before committing. Every grep must come back empty (except intentional placeholder
examples like `/Users/you/...` in test fixtures).

```bash
# No real username anywhere:
grep -rn "<your-username>" .

# No PAT / API-key / bot-token shapes:
grep -rnE "ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,}|xox[baprs]-" .

# No real absolute machine/home paths (placeholders like /Users/you are fine):
grep -rnE "/Users/[a-z]|/home/[a-z]" . | grep -v "/Users/you"
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
