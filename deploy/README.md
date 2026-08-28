# deploy

Run hermes-coder as an always-on background agent. This folder ships a **genericized macOS
LaunchAgent template** — no real paths or usernames, just placeholders you fill in.

> hermes-coder is normally hosted inside a larger agent process (the "gateway") that owns the
> messaging transport and runtime. This template launches that host process and points it at
> your hermes home dir. If you're adopting only the coordinator scripts, you may not need a
> long-running service at all — you can invoke the scripts directly. Use this when you want
> the agent always listening.

## The template

[`com.hermes-coder.agent.plist.template`](com.hermes-coder.agent.plist.template) uses these
placeholders:

| Placeholder | Meaning |
|-------------|---------|
| `{{USER}}` | Your macOS username |
| `{{HERMES_HOME}}` | The hermes-coder home dir (e.g. `/Users/{{USER}}/.hermes-coder`) |
| `{{AGENT_HOME}}` | The host agent install dir (working dir + venv root) |
| `{{PYTHON_BIN}}` | Absolute path to the agent's Python (e.g. `{{AGENT_HOME}}/venv/bin/python`) |
| `{{BIN_PATH}}` | The `PATH` the agent runs with (venv bin + node bin + system paths) |

## Install

1. Copy the template, substitute your values, and drop it in `~/Library/LaunchAgents/`:

   ```bash
   mkdir -p "$HOME/.hermes-coder/logs"
   sed \
     -e "s|{{USER}}|$USER|g" \
     -e "s|{{HERMES_HOME}}|$HOME/.hermes-coder|g" \
     -e "s|{{AGENT_HOME}}|$HOME/.hermes/hermes-agent|g" \
     -e "s|{{PYTHON_BIN}}|$HOME/.hermes/hermes-agent/venv/bin/python|g" \
     -e "s|{{BIN_PATH}}|$HOME/.hermes/hermes-agent/venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin|g" \
     deploy/com.hermes-coder.agent.plist.template \
     > "$HOME/Library/LaunchAgents/com.hermes-coder.agent.plist"
   ```

2. Load it:

   ```bash
   launchctl load "$HOME/Library/LaunchAgents/com.hermes-coder.agent.plist"
   ```

3. Verify and tail logs:

   ```bash
   launchctl list | grep hermes-coder
   tail -f "$HOME/.hermes-coder/logs/gateway.log"
   ```

To stop / reload:

```bash
launchctl unload "$HOME/Library/LaunchAgents/com.hermes-coder.agent.plist"
```

## Notes

- `RunAtLoad` + `KeepAlive` make it start at login and restart on crash.
- Secrets come from the environment (see
  [`../coordinator-core/.env.example`](../coordinator-core/.env.example)) — don't hardcode
  them in the plist.
- Scheduled jobs (nightly backlog triage, weekly grooming) are **not** auto-registered. Wire
  your own cron/launchd jobs deliberately if you want them.
