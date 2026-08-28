---
name: security-auditor
description: Static + LLM code audit of a skill/tool source into FAIL/WARN/PASS. Never executes the code. The first guard in the dynamic ingestion pipeline (#6, Phase 4).
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [security, audit, static-analysis, llm, supply-chain, skills, mcp, vetting]
    related_skills: [security, reviewer, vetted-vault, skill-ingest, skill-discovery]
---

# Security Auditor

The first guard of the dynamic skill/tool ingestion pipeline (Backlog #6, Phase 4). It reviews a
source tree for dangerous patterns and returns a `FAIL | WARN | PASS` verdict **without ever
executing the code**. Two phases:

- **Phase A — static (deterministic):** regex scan that carries the blocking weight. Any
  FAIL-category match → aggregate `FAIL`. Categories: code execution (`eval`/`exec`/`os.system`/
  `shell=True`/`pickle.loads`/`child_process.exec`), obfuscation (base64/hex feeding exec, long
  opaque literals), sensitive-path/credential access (`~/.aws`, `~/.ssh`, `id_rsa`, keychain,
  browser cookies, `*_TOKEN`/`*_KEY` env dumps), and network egress (WARN: `requests.post`,
  `urllib`, `socket`, `fetch`, URLs, hardcoded IPs, `curl`/`wget`/`nc`).
- **Phase B — LLM (advisory):** a strict-rubric pass routed through the active coding harness
  (resolved from `--engine`/`coding.default_engine`). Corroborates/escalates; a clean static scan is
  not overridden to FAIL by a missing LLM. If the harness is down, Phase B is skipped and the
  static-only verdict still gates (exit 3).

**Aggregate:** any FAIL (static or LLM) → `FAIL`; else any WARN → `WARN`; else `PASS`.

## Safety rule

The auditor **never executes** the source it reviews. Execution happens later, sandboxed, via the
`container-runner`. A `FAIL` verdict must hard-block vaulting/injection.

## Dispatch

```
terminal(command="python3 ~/.hermes-coder/scripts/security_auditor.py --source '<path>' --json", workdir="~/.hermes-coder", timeout=120)
```

Static-only (no LLM pass):

```
terminal(command="python3 ~/.hermes-coder/scripts/security_auditor.py --source '<path>' --static-only --json", workdir="~/.hermes-coder", timeout=30)
```

Flags: `--engine` (coding harness for the LLM pass; default `coding.default_engine`), `--model`
(deprecated/ignored — the LLM pass uses the harness), `--max-llm-files` (default 12), `--static-only`,
`--json`.

## Reading the output (`--json`)

`AuditReport`: `source`, `verdict` (`FAIL|WARN|PASS`), `static_findings[]` (`file`, `line`,
`severity`, `category`, `snippet`), `llm_findings[]`, `llm_used`, `model` (the resolved harness),
plus `harness_down`.
**Gate on the `verdict` field, not just the exit code** — `WARN` exits 0.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | PASS or WARN (non-blocking) |
| 1 | FAIL (blocked) |
| 2 | Invalid arguments / source not found |
| 3 | LLM harness unavailable during the LLM pass (static-only verdict provided) |

## Graceful degradation

If the LLM harness is down, the audit still runs static-only and emits a verdict (exit 3). The static phase
carries the blocking weight, so a malicious source is still caught without the LLM.
