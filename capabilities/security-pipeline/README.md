# Capability: Security pipeline

A structural guarantee that no third-party skill or tool is ever injected or executed
without being audited, vaulted, and (when untrusted) sandboxed. Safety is enforced by the
pipeline shape, not by asking the model to be careful.

## The pipeline

```
source (URL / clone)
   │
   ▼  skill_ingest.py
fetch → quarantine → classify (trust tier) → security audit
   │                                              │
   │                                       FAIL → hard-block (never vaulted)
   ▼
vetted_vault.py  ──►  approved, immutable vault copy
   │
   ▼  container_runner.py
sandboxed execution (Tier 2/3: no network, read-only mount)
```

## Trust tiers & reputation

Every source is classified, and the classification drives policy:

| Tier | Source kind | Policy |
|------|-------------|--------|
| 1 | Local / first-party | Auto — runs on host |
| 2 | Trusted org (anthropic/google/aws/microsoft/…) | Auto-vault on clean audit; **sandbox** to run |
| 3 | Known / unknown / community | Require human `--confirm`; **sandbox** to run |

A `FAIL` from the auditor **hard-blocks** regardless of reputation — it is never vaulted,
never injected. Trusted sources auto-vault on a *clean* audit; known/untrusted always
require `--confirm` and have any shipped code sandboxed.

## Components

- **Scripts:**
  - [`scripts/skill_ingest.py`](../../scripts/skill_ingest.py) — fetch → quarantine →
    classify → audit → vault, in one step.
  - [`scripts/security_auditor.py`](../../scripts/security_auditor.py) — static + LLM audit;
    `FAIL` blocks.
  - [`scripts/vetted_vault.py`](../../scripts/vetted_vault.py) — the approved registry +
    diff-audit update lifecycle.
  - [`scripts/container_runner.py`](../../scripts/container_runner.py) — sandboxed run of
    vaulted tools.
- **Skills:**
  [`skill-ingest`](../../skill-library/coordinator/skill-ingest/SKILL.md),
  [`security-auditor`](../../skill-library/coordinator/security-auditor/SKILL.md),
  [`vetted-vault`](../../skill-library/coordinator/vetted-vault/SKILL.md),
  [`container-runner`](../../skill-library/coordinator/container-runner/SKILL.md).
- **Config:** the `skill_ingest`, `security_auditor`, `vetted_vault`, and `container_runner`
  blocks in [`config.sample.yaml`](../../coordinator-core/config.sample.yaml).

## Guardrails (from SOUL.md)

- Never inject or run a downloaded source directly — always ingest → audit → vault → sandbox.
- Never vault/inject a `FAIL` source.
- Never execute a Tier 2/3 tool outside the sandbox; if no sandbox is available, do not fall
  back to host execution.
- Never fabricate/hand-author a skill and route it through the pipeline to manufacture
  trust — a vaulted skill must come from a real remote source with verifiable provenance.
  ([`test_fabrication_guard.py`](../../scripts/test_fabrication_guard.py) enforces this.)

## Relationship to dynamic tooling

[Dynamic tooling](../dynamic-tooling/README.md) is the discovery layer that *feeds* this
pipeline: it finds candidate skills, then hands each to ingest → audit → vault → sandbox
before injection. This capability is the gate; dynamic tooling is what knocks on it.
