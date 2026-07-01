#!/usr/bin/env python3
"""Shared LLM helper that routes text-in/text-out work through the active
coding harness (`claude -p`, `agy -p`, `opencode run`) instead of a local
Ollama model.

Why this exists: per the standing "no local models for now" directive, the
LLM-backed support passes (humanizer rewrite, complexity triage, retrospective
summaries, security audit, backlog grooming) run through whichever coding
harness the user selected, not gemma4 on localhost. The harness is NOT
hard-coded to claude -- it is resolved from the caller's `--engine`, then the
`coding.default_engine` config key, then a claude-code fallback.

Stdlib-only (no pip dependencies).
"""

import re
import subprocess
from pathlib import Path
from typing import Optional

ENGINES = ["claude-code", "antigravity", "opencode"]
DEFAULT_ENGINE = "claude-code"


class HarnessUnavailable(Exception):
    """Raised when the selected coding harness cannot produce output
    (missing binary, non-zero exit, timeout, or empty response).

    Callers map this to their existing degraded path -- the same place they
    previously caught OllamaConnectionError.
    """


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _read_coding_block() -> dict:
    """Parse the indented `coding:` block from the global config.yaml."""
    cfg = _config_path()
    result: dict = {}
    if not cfg.is_file():
        return result
    try:
        lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    in_block = False
    for line in lines:
        if not in_block:
            if re.match(r'^coding:\s*$', line):
                in_block = True
            continue
        if line.startswith((" ", "\t")):
            m = re.match(r'^\s+([A-Za-z0-9_]+):\s*(.*)$', line)
            if m:
                v = re.sub(r'\s+#.*$', '', m.group(2)).strip().strip('"\'')
                result[m.group(1)] = v
        elif line.strip():
            break  # dedent to a new top-level key ends the block
    return result


def resolve_engine(cli_engine: Optional[str] = None) -> str:
    """Pick the active harness: explicit CLI value, else config
    `coding.default_engine`, else claude-code. Accepts the bare alias
    "claude" as a synonym for "claude-code"."""
    if cli_engine:
        e = "claude-code" if cli_engine == "claude" else cli_engine
        if e in ENGINES:
            return e
    cfg = _read_coding_block().get("default_engine", "")
    cfg = "claude-code" if cfg == "claude" else cfg
    if cfg in ENGINES:
        return cfg
    return DEFAULT_ENGINE


def resolve_claude_model() -> str:
    """Model for claude-code dispatches (config `coding.claude_model`).
    Empty string = let the claude CLI use its own default."""
    return _read_coding_block().get("claude_model", "").strip()


TIERS = ("fast", "standard", "elevated", "premium")


def resolve_tier_model(tier: Optional[str]) -> str:
    """Model for a routing tier (config `coding.model_<tier>`). Falls back to
    the global claude_model when the tier key is unset or unknown."""
    if tier in TIERS:
        m = _read_coding_block().get(f"model_{tier}", "").strip()
        if m:
            return m
    return resolve_claude_model()


def _engine_for_model(model: str) -> str:
    """gemini-* models run via opencode (Vertex); everything else via claude CLI."""
    return "opencode" if model.startswith("gemini") else "claude-code"


# Canonical claude-code command builder + tool-name mapping, shared by the
# coordinator's list-form dispatchers (harness_llm text passes, final_review,
# pr_review_cycle) so --allowedTools naming and the flag shape live in ONE place.
# (auto_healer uses a shell-string builder for parallel_dispatch composition and
# is intentionally left separate.)
_CLAUDE_TOOL_MAP = {
    "read": "ReadFile", "write": "WriteFile", "edit": "EditFile",
    "bash": "Bash", "glob": "Glob", "grep": "Grep",
}


def map_claude_tools(tools: str) -> str:
    """Map canonical lowercase tool names to Claude Code's exact tool names.
    Unknown names pass through unchanged (so already-correct names are safe)."""
    out = []
    for part in (tools or "").split(","):
        p = part.strip()
        if p:
            out.append(_CLAUDE_TOOL_MAP.get(p.lower(), p))
    return ",".join(out)


def build_claude_cmd(prompt: str, *, tools: str = "", max_turns: Optional[int] = None,
                     model: str = "") -> list:
    """Build a list-form `claude -p` command. `tools` (if given) becomes
    --allowedTools after name-mapping; `model` (already resolved by the caller)
    becomes --model. Flag shape matches the prior per-script builders exactly."""
    cmd = ["claude", "-p", prompt]
    mapped = map_claude_tools(tools)
    if mapped:
        cmd += ["--allowedTools", mapped]
    if max_turns is not None:
        cmd += ["--max-turns", str(max_turns)]
    cmd += ["--dangerously-skip-permissions"]
    if model:
        cmd += ["--model", model]
    return cmd


def _build_cmd(prompt: str, engine: str, repo: Optional[str],
               model: str = "") -> list:
    """Build a list-form (no shell) command for a single text-in/text-out
    pass. No file-editing tools are granted; the prompt is self-contained."""
    if engine == "antigravity":
        cmd = ["agy", "-p", prompt,
               "--dangerously-skip-permissions",
               "--print-timeout", "3m0s"]
        if repo:
            cmd += ["--add-dir", repo]
        return cmd
    if engine == "opencode":
        cmd = ["opencode", "run", prompt,
               "--dangerously-skip-permissions",
               "-m", f"google-vertex/{model if model.startswith('gemini') else 'gemini-3.5-flash'}"]
        if repo:
            cmd += ["--dir", repo]
        return cmd
    # claude-code (default). --max-turns 2 is the hard safety valve; no
    # --allowedTools so it answers as plain text without wandering the FS.
    return build_claude_cmd(prompt, max_turns=2, model=model or resolve_claude_model())


def harness_generate(
    prompt: str,
    *,
    engine: Optional[str] = None,
    system: Optional[str] = None,
    repo: Optional[str] = None,
    timeout: int = 120,
    tier: Optional[str] = None,
) -> str:
    """Run one text-in/text-out pass through the resolved harness and return
    stdout. Raises HarnessUnavailable on any failure (missing binary, non-zero
    exit, timeout, or empty output). `system`, if given, is prepended to the
    prompt (CLI harnesses have no separate system channel).

    `tier` selects a routing tier from config (`coding.model_<tier>`); the
    model then picks its engine (gemini-* -> opencode, otherwise claude CLI).
    An explicit `engine` argument wins over tier-based engine selection."""
    model = resolve_tier_model(tier) if tier else ""
    if engine:
        eng = resolve_engine(engine)
    elif model:
        eng = _engine_for_model(model)
    else:
        eng = resolve_engine(None)
    full = prompt if not system else f"{system}\n\n{prompt}"
    cmd = _build_cmd(full, eng, repo, model=model)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        raise HarnessUnavailable(f"{eng}: {e}") from e
    if r.returncode != 0:
        raise HarnessUnavailable(
            f"{eng} exited {r.returncode}: {(r.stderr or '').strip()[:200]}"
        )
    out = (r.stdout or "").strip()
    if not out:
        raise HarnessUnavailable(f"{eng} produced no output")
    return out


def strip_fences(text: str) -> str:
    """Drop a single ``` code fence the harness may wrap its reply in."""
    t = text.strip()
    t = re.sub(r'^```[a-zA-Z0-9_-]*\n', '', t)
    t = re.sub(r'\n```\s*$', '', t)
    return t.strip()
