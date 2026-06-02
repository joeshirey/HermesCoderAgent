# scripts

The flat, importable Python engine that backs every capability. The coordinator (driven by
[`../coordinator-core/SOUL.md`](../coordinator-core/SOUL.md)) invokes these as one-shot CLI
calls; most also expose `--json` for machine-readable output.

## Hard constraints

- **Stdlib-only. ZERO pip.** These run on a bare Python 3 install. There is no PyYAML —
  config is parsed with custom line/regex readers. Preserve this if you extend them.
- **Flat package, intra-coupled.** Several scripts import siblings (e.g. delivery/backlog
  call `harness_llm`; discovery calls `skill_ingest`/`security_auditor`). Keep them in one
  directory so imports resolve. `python3 -m py_compile scripts/*.py` should always pass.
- **No shell=True.** Git/`gh` calls use list-form `subprocess`.

## Index

### Harness / LLM routing

- **`harness_llm.py`** — Routes every LLM-backed support pass to the active coding harness
  (`resolve_engine`, `harness_generate`, `strip_fences`, `HarnessUnavailable`). The single
  choke point that makes the system harness-neutral. See
  [multi-harness](../capabilities/multi-harness/README.md).

### Triage & dispatch

- **`dynamic_curator.py`** — Complexity triage: sizes a task (S/M/L/XL), recommends
  routing + a tool budget (max skills/turns), and selects skills to inject.
- **`parallel_dispatch.py`** — Runs independent tasks concurrently, each isolated in its
  own git worktree + branch. Never auto-merges.

### Quality loop

- **`auto_healer.py`** — Parses check failures (pytest/ruff/eslint/tsc/go-vet), builds
  escalating fix prompts, retries up to 3×, escalates if it can't.
- **`systematic_debugger.py`** — Enforces reproduce → root-cause-trace → failing
  regression test before any fix; delegates the fix to the auto-healer.
- **`retrospective.py`** — Captures lessons after a struggle and injects relevant prior
  lessons into future dispatches.
  See [quality-loop](../capabilities/quality-loop/README.md).

### Security / dynamic tooling

- **`skill_discovery.py`** — Discovers task-relevant skills from a trusted-index allowlist;
  reputation-gates, vets through the pipeline, and injects approved skills.
- **`skill_ingest.py`** — Fetch → quarantine → classify → audit → vault, one step.
- **`security_auditor.py`** — Static + LLM security audit; `FAIL` hard-blocks.
- **`vetted_vault.py`** — The trust-tiered registry of approved tools + diff-audit update
  lifecycle.
- **`container_runner.py`** — Sandboxed execution of vaulted Tier 2/3 tools (no network,
  read-only mount).
  See [security-pipeline](../capabilities/security-pipeline/README.md) and
  [dynamic-tooling](../capabilities/dynamic-tooling/README.md).

### GitHub

- **`github_lifecycle.py`** — Branch/commit/push/PR + CI watch, behind a per-project
  autonomy gate, with a pre-commit hygiene gate and auto issue-close. See
  [github-delivery](../capabilities/github-delivery/README.md).
- **`github_backlog.py`** — Backlog as GitHub Issues: create/enrich/triage/groom. See
  [github-backlog](../capabilities/github-backlog/README.md).
- **`repo_onboarding.py`** — First-touch permission interview: persist a repo's autonomy,
  backlog opt-in, and external-skill-discovery policy to its two config files (idempotent;
  `--skip` writes safe defaults). Read by `github_lifecycle`/`github_backlog`/`skill_discovery`.

### Prose

- **`humanizer_gateway.py`** — Strips AI-tell phrasing from commits/PRs/docs/chat before
  they go out. See [humanizer](../capabilities/humanizer/README.md).

### Local models (optional)

- **`ollama_manager.py`**, **`ollama_utils.py`** — Local-model health/management. Off by
  default. See [local-models](../capabilities/local-models/README.md).

### Tests

- **`test_github_lifecycle.py`** — Issue-link inference, closing-keyword dedup, and the
  hygiene gate (secret/junk classification + machine-path content scan).
- **`test_skill_discovery.py`** — Discovery ranking + reputation gating + per-repo
  local-only gate.
- **`test_repo_onboarding.py`** — Onboarding status detection + idempotent init writes
  (no-op re-run, conflict refusal, `--force`, `--skip`).
- **`test_fabrication_guard.py`** — Guards against hand-authored skills being routed
  through the vault to manufacture trust.

Run them all from the snapshot:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
```
