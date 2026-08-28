# Guide: Skill discovery, vetting, caching & execution

How the coordinator acquires a capability it doesn't already have — safely. When a task
needs a skill that isn't in the local library, the coordinator can **discover** a candidate
from a curated allowlist, **vet** it through a security pipeline, **cache** the approved copy
in a trust-tiered vault, and **execute** any shipped code in a sandbox before it's ever
injected. This guide ties those stages into one narrative; each stage's deep reference is a
linked capability README.

> Safety here is **structural, not advisory** — third-party code is never injected or run
> directly. The pipeline shape enforces it; the coordinator isn't merely asked to be careful.

## The end-to-end flow

```
discover (read-only)  →  reputation-gate  →  ingest → audit → vault (cache)  →  sandbox  →  inject
```

Every M/L/XL task runs the read-only **discover** step and reports the result — even "no
remote candidate matched." Discovery is never silent; the decision is always shown (see
*The skill ledger* below).

## 1 — Discover

The coordinator ranks candidate skills against a curated allowlist of **trusted indexes**
(no writes, no fetches of code yet). Community indexes are opt-in, not default. This is the
[dynamic-tooling capability](../capabilities/dynamic-tooling/README.md), implemented by
[`scripts/skill_discovery.py`](../scripts/skill_discovery.py) and the
[`skill-discovery` skill](../skill-library/coordinator/skill-discovery/SKILL.md).

**Per-repo gate.** Whether discovery reaches out at all is governed by the repo's
`skill_discovery` setting (`external` vs `local-only`) in `.hermes-github.yaml`, captured
during [onboarding](../skill-library/coordinator/repo-onboarding/SKILL.md). A `local-only`
repo short-circuits discovery to an empty result — the system simply dispatches with local
skills. (See the [base-system guide](base-system-setup.md#step-6--first-touch-of-a-repo).)

## 2 — Reputation-gate

Each candidate carries a `trust` class, a `tier`, and a `sandbox_code` flag. The gate
decides what happens next:

- **Trusted** sources auto-vault on a clean audit.
- **Known / untrusted** sources require an explicit `--confirm`, and any code they ship is
  sandboxed.

Source-reputation overrides live in `SOURCE_REPUTATION` inside `skill_discovery.py`.

## 3 — Vet: ingest → audit

The candidate is pulled through the
[security pipeline](../capabilities/security-pipeline/README.md) in one step
([`scripts/skill_ingest.py`](../scripts/skill_ingest.py)):

```
fetch → quarantine → classify (trust tier) → security audit
```

The [`security_auditor`](../scripts/security_auditor.py) runs a static + LLM audit. A
**`FAIL` hard-blocks** the source regardless of reputation — it is never vaulted, never
injected. The trust tiers and their policies (Tier 1 local/host, Tier 2 trusted-org
auto-vault-but-sandbox, Tier 3 known/unknown confirm-and-sandbox) are tabulated in the
[security-pipeline README](../capabilities/security-pipeline/README.md#trust-tiers--reputation).

## 4 — Cache: the vetted vault

An approved source is copied into the **vetted vault** — an immutable, trust-tiered registry
of what's been cleared, with a diff-audit update lifecycle for re-fetches.
[`scripts/vetted_vault.py`](../scripts/vetted_vault.py) owns it. The vault is the cache layer:
once a skill is vaulted, the coordinator injects from the vault rather than re-fetching and
re-auditing. (Vault *contents* and the `.hermes-quarantine/` staging area are runtime state
and are deliberately excluded from this snapshot — see [SNAPSHOT.md](../SNAPSHOT.md).)

## 5 — Execute: sandbox

Tier 2/3 tools that ship runnable code are executed only inside a sandbox — **no network,
read-only mount** — via [`scripts/container_runner.py`](../scripts/container_runner.py). If
no sandbox is available, the coordinator does **not** fall back to host execution.

## 6 — Inject

Only an approved, vaulted (and for code, sandbox-cleared) skill is injected into the active
harness for the dispatch.

**Fail-open by design:** any fetch, audit, or harness failure falls back to **local-only**
injection. Discovery never blocks a dispatch — worst case, the task runs with the skills
already on hand.

## The skill ledger (show your work)

Because skill selection must never be invisible, every dispatch states what was brought to
bear — one of: *none needed* · *local only* · *discovery ran, nothing found* · *discovery
found something* (auto-vaulted+injected / awaiting `--confirm` / audit-FAIL blocked) ·
*discovery degraded* (fell open to local-only). The full ledger vocabulary is in the
[dynamic-tooling README](../capabilities/dynamic-tooling/README.md#the-skill-ledger-show-your-work).

## Configuration

The knobs live in [`config.sample.yaml`](../coordinator-core/config.sample.yaml):

- `skill_discovery` — allowlist, `top_k`, `auto_vault_trusted`, `require_confirm`,
  `sandbox_code_for`.
- `skill_ingest`, `security_auditor`, `vetted_vault`, `container_runner` — the pipeline
  policy blocks.

## Guardrails (from [SOUL.md](../coordinator-core/SOUL.md))

- Never inject or run a downloaded source directly — always ingest → audit → vault → sandbox.
- Never vault or inject a `FAIL` source.
- Never execute a Tier 2/3 tool outside the sandbox.
- Never hand-author a skill and route it through the pipeline to manufacture trust — a
  vaulted skill must come from a real remote source with verifiable provenance
  ([`test_fabrication_guard.py`](../scripts/test_fabrication_guard.py) enforces this).
- Only trusted sources auto-vault; known/untrusted require `--confirm`.

## Related

- [Security pipeline](../capabilities/security-pipeline/README.md) — the gate, in depth.
- [Dynamic tooling](../capabilities/dynamic-tooling/README.md) — the discovery layer.
- [Base system setup](base-system-setup.md) · [GitHub management](github-management.md)
