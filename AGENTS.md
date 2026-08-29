# HermesCoderAgent — Agent Context

## Project memory (hermes)

Facts captured from prior agent sessions in this repo. Verify against current code before relying on them.

- dispatch_coder.py/final_review.py background 'exited' notifications can fire while the underlying claude subprocess is still alive/orphaned (race condition) — verify with pgrep/ps before trusting a completion notification's log output, especially for long premium-tier dispatches.
- scripts/github_backlog.py create has no --labels flag — it classifies and applies standard labels (type/severity/effort/risk/impact/confidence/backlog) automatically; don't pass --labels.
- dispatch_coder.py: --tier alone doesn't suppress tier_randomized; use --model explicitly (e.g., --model claude-sonnet-5) to guarantee model choice.
- Entire skill library in this profile is user-owned (created_by=None) — patch/edit refused for every skill checked. Needs `hermes curator adopt <name>` first. Also: background dispatch "exited" signals (terminal/process wait) can fire while the actual PID/claude-p children are still running — verify with `ps -p <pid>` before trusting completion.
- Verify final-review/coding findings against actual git HEAD/diff before reporting; treat a 'fixed' verdict with 0 actual changes as blocked, not passed.
- Amending commits invalidates SHA-pinned receipts; re-run push gates on new HEAD even if code unchanged.
