---
name: container-runner
description: Hardware-probe + sandboxed execution of vaulted tools. Network-isolated, read-only, resource-capped; never runs untrusted code on the host (#6, Phase 4).
version: 1.0.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [sandbox, container, docker, apple-container, isolation, security, execution, mcp]
    related_skills: [security, vetted-vault, skill-ingest, devops]
---

# Container Runner

The execution guard of the dynamic skill/tool pipeline (Backlog #6, Phase 4). Untrusted (Tier 2/3)
code is **never run on the host** — it runs inside a network-isolated, read-only, resource-capped,
timed sandbox, and **only from its immutable vault copy** (lock-in execution).

## Runner selection (`probe`)

- **arm64 + `container` on PATH → `apple-container`** (Apple Silicon native).
- **else `docker` on PATH → `docker`.**
- **else → `local-restricted`** (no sandbox available; refuses Tier 2/3 — only Tier 1 may run).

This host (Intel Mac, Docker present) selects **docker**.

## Dispatch

Probe:

```
terminal(command="python3 ~/.hermes-coder/scripts/container_runner.py probe --json", workdir="~/.hermes-coder", timeout=15)
```

Run a vaulted tool sandboxed (lock-in execution):

```
terminal(command="python3 ~/.hermes-coder/scripts/container_runner.py run --from-vault '<tool>' --cmd '<cmd>' --tier <n> --json", workdir="~/.hermes-coder", timeout=300)
```

Dry-run (print the sandbox command, execute nothing):

```
terminal(command="python3 ~/.hermes-coder/scripts/container_runner.py run --from-vault '<tool>' --cmd '<cmd>' --tier <n> --dry-run --json", workdir="~/.hermes-coder", timeout=30)
```

Flags: `--from-vault <name>` (lock-in; resolves the approved vault path) **or** `--source <path>`
(Tier 1, or Tier 2/3 only with `--allow-unvaulted` for trusted local testing), `--cmd` (required),
`--image` (default `nikolaik/python-nodejs:python3.11-nodejs20`), `--tier` (default 3), `--timeout`
(default 120), `--dry-run`, `--json`.

## Safety rules

- Docker invocation: `docker run --rm --network none --cpus 1 --memory 512m -v <path>:/work:ro -w
  /work <image> sh -lc '<cmd>'` — no network, read-only mount, CPU/memory caps, timeout.
- Tier 2/3 must come from the vault (`--from-vault`), not an arbitrary `--source` path.
- On `local-restricted` (no runtime), Tier 2/3 returns `blocked` — **never** fall back to host
  execution.

## Reading the output (`--json`)

`RunResult`: `runner`, `image`, `cmd`, `status` (`success|failed|timeout|blocked|dry-run`),
`returncode`, `duration_s`, `output_tail`, `error`, `sandbox_command`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success / dry-run |
| 1 | Run failed, or blocked (no sandbox for this tier) |
| 2 | Invalid arguments / no runner / vault name not found |
