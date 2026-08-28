# hermes-coder — guided install (agent-driven)

**You are an AI coding agent (Claude Code, Antigravity, or OpenCode) and the user has
pointed you at this file to install the `hermes-coder` coordinator on their machine.** Read
this whole file first, then walk the user through the install **interactively**, one phase at
a time. This is a runbook for *you* to execute — not a document for the user to read alone.

---

## How you (the agent) must behave

1. **Do the work where you can.** When a step is a shell command and you have terminal
   access, run it yourself (show the user what you're running and why). When a step needs a
   GUI download, an OS-level installer, or a credential the user must type into a browser
   (any auth/login), **stop and give the user the exact commands or click-path**, then wait
   for them to confirm before continuing.
2. **Ask, don't assume.** At every decision point below, ask the user the question and wait
   for an answer. Use a clear multiple-choice prompt where one is offered.
3. **Confirm before destructive or system-wide actions** (installing system packages,
   writing to `~/Library/LaunchAgents`, deleting files). Summarize, then proceed on approval.
4. **One phase at a time.** Finish and verify a phase before starting the next. Report what
   happened after each phase.
5. **Install only what the user opts into.** Skill discovery (Phase 4), GitHub (Phase 5),
   Telegram and the WebUI (Phase 6), and the always-on service (Phase 7) are all optional. If
   the user declines an optional module, **actively clean up** so the installed system never
   references the missing capability — follow that phase's *“If DECLINED, remove”* manifest
   exactly. A half-installed module is worse than an absent one.
6. **Scope.** macOS and Linux are supported. Assume the user has admin rights. Windows
   (PowerShell / WSL2) is untested — if the user is on Windows, tell them they're on their
   own and offer best-effort WSL2 guidance only.
7. **Validate every phase *with the user*.** Each phase ends with a **✓ Validate** block —
   a short, concrete check the user performs themselves (open a new terminal, message the
   bot, hit a URL) so *they* see it working, not just you. Read it to them, state the
   expected result, and **wait for them to confirm** before starting the next phase. If the
   check fails, treat it as a failure under rule 4 — stop and diagnose. Run the agent-side
   commands yourself where you can, but always hand the user the human-visible check too.
8. **Detect before you install.** Never tell the user to install — or run an installer for —
   a tool that's already present. Every install step starts with a **detection probe**
   (`command -v <tool>` / `<tool> --version`). Three outcomes:
   - **Present and working** → *skip the install.* Report the detected version. Optionally
     offer to **update** it, but only with a command you're sure of (e.g.
     `npm update -g @anthropic-ai/claude-code`, `brew upgrade <formula>`); if you don't know
     the right update command for that tool, **don't guess** — link its docs and let the user
     decide. Never auto-update without asking.
   - **Installed but not running/authenticated** (e.g. Docker daemon down, `gh` not logged
     in) → *don't reinstall* — tell the user to **start it / authenticate it.**
   - **Absent** → install it (or hand the user the exact steps) per the phase.
   Phase 0 runs a one-time **detection sweep** so you know the lay of the land before you
   touch anything; each later phase re-confirms its own tool right before acting.

If at any point a command fails, stop, show the error, and diagnose with the user before
continuing. Don't barrel past failures.

---

## What gets built

Two pieces on disk:

```
~/.hermes/hermes-agent/   the Hermes Agent runtime code + its own venv (installed in Phase 1;
                          this path is fixed regardless of HERMES_HOME)

$HERMES_HOME/             the coordinator's home directory (you choose this in Phase 0:
                          ~/.hermes for a coder-only box, ~/.hermes-coder alongside a
                          general-purpose agent). Pointed at by the runtime:
  SOUL.md                 the coordinator's behavioral contract (system prompt)
  config.yaml             coordinator config (copied from config.sample.yaml, trimmed to choices)
  .env                    secrets (coordinator model key, optional Telegram tokens); never committed
  scripts/                the stdlib-only Python engine
  skills/                 curated SKILL.md files (roles, workflow, harnesses, coordinator tools)
  logs/                   runtime logs
```

The **Hermes Agent runtime** is what actually runs the coordinator as a persistent agent and
exposes the front-ends (CLI, Telegram, WebUI). The **coordinator** itself — its brain — lives in
`$HERMES_HOME`: it **plans, delegates, and reviews** code, while a **coding harness** (the CLI
you're running right now, and any others the user picks) does the actual writing.

Background concepts live in [`guides/base-system-setup.md`](guides/base-system-setup.md),
[`guides/skill-discovery-and-vetting.md`](guides/skill-discovery-and-vetting.md), and
[`guides/github-management.md`](guides/github-management.md). Don't re-explain them in depth —
link the user there if they want detail.

---

## Prerequisites (verify in Phase 0)

- **One coding harness already installed and authenticated** — the one you're running in. The
  user did this before opening this file (e.g. installed Claude Code and ran its login, or
  Antigravity + `gcloud` auth). If not, send them to that product's docs first:
  [Claude Code](https://docs.anthropic.com/en/docs/claude-code) ·
  [Antigravity / Gemini Code Assist](https://cloud.google.com/products/gemini/code-assist) ·
  [OpenCode](https://github.com/opencode-ai/opencode).
- **Python 3.9+** (`python3 --version`). The engine is **stdlib-only — zero pip**.
- **git** (`git --version`).
- **This repo, cloned locally.** The directory containing this `INSTALL.md` is your source —
  call it `REPO_DIR`.
- A **coordinator-model API key** (Gemini / Anthropic / OpenAI-compatible) — the model that
  *plans and reviews*. This is separate from whatever model the harness uses to write code.

---

## Phase 0 — Preflight

Run these and report results to the user:

```bash
uname -s                       # Darwin = macOS, Linux = Linux, anything else = untested
python3 --version              # need 3.9+
git --version
```

**Detection sweep — find out what's already installed before touching anything** (per
behavior rule 8). Run this once and record the results; each later phase uses them to decide
*skip / update / install* instead of blindly installing. Nothing here changes the system —
it only probes:

```bash
# Hermes Agent runtime (Phase 1)
([ -x ~/.hermes/hermes-agent/venv/bin/python ] && \
  ~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main --version) \
  && echo "hermes: present" || echo "hermes: absent"

# Coding harnesses (Phase 3) — at least one should already be here (the one running this)
for t in claude agy opencode; do command -v "$t" >/dev/null && echo "$t: $(command -v $t)" || echo "$t: absent"; done

# Optional-module tooling
command -v ollama >/dev/null && ollama --version            || echo "ollama: absent"   # Phase 3 opt 4
command -v node   >/dev/null && echo "node: $(node --version)  npm: $(npm --version)" || echo "node/npm: absent"
command -v brew   >/dev/null && echo "brew: $(brew --version | head -1)" || echo "brew: absent (macOS installer helper)"
command -v docker >/dev/null && { docker info >/dev/null 2>&1 && echo "docker: running" || echo "docker: installed but NOT running"; } || echo "docker: absent"  # Phase 4
command -v gh     >/dev/null && { gh auth status >/dev/null 2>&1 && echo "gh: installed + authed" || echo "gh: installed, NOT authed"; } || echo "gh: absent"      # Phase 5
```

Report the sweep to the user as a short inventory. For anything that prints **present /
installed**, you will *skip* its install below (and may offer an update); for **NOT
running / NOT authed**, you'll have them start or authenticate it rather than reinstall; only
**absent** tools get installed.

Establish two variables for the rest of the install (substitute the real values when you run
commands — don't rely on shell state persisting between your tool calls):

- `REPO_DIR` = the absolute path of the directory holding this `INSTALL.md`.
- `HERMES_HOME` = the coordinator's home directory — **ask the user, with a suggested default.**

**Ask the user which describes this machine, then pick the default home dir:**

> Will this machine run **only** the coding coordinator, or **also** a separate general-purpose
> Hermes agent?
>
> 1. **Only the coder** → suggest **`~/.hermes`** (the runtime's *default* home — no alias or
>    `HERMES_HOME` env var needed; you just run `hermes`).
> 2. **Also a general-purpose agent** → suggest **`~/.hermes-coder`** (a distinct home so the
>    coordinator doesn't collide with the default `~/.hermes` personal agent; reached via the
>    `coder` alias set up in Phase 6).

Accept the user's choice (or a custom absolute path they prefer) and set `HERMES_HOME` to it.
**This is the only place the path is decided.** Everywhere below shows `~/.hermes-coder` as the
running example — read it as *whatever `HERMES_HOME` you set here* and substitute your real path
in commands (the code blocks already use `$HERMES_HOME`).

> **Note on the single-agent case (`HERMES_HOME=~/.hermes`).** The Phase 1 runtime installs its
> *code* under `~/.hermes/hermes-agent/`; the coordinator's *config* (`SOUL.md`, `config.yaml`,
> `.env`) sits at the top of `~/.hermes/`. Installing the coordinator there **replaces the
> runtime's default persona** — which is exactly what a coder-only box wants. The two never
> conflict (code vs. config live in different subpaths).

Create the skeleton (uses whatever `HERMES_HOME` you set):

```bash
mkdir -p "$HERMES_HOME/scripts" "$HERMES_HOME/skills" "$HERMES_HOME/logs"
```

If `HERMES_HOME` already exists **with coordinator content** (a `SOUL.md`/`config.yaml` from a
prior install — *not* the runtime's own `hermes-agent/` subdir), **stop** and ask the user
whether to update in place, back up first (`mv "$HERMES_HOME" "$HERMES_HOME.bak-$(date +%Y%m%d)"`),
or abort.

> **✓ Validate:** Ask the user to run `ls "$HERMES_HOME"` in a terminal. They should see the
> empty `scripts`, `skills`, and `logs` folders. Confirm `python3 --version` printed 3.9 or
> higher and `uname -s` is `Darwin` or `Linux` (anything else = untested; warn them).

---

## Phase 1 — Install the Hermes Agent runtime

The coordinator runs on the **Nous Research Hermes Agent** — a host process that loads a home
directory (`HERMES_HOME`), reads its `SOUL.md` + `config.yaml`, and runs the agent loop. Install
it before the coordinator brain so the runtime is ready to point at the `HERMES_HOME` you chose
in Phase 0.

> **Authoritative source:** [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/).
> The install command below may change — if it fails, follow the install instructions on that
> page (or the project's README) instead of guessing.

**Already installed? (from the Phase 0 sweep)** If the runtime probe printed `hermes:
present`, **do not re-run the installer.** Report the version and move on — optionally ask the
user whether they want to update; if so, re-running the official installer is the supported
update path, but only with their OK. Re-install only if the runtime is absent or the probe
errored.

Install (it creates `~/.hermes/hermes-agent/` with its own virtualenv — it does **not** touch
your system Python). The runtime *code* always lives there; your `HERMES_HOME` *config* is
separate (even when `HERMES_HOME=~/.hermes`, since the code sits in the `hermes-agent/` subdir):

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

Piping a remote script to `bash` is a privileged action — **show the user the URL first and get
their OK** before running it (or have them run it themselves). They can also download and read
the script before executing.

Verify the runtime is present:

```bash
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main --version
```

The runtime is driven with `HERMES_HOME` pointing at the coordinator's home dir. If you chose
the **default `~/.hermes`** (coder-only box), `hermes` already finds it with **no env var** — no
alias needed. If you chose a **custom home** like `~/.hermes-coder`, you'll wire a convenient
alias in Phase 6. Nothing is "always-on" yet; that's the optional Phase 7.

> If the user only wants to invoke the engine's scripts ad-hoc through their harness (no
> persistent agent, no Telegram/WebUI), the runtime is still the cleanest way to run the
> coordinator loop — but you *can* skip Phase 1 and call `python3 "$HERMES_HOME/scripts/"*.py`
> directly. Ask the user which they want; default to installing the runtime.

> **✓ Validate:** Ask the user to open a **new terminal** and run
> `~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main --version`. They should see a
> version number — not `No such file or directory` or a Python traceback. (Phase 6 turns this
> into a friendly `coder` command; for now the long path confirms the runtime exists.)

---

## Phase 2 — Install the core

The core is always installed (planning, triage, review, auto-healing, debugging,
retrospective memory, parallel dispatch, humanizer). Copy these from `REPO_DIR`:

**Core scripts** → `~/.hermes-coder/scripts/`:

```
harness_llm.py  dynamic_curator.py  auto_healer.py  systematic_debugger.py
retrospective.py  parallel_dispatch.py  humanizer_gateway.py
```

**Core skills** → `~/.hermes-coder/skills/` (copy each directory, preserving the category path
`skill-library/<category>/<name>/` → `skills/<category>/<name>/`):

```
coding-team/architect  coding-team/implementer  coding-team/quality
coding-team/security   coding-team/docs         coding-team/devops  coding-team/reviewer
workflow/writing-plans workflow/test-driven-development workflow/requesting-code-review
software-development/plan software-development/spike software-development/systematic-debugging
coordinator/complexity-triage coordinator/auto-healing coordinator/systematic-debugger
coordinator/retrospective coordinator/parallel-dispatch coordinator/humanizer-gate
```

**Core config + contract:**

```bash
cp "$REPO_DIR/coordinator-core/SOUL.md"            "$HERMES_HOME/SOUL.md"
cp "$REPO_DIR/coordinator-core/config.sample.yaml" "$HERMES_HOME/config.yaml"
cp "$REPO_DIR/coordinator-core/.env.example"       "$HERMES_HOME/.env"
```

Then **fill in the coordinator model key**: ask the user which provider they're using and the
key, and write it into `~/.hermes-coder/.env`. If they use Anthropic (not the default Gemini)
as the *coordinator* model, also update the model/provider in `config.yaml`. Never echo the
key back or commit it.

> Note: the repo stores skills under `skill-library/`, but the live system and `SOUL.md`
> reference them as `skills/`. Always install into `~/.hermes-coder/skills/`.

After this phase, Phases 4 and 5 may trim `config.yaml` and `SOUL.md`. The default
`config.sample.yaml` ships **everything enabled** — you will disable/remove the blocks for any
module the user declines (see the manifests).

> **✓ Validate:** Have the user run `ls "$HERMES_HOME/SOUL.md" "$HERMES_HOME/config.yaml"`
> (both should exist) and
> `python3 -m py_compile "$HERMES_HOME/scripts/"*.py && echo OK` (should print `OK` with no
> traceback). The coordinator's brain and engine are now in place — it just can't be *talked
> to* until a front-end is wired in Phase 6.

---

## Phase 3 — Choose and install harness(es)

**Ask the user (multi-select — at least one):**

> Which coding engines should this system be allowed to use?
>
> 1. **Claude Code** (`claude -p`) — default
> 2. **Antigravity** (`agy -p`)
> 3. **OpenCode** (`opencode run`)
> 4. **OpenCode + Ollama** (OpenCode with local models via Ollama)

For **each selected** engine, check the Phase 0 sweep first: if `command -v` already found it
(the one running this install always will), **skip the install** — just confirm auth and
smoke-test. Only when it's **absent** do you install it (run the install if you can, otherwise
give the user the exact steps). Either way, have the user complete that engine's
**authentication** in their browser/terminal — link the product docs above; **do not duplicate
auth steps here.** Smoke-test each: `claude -p 'say hello'` / `agy -p 'say hello'` /
`opencode run 'say hello'`. If an engine is present but the user wants it updated, use that
tool's own updater (e.g. `npm update -g @anthropic-ai/claude-code`) — don't guess; link its
docs if unsure.

If **option 4** is selected, also set up local models:

- **Ollama — detect first.** If the Phase 0 sweep printed an `ollama` version, it's installed;
  skip the install and just make sure the service is running and a model is pulled. If
  **absent**, install it (macOS: `brew install ollama` — only if `brew` was detected — or the
  [ollama.com](https://ollama.com) installer; Linux: `curl -fsSL https://ollama.com/install.sh | sh`),
  start the service, then `ollama pull` a small model (skip the pull if `ollama list` already
  shows one you want).
- Copy `ollama_manager.py` and `ollama_utils.py` → `~/.hermes-coder/scripts/`, and the
  `coordinator/local-model-router` skill → `~/.hermes-coder/skills/coordinator/`.
- In `config.yaml`, set `ollama.enabled: true` and the `default_model` to what you pulled.
- In `SOUL.md`, the **"Local Model Routing"** section currently says local models are
  disabled — update it to reflect that local routing is available (you may remove the
  "Currently disabled" sentence).

If option 4 is **not** selected (the common case): **remove** `ollama_manager.py`,
`ollama_utils.py`, and the `coordinator/local-model-router` skill if you copied them; leave
`ollama.enabled: false`; and leave the `SOUL.md` "Local Model Routing" section as-is (it
already states local models are off and everything routes through the cloud harness).

**Then wire the selection into the installed system:**

- Set `coding.default_engine` in `config.yaml` to the user's preferred default among those
  selected (default to `claude-code` if selected).
- Copy **only the selected** harness skills into `~/.hermes-coder/skills/harness/`
  (`claude-code`, `antigravity`, and/or `opencode`). Do **not** copy harness skills for
  engines the user didn't pick.
- Edit the **"Harness Selection"** section of `~/.hermes-coder/SOUL.md` so it lists only the
  installed harnesses and names the chosen default. Remove the lines for any engine not
  installed.

> **✓ Validate:** For **each** engine the user selected, have them run its hello smoke-test in
> a terminal and confirm a short reply comes back: `claude -p 'say hi'` /
> `agy -p 'say hi'` / `opencode run 'say hi'`. If option 4 (Ollama), also have them run
> `ollama list` and see the model they pulled. A reply from every selected engine = the writers
> are reachable.

---

## Phase 4 — Skill discovery, vetting, caching & execution (OPTIONAL)

This module lets the coordinator discover task-relevant skills from a curated allowlist, vet
them through a security pipeline (ingest → audit → vault), cache approved copies, and run any
third-party code **sandboxed in Docker**. See
[`guides/skill-discovery-and-vetting.md`](guides/skill-discovery-and-vetting.md).

**Ask the user:**

> Install dynamic skill discovery, vetting, caching & sandboxed execution? It needs **Docker**
> for sandboxing third-party tools. (You can always add hand-vetted skills manually without
> this — see below.) [yes / no]

### If ACCEPTED

1. **Docker** must be available for sandboxed execution of Tier 2/3 tools. Use the Phase 0
   sweep result (re-probe if unsure):
   - `docker: running` → **already good**, nothing to install or start.
   - `docker: installed but NOT running` (the binary exists, `docker info` fails) → **do not
     reinstall** — tell the user to **start Docker** (launch Docker Desktop on macOS, or
     `sudo systemctl start docker` on Linux) and wait until `docker info` succeeds.
   - `docker: absent` → instruct the user to install **Docker Desktop**
     ([docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)) on
     macOS, or Docker Engine on Linux, then start it.
   In all cases, don't proceed until `docker info` succeeds.
2. Copy these **scripts** → `~/.hermes-coder/scripts/`:

   ```
   skill_discovery.py  skill_ingest.py  security_auditor.py  vetted_vault.py
   container_runner.py  test_skill_discovery.py  test_fabrication_guard.py
   ```

3. Copy these **skills** → `~/.hermes-coder/skills/coordinator/`:

   ```
   skill-discovery  skill-ingest  security-auditor  vetted-vault  container-runner
   ```

4. Keep these `config.yaml` blocks (they're already present from the sample):
   `skill_discovery`, `skill_ingest`, `security_auditor`, `vetted_vault`, `container_runner`.
5. Leave the discovery-related sections of `SOUL.md` in place.

### If DECLINED — clean up so the system never references it

Remove from `~/.hermes-coder/`:

- **scripts:** `skill_discovery.py`, `skill_ingest.py`, `security_auditor.py`,
  `vetted_vault.py`, `container_runner.py`, `test_skill_discovery.py`,
  `test_fabrication_guard.py` (don't copy them in the first place if installing fresh).
- **skills:** `skills/coordinator/{skill-discovery,skill-ingest,security-auditor,vetted-vault,container-runner}`.
- **config.yaml blocks:** delete `skill_discovery:`, `skill_ingest:`, `security_auditor:`,
  `vetted_vault:`, `container_runner:` (and their comment headers).
- **SOUL.md passages** (use Edit to delete each block, matched by its distinctive opening):
  - The entire Execute bullet beginning *“**Dynamic skill discovery + injection (discover →
    reputation-gate …”* through its end *“… and `vetted-vault` coordinator skills.)”*.
  - In the **"State the skill ledger"** bullet, delete the three sub-lines beginning
    *“Discovery ran, nothing found”*, *“Discovery found something”*, and *“Discovery
    degraded”*, and drop the clause *“and M/L/XL tasks always run the read-only discover step
    …”*. Keep the *“No skills needed”* and *“Local only”* lines.
  - These **"What You Do NOT Do"** bullets: *“You do not dispatch without stating the skill
    ledger …”* (or trim its discovery clause), *“You do not inject a non-local (Tier 2/3)
    skill …”*, *“You do not vault or inject a source the security auditor marked FAIL …”*,
    *“You do not execute a non-local (Tier 2/3) tool outside the container sandbox …”*, *“You
    do not auto-vault a discovered skill …”*, *“You do not fabricate, hand-author …”*.

> **Even without this module**, the user can still add **global skills/tools manually**: drop a
> `SKILL.md` into `~/.hermes-coder/skills/<category>/<name>/` and it applies to **all**
> sessions as a local (Tier 1) skill. There's just no automated discovery, audit, vault, or
> sandbox — the user vets anything they add themselves. Tell them this when they decline.

> **✓ Validate (if ACCEPTED):** Have the user run `docker info` (should succeed, not "cannot
> connect") and `python3 -m unittest discover -s "$HERMES_HOME/scripts" -p 'test_skill_*.py'`
> (tests pass). Then a read-only dry run:
> `python3 "$HERMES_HOME/scripts/skill_discovery.py" discover --task "add a CLI flag"` — it
> should return candidates (or a clean "nothing found"), not a crash.
> **✓ Validate (if DECLINED):** Run the orphan grep —
> `grep -rln "skill_discovery\|vetted_vault\|container_runner" "$HERMES_HOME/SOUL.md" "$HERMES_HOME/config.yaml"`
> should print **nothing**.

---

## Phase 5 — GitHub integration (OPTIONAL)

This module adds gated delivery (commit/push/PR/CI with a pre-commit hygiene gate and auto
issue-close), GitHub-Issues backlog management, and first-touch repo onboarding. See
[`guides/github-management.md`](guides/github-management.md).

**Ask the user:**

> Install GitHub integration (gated commit/push/PR + CI watch, GitHub-Issues backlog, and
> per-repo onboarding)? It uses the **`gh` CLI** with your own GitHub auth. [yes / no]

### If ACCEPTED

1. **GitHub CLI — detect first** (Phase 0 sweep):
   - `gh: installed + authed` → **nothing to do** here; skip install and auth.
   - `gh: installed, NOT authed` → **don't reinstall** — just have the user run
     `gh auth login` (link [the gh docs](https://cli.github.com/manual/); don't inline scopes).
   - `gh: absent` → install it (macOS `brew install gh` — only if `brew` was detected — Linux
     per [cli.github.com](https://cli.github.com)), then have the user run `gh auth login`.
2. Copy these **scripts** → `~/.hermes-coder/scripts/`:

   ```
   github_lifecycle.py  github_backlog.py  repo_onboarding.py
   test_github_lifecycle.py  test_repo_onboarding.py
   ```

3. Copy these **skills** → `~/.hermes-coder/skills/coordinator/`:

   ```
   github-lifecycle  github-backlog  repo-onboarding
   ```

4. Keep the `github` and `github_backlog` `config.yaml` blocks. Default autonomy is `gated`
   (safest) — confirm with the user or leave as-is.
5. Leave the GitHub/onboarding/delivery/backlog sections of `SOUL.md` in place.

### If DECLINED — clean up so the system never references it

Remove from `~/.hermes-coder/`:

- **scripts:** `github_lifecycle.py`, `github_backlog.py`, `repo_onboarding.py`,
  `test_github_lifecycle.py`, `test_repo_onboarding.py`.
- **skills:** `skills/coordinator/{github-lifecycle,github-backlog,repo-onboarding}`.
- **config.yaml blocks:** delete `github:` and `github_backlog:` (and their comment headers).
- **SOUL.md passages** (delete each, matched by its distinctive opening):
  - **Core Principle 6** — *“**Capture before building.** …”*.
  - **Workflow step 0** — *“**Onboard (first touch)** …”* (the whole numbered step + its code
    block); renumber the remaining steps if you like, or leave the numbering.
  - In **Workflow step 2 (Triage)**, the intake-gate block beginning *“**Capture new work to
    the backlog before building (intake gate).** …”* through *“… don't begin implementation on
    an uncaptured enhancement.”*.
  - **Workflow step 7** — the entire *“**Deliver** …”* step including its **Push guards**,
    **Commit hygiene**, and **Backlog as GitHub Issues** subsections.
  - These **"What You Do NOT Do"** bullets: the onboarding bullet (*“… before it is onboarded
    …”*), the autonomy/push/PR bullet, the default-branch bullet, the raw-`git push` bullet,
    the unclean-tree bullet, the self-remediate-on-remote bullet, the never-auto-merge bullet,
    the *“… before it is captured in the backlog …”* bullet, the *“… repo that has not opted
    in …”* bullet, the push-backlog-mutations bullet, the `pr --issue <N>` bullet, the
    *“create/enrich/triage close”* bullet, and the *“groom close”* bullet.

> If GitHub is declined but Phase 4 (skill discovery) was installed, the per-repo
> external-vs-local-only discovery gate normally captured during onboarding no longer applies.
> In that case discovery falls back to the `skill_discovery` config default (external). Tell
> the user they can flip the whole system to local-only by setting `skill_discovery.enabled:
> false` or editing the allowlist in `config.yaml`.

> **✓ Validate (if ACCEPTED):** Have the user run `gh auth status` (should show them logged in
> to github.com) and `python3 -m unittest discover -s "$HERMES_HOME/scripts" -p 'test_github*.py' -p 'test_repo_onboarding.py'`
> (tests pass). The full end-to-end commit/PR flow is exercised in Phase 8.
> **✓ Validate (if DECLINED):** Run the orphan grep —
> `grep -rln "github_lifecycle\|github_backlog\|repo_onboarding" "$HERMES_HOME/SOUL.md" "$HERMES_HOME/config.yaml"`
> should print **nothing**.

---

## Phase 6 — Connect a front-end (CLI · Telegram · WebUI)

How will the user actually *talk to* the coordinator? There are three front-ends; the CLI is
always set up, Telegram and the WebUI are optional and **both require the Phase 1 runtime**.

### 6a — CLI command (always)

How the user launches the coordinator depends on the `HERMES_HOME` they chose in Phase 0:

- **Default home (`~/.hermes`, coder-only box):** nothing to set up — `hermes` finds it
  automatically. They run `hermes` directly. (Optionally still alias it to `coder` for a name
  that says *what it is*, but it's not required.)
- **Custom home (e.g. `~/.hermes-coder`, alongside a general-purpose agent):** add an alias so
  they don't retype the env var. Put this in their shell rc (`~/.zshrc` on macOS default,
  `~/.bashrc` on most Linux), substituting the real path:

  ```bash
  alias coder='HERMES_HOME=~/.hermes-coder hermes'
  ```

  Then `source` the rc (or open a new shell). Pick whatever alias name the user likes
  (`coder`, `hc`, …); just keep `HERMES_HOME` pointed at their chosen home.

> **Why this matters with multiple Hermes instances.** The same runtime can host more than one
> home dir — a general-purpose personal agent at the default `~/.hermes` *and* a coding
> coordinator at a custom path. `HERMES_HOME` is the only thing that selects which one runs, so a
> dedicated alias (`coder` → the coordinator's home) is what reaches the coordinator
> specifically. If the coordinator *is* the only agent, putting it at `~/.hermes` means plain
> `hermes` already is the coordinator — no alias needed.

> **✓ Validate:** Tell the user: *open a brand-new terminal, type `coder` (or `hermes` if you
> used the default home), and say hi to it.* The coordinator should start and reply in the
> terminal. (If `coder` isn't found, the rc wasn't sourced — open another new terminal or
> `source ~/.zshrc`.) Have them exit with `Ctrl+C` once they've seen a reply.

### 6b — Telegram integration (OPTIONAL)

Lets the user drive the coordinator from Telegram (and receive its status pings) instead of a
terminal. **Ask the user:** *Connect a Telegram bot? [yes / no]*

**If yes:**

1. **Create a bot.** In Telegram, message **@BotFather**, send `/newbot`, follow the prompts,
   and copy the **bot token** it returns. (Tell the user to do this — you can't.)
2. **Find the allowed user/chat IDs.** The user can message **@userinfobot** (or similar) to
   get their numeric Telegram user ID. For a group/channel, get its chat ID and (if it's a
   forum) the thread ID.
3. **Write the values into `~/.hermes-coder/.env`** (these keys already exist in the copied
   `.env`; fill them, never echo them back, never commit):

   ```
   TELEGRAM_BOT_TOKEN=...              # from @BotFather
   TELEGRAM_ALLOWED_USERS=...          # comma-separated numeric user IDs allowed to talk to it
   TELEGRAM_HOME_CHANNEL=...           # optional: chat/channel ID for status pings
   TELEGRAM_HOME_CHANNEL_THREAD_ID=... # optional: forum thread ID within that channel
   ```

4. **Enable the transport in the Hermes Agent.** The actual Telegram *transport wiring* is a
   property of the **Hermes Agent runtime config**, which is intentionally **not** shipped in
   this snapshot. Point the user at the
   [Hermes Agent docs](https://hermes-agent.nousresearch.com/) for how to turn on the Telegram
   messaging transport in the runtime, and have them confirm the runtime picks up the `.env`
   values above.
5. **Test:** start the agent (`coder` or, later, the Phase 7 service) and send it a message
   from an allowed account. Confirm it replies and that *non-allowed* accounts are ignored.

> **Use a separate bot per instance.** If the user also runs a general-purpose Hermes agent
> (the `~/.hermes` instance from the alias note above), create a **second** @BotFather bot for
> the coordinator and put *its* token in `~/.hermes-coder/.env`. Sharing one token across two
> instances crosses the wires — personal and coding conversations land on the same bot.

> **✓ Validate:** With the agent running (`coder`, or the Phase 7 service), tell the user:
> *from your phone, message your bot "hi" — it should reply within a few seconds.* Then have
> them confirm the allowlist works: a message from a **non-allowed** account should get **no**
> response. Both behaviors = Telegram is wired correctly.

**If no:** leave the `TELEGRAM_*` keys blank in `.env`. Nothing else references them, so no
cleanup is needed.

### 6c — WebUI (OPTIONAL)

A local web dashboard for the coordinator —
[hermes-webui](https://github.com/nesquena/hermes-webui) by nesquena. **Ask the user:**
*Install the local WebUI? [yes / no]*

**If yes:**

1. Clone it somewhere outside the home dir (e.g. `~/src`) — **but first check whether it's
   already cloned.** If a `hermes-webui/` checkout already exists, don't re-clone; update it
   with `git -C hermes-webui pull` instead:

   ```bash
   [ -d hermes-webui/.git ] && git -C hermes-webui pull \
     || git clone https://github.com/nesquena/hermes-webui.git
   ```

2. **Set a password before exposing it.** The WebUI reads `HERMES_WEBUI_PASSWORD` (and
   optionally `HERMES_WEBUI_HOST`/`HERMES_WEBUI_PORT`) from a `.env` in its own directory.
   Always set a password — even bound to localhost:

   ```bash
   cd hermes-webui
   cat > .env <<'EOF'
   HERMES_WEBUI_PASSWORD=choose-a-strong-password
   HERMES_WEBUI_HOST=127.0.0.1
   EOF
   ```

3. Launch it against the coordinator's home dir (keeps its own state under
   `$HERMES_HOME/webui`, and `--skip-agent-install` because Phase 1 already installed the
   runtime — this also avoids the bootstrap's own `curl | bash` step):

   ```bash
   HERMES_HOME="$HERMES_HOME" HERMES_WEBUI_STATE_DIR="$HERMES_HOME/webui" \
     python3 bootstrap.py 8788 --skip-agent-install --no-browser
   ```

4. Open **<http://localhost:8788>** and confirm it loads and can see the coordinator. Check the
   project's README for its own prerequisites and any other options; **don't duplicate them
   here** — link the user to the repo.

> **Multiple instances → different ports + state dirs.** If the user also runs a WebUI for a
> general-purpose `~/.hermes` agent, give each its own port and `HERMES_WEBUI_STATE_DIR` (e.g.
> the personal agent on `8787`, the coordinator on `8788`) so they don't collide.

> **✓ Validate:** Tell the user: *open <http://localhost:8788> in your browser, log in with the
> password you set, and start a session.* The dashboard should load and the coordinator should
> respond to a message typed in the browser. If the page doesn't load, check the `bootstrap.py`
> terminal for errors (often a port already in use or a missing password).

**If no:** skip — nothing was installed, nothing to clean up.

---

## Phase 7 — Operations: always-on, sleep, backup (OPTIONAL)

Phases 1–6 let the user run the coordinator on demand (`coder …`, WebUI, or Telegram while the
agent is running). This phase is for users running it as a **dedicated always-on box**. Each
sub-step is independent — offer them as a menu and skip what the user doesn't want.

### 7a — Prevent sleep (macOS, dedicated box only)

If the coordinator lives on a Mac that must stay reachable 24/7, disable sleep on both AC and
battery (battery matters for brief power blips):

```bash
sudo pmset -c sleep 0 && sudo pmset -c disksleep 0   # AC power
sudo pmset -b sleep 0 && sudo pmset -b disksleep 0   # battery
pmset -g custom                                      # verify both show sleep 0 / disksleep 0
```

This is a system-wide power change — confirm with the user first. Skip it for a laptop the user
also uses normally. (Linux: adjust the desktop/logind sleep settings instead; best-effort.)

> **✓ Validate:** Have the user run `pmset -g custom` and confirm both the AC and Battery
> sections show `sleep 0` and `disksleep 0`.

### 7b — Always-on service

**Ask the user:** *Run hermes-coder as an always-on background service? [yes / no]*

If **yes**: follow [`deploy/README.md`](deploy/README.md) to render and load
`deploy/com.hermes-coder.agent.plist.template` (substitute `{{USER}}`, `{{HERMES_HOME}}`,
etc.) into `~/Library/LaunchAgents` on macOS. On Linux, adapt to a systemd **user** unit (the
template is macOS-specific; tell the user this is best-effort). Confirm the service is running
(`launchctl list | grep hermes`) and survives a logout/login. If **no**: skip — invoking
`coder` directly is fully supported.

> **✓ Validate:** Have the user run `launchctl list | grep hermes` and confirm the entry shows
> exit code `0` (not `1`). Then the real test: *log out and back in (or reboot), then message
> the bot / hit the WebUI without starting anything manually* — it should answer on its own.

### 7c — Back up the config (optional)

The home dir is hand-tuned state worth preserving. Offer to back `~/.hermes-coder` up to a
**private** git repo — but the `.gitignore` must exclude **all secrets and runtime state**
first: `.env`, `auth.json`, `*.key`/`*.pem`/`*.token`, `*.db*`, `logs/`, `sessions/`,
`*.pid`/`*.lock`, `gateway_state.json`, `channel_directory.json`, caches, `webui/`, and
`node_modules/`. With GitHub integration installed (Phase 5), the cleanest path is
`gh repo create <name> --private` then an initial commit; otherwise the user creates a private
repo and adds the remote themselves. **Never commit `.env` or any token.** A nightly
commit-and-push (cron/launchd) keeps it current — register it deliberately, only if asked.

> **✓ Validate:** From inside `$HERMES_HOME`, run
> `git ls-files | grep -E '\.env$|auth\.json|\.key$|\.pem$|\.token$'` — it must print
> **nothing** (no secret is tracked). Then confirm the private repo on GitHub shows the initial
> commit. Secrets absent + commit present = the backup is safe.

### Operational notes & troubleshooting

- **Scheduled jobs** (nightly backlog triage, weekly grooming) are **never auto-registered**.
  If the user wants them, help them add their own cron/launchd entries deliberately.
- **Service exits cleanly and doesn't restart.** macOS `KeepAlive`/`SuccessfulExit:false` only
  restarts on a *non-zero* exit. After a clean stop, reload: `launchctl unload` then `load` the
  plist.
- **Harmless platform errors in logs.** The runtime probes every messaging platform; lines like
  `[Discord] No bot token configured` when only Telegram is set up are expected noise, not a
  failure. Check `~/.hermes-coder/logs/` for real errors.

---

## Phase 8 — Verify

```bash
# Runtime is installed and runnable:
~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main --version

# Engine still imports as a flat package (only the scripts that were installed):
python3 -m py_compile "$HERMES_HOME/scripts/"*.py && echo "compile OK"

# Run whatever tests came with the installed modules:
python3 -m unittest discover -s "$HERMES_HOME/scripts" -p 'test_*.py'

# The coordinator has no hardcoded engine outside the installed harness skills:
grep -rn "claude -p" "$HERMES_HOME/SOUL.md" \
  "$HERMES_HOME/skills/coding-team" "$HERMES_HOME/skills/workflow" \
  && echo "UNEXPECTED — investigate" || echo "clean"

# Installed harness skills match what the user selected:
ls "$HERMES_HOME/skills/harness/"*/SKILL.md
```

If a declined module was cleaned up correctly, **grep should find no orphan references**:

```bash
# Example for a declined GitHub module — expect no matches:
grep -rln "github_lifecycle\|github_backlog\|repo_onboarding" "$HERMES_HOME/SOUL.md" "$HERMES_HOME/config.yaml"
# Example for a declined discovery module — expect no matches:
grep -rln "skill_discovery\|vetted_vault\|container_runner" "$HERMES_HOME/SOUL.md" "$HERMES_HOME/config.yaml"
```

> **✓ Validate (end to end — the real proof):** Have the user drive a small **real task**
> through whichever front-end they set up — terminal `coder`, Telegram, or the WebUI. Two good
> first asks:
>
> - *"Create a hello-world script and a test for it in /tmp/hc-smoke."*
> - *"Clone <https://github.com/octocat/Hello-World> into /tmp/hello and tell me what's in it."*
>
> Watch the coordinator **plan → dispatch the coding harness → review → report back**. The user
> seeing that full loop complete is the install's real success criterion — not just green
> test output.

Then summarize for the user: which harnesses are active, which optional modules are installed,
which front-ends are connected (CLI / Telegram / WebUI), whether the always-on service is
running, and where the home dir lives.

---

## Module manifest (quick reference)

| Module | Phase | Scripts | Skills (under `skills/`) | config.yaml blocks |
|--------|-------|---------|--------------------------|--------------------|
| **Hermes Agent runtime** (recommended) | 1 | (installed to `~/.hermes/`, not the home dir) | — | — |
| **Core** (always) | 2 | harness_llm, dynamic_curator, auto_healer, systematic_debugger, retrospective, parallel_dispatch, humanizer_gateway | coding-team/*· workflow/* · software-development/* · coordinator/{complexity-triage,auto-healing,systematic-debugger,retrospective,parallel-dispatch,humanizer-gate} | coding, skills, curator, triage, humanizer, auto_healing, systematic_debugger, retrospective, parallel_dispatch |
| **Harness** (≥1) | 3 | (ollama_manager, ollama_utils — only for opt 4) | harness/{selected} · (coordinator/local-model-router — only opt 4) | ollama (enabled only for opt 4) |
| **Skill discovery** (opt) | 4 | skill_discovery, skill_ingest, security_auditor, vetted_vault, container_runner, test_skill_discovery, test_fabrication_guard | coordinator/{skill-discovery,skill-ingest,security-auditor,vetted-vault,container-runner} | skill_discovery, skill_ingest, security_auditor, vetted_vault, container_runner |
| **GitHub** (opt) | 5 | github_lifecycle, github_backlog, repo_onboarding, test_github_lifecycle, test_repo_onboarding | coordinator/{github-lifecycle,github-backlog,repo-onboarding} | github, github_backlog |
| **Front-ends** (CLI always; Telegram/WebUI opt) | 6 | — (CLI alias; WebUI cloned separately) | — | — (Telegram uses `.env` `TELEGRAM_*`) |
| **Operations** (opt) | 7 | — (sleep via `pmset`; service via `deploy/` template; backup via `git`/`gh`) | — | — |

Rule of thumb: **install a module = copy its scripts + skills and keep its config blocks;
decline a module = don't copy them (or delete them) and remove its config blocks + the SOUL.md
passages listed in that phase.** When in doubt, run the Phase 8 orphan-reference greps and fix
anything they surface.

---

## After install (mention these, don't auto-do them)

Once the smoke test passes, point the user at a few common next steps:

- **Per-repo conventions:** drop a `CLAUDE.md` (or the harness's equivalent) in their project
  repos so the *coding* harness follows that project's style — separate from the coordinator's
  `SOUL.md`.
- **More users:** add Telegram user IDs to `TELEGRAM_ALLOWED_USERS` (comma-separated).
- **Tune the role skills:** edit the `coding-team/*` skills to match the team's review bar.
- **Cost tracking:** the coordinator model and the harness model bill separately — watch both.
- **MCP / external tools:** the runtime can connect to GitHub, Linear, etc. via MCP; see the
  [Hermes Agent docs](https://hermes-agent.nousresearch.com/).
