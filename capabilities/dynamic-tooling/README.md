# Capability: Dynamic tooling (discovery + injection)

When a task needs a skill the coordinator doesn't already have, it discovers candidates from
a curated allowlist of trusted indexes, vets them through the
[security pipeline](../security-pipeline/README.md), and injects the approved ones into the
active harness — all reputation-gated, all fail-open.

## The flow

```
discover (read-only)  →  reputation-gate  →  ingest → audit → vault → sandbox  →  inject
```

0. **Discover** ranked candidates against the allowlist (no writes). For **every** M/L/XL
   task this read-only step runs and its result is reported — even "no remote candidate
   matched". Discovery is never silent.
1. **Reputation gate.** Each candidate carries `trust` (trusted/known/untrusted), `tier`,
   and a `sandbox_code` flag. Trusted sources auto-vault on a clean audit; known/untrusted
   require `--confirm` and have shipped code sandboxed.
2. **Vet** through the pipeline (`ingest` reuses [skill_ingest](../security-pipeline/README.md));
   a `FAIL` audit hard-blocks.
3. **Inject** an approved, vaulted skill into the active harness.

**Fail-open by design:** any fetch/audit/harness failure falls back to local-only injection.
Discovery never blocks a dispatch. Scope is `SKILL.md` skills; MCP-server discovery is a
documented follow-on.

## The skill ledger (show your work)

Every dispatch states what skills were brought to bear, so the decision is never invisible.
The coordinator emits one of:

- *none needed* — dispatched with harness defaults
- *local only* — injected local skill(s) (Tier 1)
- *discovery ran, nothing found* — dispatched local-only
- *discovery found something* — auto-vaulted+injected / awaiting `--confirm` / audit-FAIL blocked
- *discovery degraded* — network/harness down, fell open to local-only

## Components

- **Script:** [`scripts/skill_discovery.py`](../../scripts/skill_discovery.py) (calls
  `skill_ingest` / `security_auditor` / `container_runner` from the security pipeline).
- **Skill:** [`skill-library/coordinator/skill-discovery`](../../skill-library/coordinator/skill-discovery/SKILL.md).
- **Design note:** [`DYNAMIC_TOOLING.md`](DYNAMIC_TOOLING.md).
- **Config:** the `skill_discovery` block in
  [`config.sample.yaml`](../../coordinator-core/config.sample.yaml) (allowlist, `top_k`,
  `auto_vault_trusted`, `require_confirm`, `sandbox_code_for`).
- **Tests:** [`scripts/test_skill_discovery.py`](../../scripts/test_skill_discovery.py).

## Guardrails

- M/L/XL tasks always run the read-only discover step and report the result; silent skill
  selection is not allowed.
- Only trusted sources auto-vault; known/untrusted require `--confirm`.
- Source-reputation overrides live in `SOURCE_REPUTATION` inside `skill_discovery.py`;
  community indexes are opt-in, not default.
