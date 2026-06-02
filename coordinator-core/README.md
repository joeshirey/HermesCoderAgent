# coordinator-core

The heart of hermes-coder: the coordinator's behavioral contract plus the two
configuration surfaces it reads.

## Files

| File | What it is |
|------|------------|
| [`SOUL.md`](SOUL.md) | The coordinator's operating contract — its principles, workflow, role lenses, and the hard "what I do NOT do" invariants. This is the single most important file in the repo. |
| [`config.sample.yaml`](config.sample.yaml) | A slim, sanitized sample of the coordinator-relevant config blocks. The live system embeds these in a larger host-agent `config.yaml`; only the coordinator slice is shipped here. |
| [`.env.example`](.env.example) | Placeholder environment variables. Copy to `.env` and fill in your own; never commit a real `.env`. |

## How they fit together

- **SOUL.md** is loaded as the coordinator's system prompt. It tells the model *how to
  behave*: plan first, delegate all coding to the active harness, review in two passes
  (spec + quality), vet third-party tools, humanize outward prose, deliver through the
  gated GitHub lifecycle, and never write code itself.
- **config.sample.yaml** tells the scripts *how to run*: which harness is default
  (`coding.default_engine`), triage tool budgets, autonomy levels, vault trust tiers,
  audit policy, and so on. Each block maps to a script in [`../scripts`](../scripts/) and
  is documented in the capability READMEs.
- **.env.example** holds the secrets the scripts and host agent read from the environment.
  GitHub auth is **not** here — authenticate with `gh auth login` so the lifecycle/backlog
  scripts inherit credentials.

## Adopting just the coordinator

The minimum viable adoption is: take `SOUL.md`, point it at one harness (see
[multi-harness](../capabilities/multi-harness/README.md)), and wire up the triage +
delivery scripts. Everything else (security pipeline, backlog, retrospective, etc.) layers
on top.

## A note on paths

`SOUL.md` references scripts as `~/.hermes-coder/scripts/...`. That `~/.hermes-coder` is the
**hermes home directory** on the live machine. When adopting, substitute your own hermes
home; the `~`/`$HOME`-relative form is intentional and portable.
