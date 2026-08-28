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

import os
import re
import subprocess
import sys
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


DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"


def resolve_gemini_model() -> str:
    """Model for opencode/Vertex support passes (config `coding.gemini_model`).
    Falls back to DEFAULT_GEMINI_MODEL when the key is unset."""
    return _read_coding_block().get("gemini_model", "").strip() or DEFAULT_GEMINI_MODEL


TIERS = ("fast", "standard", "elevated", "premium", "max")


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


def _configured_claude_models() -> set:
    """All claude model ids that appear in config (claude_model + every tier)."""
    blk = _read_coding_block()
    models = {blk.get("claude_model", "").strip()}
    models |= {blk.get(f"model_{t}", "").strip() for t in TIERS}
    return {m for m in models if m and not m.startswith("gemini")}


class UnknownModel(Exception):
    """An explicitly-requested model id is not in config coding.*."""


def sanitize_claude_model(model: str, strict: bool = False) -> str:
    """Reject claude model ids that don't come from config. Freehand ids are
    how a recent project dispatch failed three times in a row
    (claude-3-5-sonnet, claude-sonnet-4-5@20250929, ... -- none deployed);
    substituting the configured model keeps the dispatch on a known-good id.
    Empty stays empty (claude CLI default); gemini-* passes through untouched
    (routed to opencode, validated there).

    `strict` raises instead of substituting. Substitution is right for a
    hallucinated id but catastrophic for a deliberate A/B: a haiku reviewer
    would silently run as opus and "prove" haiku reviews as well as opus.
    Callers passing an explicit, intentional model id should set strict=True."""
    m = (model or "").strip()
    if not m or m.startswith("gemini"):
        return m
    known = _configured_claude_models()
    if m in known:
        return m
    if strict:
        raise UnknownModel(
            f"model '{m}' is not in config coding.* ({sorted(known)}); refusing to "
            f"substitute because it was requested explicitly")
    fallback = resolve_claude_model()
    print(f"harness_llm: unknown claude model '{m}' not in config coding.* "
          f"-- substituting '{fallback or '(claude CLI default)'}'", file=sys.stderr)
    return fallback


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
                     model: str = "", session_id: str = "",
                     sanitize: bool = True) -> list:
    """Build a list-form `claude -p` command. `tools` (if given) becomes
    --allowedTools after name-mapping; `model` (already resolved by the caller)
    becomes --model. Flag shape matches the prior per-script builders exactly.

    `session_id` pins the transcript filename (~/.claude/projects/<slug>/<id>.jsonl)
    so a dispatch can later be joined to its own token usage. Omitted by default,
    so production dispatches are unchanged."""
    cmd = ["claude", "-p", prompt]
    mapped = map_claude_tools(tools)
    if mapped:
        cmd += ["--allowedTools", mapped]
    if max_turns is not None:
        cmd += ["--max-turns", str(max_turns)]
    cmd += ["--dangerously-skip-permissions"]
    # sanitize=False means the caller chose this id deliberately (an A/B override).
    # Pass it through verbatim: if the id is bogus the CLI fails loudly, which is
    # far better than silently running a different model than the one recorded.
    model = sanitize_claude_model(model) if sanitize else (model or "").strip()
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--session-id", session_id]
    return cmd


def build_opencode_cmd(prompt: str, *, repo: str = "", model: str = "",
                       title: str = "", pure: Optional[bool] = None) -> list:
    """Build a list-form `opencode run` command.

    `title` names the session so it can be found afterward via
    `opencode session list` -- opencode has no caller-supplied session id, and
    picking the "most recent" session races concurrent runs. Deliberately does
    NOT set --format json: that turns stdout into a raw event stream and breaks
    the sentinel parsing the review passes rely on. Usage is read back with
    `opencode export` instead (see trial_ledger.harvest_opencode).

    `pure` adds --pure, which disables external plugins. This matters because
    the configured superpowers plugin turns opencode into a design-first agent
    that explores, asks clarifying questions and waits for approval instead of
    implementing (2026-07-29: a Gemini arm burned 111s and wrote nothing, then
    asked which approach to take). Comparing that to `claude -p` compares
    workflows, not models. None = read HERMES_OPENCODE_PURE, so production
    behaviour is unchanged unless explicitly opted in."""
    # Default ON. The configured superpowers plugin ships 19 skills with their
    # OWN commit/push gates and zero awareness of hermes's scripts, so an
    # unpure opencode run is governed by a second, conflicting gate system. It
    # also turns opencode into a design-first agent that asks for approval
    # instead of implementing. Opt back in per-call or with
    # HERMES_OPENCODE_PURE=0 if a run genuinely needs the plugins.
    if pure is None:
        pure = os.environ.get("HERMES_OPENCODE_PURE", "1") != "0"
    # Any model passes through -- Vertex serves Claude as well as Gemini, and the
    # harness-vs-provider de-confound arm runs claude-sonnet-5 through opencode.
    # Only an EMPTY model falls back to the Gemini default.
    m = (model or "").strip() or resolve_gemini_model()
    cmd = ["opencode", "run", prompt, "--dangerously-skip-permissions",
           "-m", m if "/" in m else f"google-vertex/{m}"]
    if pure:
        cmd += ["--pure"]
    if repo:
        cmd += ["--dir", repo]
    if title:
        cmd += ["--title", title]
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
               "-m", f"google-vertex/{model if model.startswith('gemini') else resolve_gemini_model()}"]
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
