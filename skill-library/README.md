# skill-library

Curated `SKILL.md` files — the modular instruction units the coordinator loads to shape its
behavior and to drive the coding harness.

## What a SKILL.md is

A skill is a single Markdown file with YAML frontmatter (`name`, `description`, `version`,
`metadata`) followed by focused instructions. The coordinator loads a skill when its
`description` matches the task at hand. Skills keep behavior modular: instead of one giant
prompt, the coordinator pulls in exactly the guidance a given step needs (how to dispatch to
a harness, how to review for security, how to write a plan, etc.). Some skills carry a
`references/` folder with deeper case studies.

## Curation philosophy: don't dump everything

The live system has ~120 skills across many non-coding domains (media, smart-home, social,
research, …). Shipping all of them would bury the signal. This snapshot ships **only** the
~30 skills the coding coordinator actually uses, organized to mirror their live subpaths so
the cross-references inside each `SKILL.md` (e.g. `skills/coordinator/...`) still resolve.

If you adopt skills, follow the same discipline: curate to what your coordinator references,
keep paths consistent, and let the [security pipeline](../capabilities/security-pipeline/README.md)
gate anything third-party rather than hand-adding it.

## What's here

### `coordinator/` — the capability skills (14)

The per-capability operating instructions the coordinator runs: `auto-healing`,
`complexity-triage`, `container-runner`, `github-backlog`, `github-lifecycle`,
`humanizer-gate`, `local-model-router`, `parallel-dispatch`, `retrospective`,
`security-auditor`, `skill-discovery`, `skill-ingest`, `systematic-debugger`,
`vetted-vault`. Each pairs with a script in [`../scripts`](../scripts/) and is the home
linked from the matching capability README.

### `coding-team/` — the role lenses (7)

Perspectives the coordinator applies when planning/reviewing: `architect`, `devops`,
`docs`, `implementer`, `quality`, `reviewer`, `security`.

### `harness/` — the engine adapters (3)

Exact dispatch syntax per coding engine: `claude-code` (default), `antigravity`,
`opencode`. See [multi-harness](../capabilities/multi-harness/README.md).

### `software-development/` & `workflow/` — curated dev skills (6)

General practices the coordinator references: `plan`, `spike`, `systematic-debugging`,
`writing-plans`, `test-driven-development`, `requesting-code-review`.
