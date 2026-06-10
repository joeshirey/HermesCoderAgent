#!/usr/bin/env python3
"""GitHub PR & CI lifecycle tool.

Delivers finished work: create branches, draft+humanize commit/PR messages,
push, open draft PRs via the gh CLI, and monitor GitHub Actions CI.

Remote-mutating actions (push, pr) respect a per-project autonomy setting.
Precedence: --autonomy flag > <repo>/.hermes-github.yaml > config.yaml github.autonomy
> hard default "gated". In "gated" mode push/pr require --confirm; the tool
otherwise returns an "awaiting_confirmation" preview without touching the remote.

This tool NEVER merges a PR. It alerts when CI is green and the PR is mergeable.

Usage:
    python3 github_lifecycle.py commit --repo /path --engine claude-code --branch feature/x
    python3 github_lifecycle.py push --repo /path --confirm
    python3 github_lifecycle.py pr --repo /path --engine claude-code --base main --confirm
    python3 github_lifecycle.py ci-status --repo /path --json
    python3 github_lifecycle.py ci-watch --repo /path --timeout 1800

Exit codes:
    0  Success (action done / CI green / ready for merge)
    1  Awaiting confirmation (gated action blocked) or local action failed
    2  Invalid arguments / nothing to do
    3  Infrastructure error (no gh, not authenticated, no remote, git error)
    4  CI failed or PR not mergeable
    5  CI still running at watch timeout
"""

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Import the humanizer gateway as a sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from humanizer_gateway import humanize
except ImportError:
    humanize = None
try:
    from harness_llm import resolve_claude_model
except ImportError:
    def resolve_claude_model() -> str:
        return ""


AUTONOMY_LEVELS = ["gated", "push-draft", "full"]
DEFAULT_AUTONOMY = "gated"
DIFF_LIMIT = 6000


@dataclass
class ActionResult:
    status: str  # done, awaiting_confirmation, failed, ci_pass, ci_fail,
                 # ci_running, not_mergeable, ready_for_merge, blocked
    action: str
    details: str = ""
    command_preview: list = field(default_factory=list)
    error: str = ""
    hygiene: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# -- subprocess wrappers --

def _run(args: list, repo: str, timeout: int = 30) -> tuple:
    """Run a command (list form, no shell). Returns (rc, stdout, stderr)."""
    try:
        r = subprocess.run(
            args, cwd=repo, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out: {' '.join(args)}"
    except OSError as e:
        return 127, "", str(e)


def _dispatch(cmd: str, repo: str, timeout: int = 300) -> str:
    """Run a harness dispatch (shell form) and return combined output."""
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout + "\n" + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return ""
    except OSError:
        return ""


# -- config resolution --

def _read_flat_yaml_value(path: Path, key: str) -> Optional[str]:
    """Read a top-level `key: value` from a flat YAML file."""
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        m = re.match(rf'^{re.escape(key)}:\s*(.*)$', line)
        if m:
            v = re.sub(r'\s+#.*$', '', m.group(1)).strip().strip('"\'')
            return v or None
    return None


def _read_global_github() -> dict:
    """Parse the indented `github:` block from the global config.yaml."""
    cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    result = {}
    if not cfg.is_file():
        return result
    try:
        lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    in_block = False
    for line in lines:
        if not in_block:
            if re.match(r'^github:\s*$', line):
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


def resolve_autonomy(repo: str, cli_flag: Optional[str]) -> str:
    if cli_flag in AUTONOMY_LEVELS:
        return cli_flag
    v = _read_flat_yaml_value(Path(repo) / ".hermes-github.yaml", "autonomy")
    if v in AUTONOMY_LEVELS:
        return v
    g = _read_global_github()
    if g.get("autonomy") in AUTONOMY_LEVELS:
        return g["autonomy"]
    return DEFAULT_AUTONOMY


def resolve_base(repo: str, cli_base: Optional[str]) -> str:
    if cli_base:
        return cli_base
    v = _read_flat_yaml_value(Path(repo) / ".hermes-github.yaml", "default_base")
    if v:
        return v
    g = _read_global_github()
    if g.get("default_base"):
        return g["default_base"]
    return "main"


def _ci_defaults() -> tuple:
    g = _read_global_github()
    try:
        poll = int(g.get("ci_poll_interval", 15))
    except (ValueError, TypeError):
        poll = 15
    try:
        wt = int(g.get("ci_watch_timeout", 1800))
    except (ValueError, TypeError):
        wt = 1800
    return poll, wt


# -- git/gh helpers --

def _preflight(repo: str, need_remote: bool = False,
               need_gh: bool = False) -> Optional[str]:
    rc, _, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if rc != 0:
        return "not a git repository"
    if need_remote:
        rc, _, _ = _run(["git", "remote", "get-url", "origin"], repo)
        if rc != 0:
            return "no 'origin' remote configured"
    if need_gh:
        rc, _, _ = _run(["gh", "--version"], repo)
        if rc != 0:
            return "gh CLI not installed"
        rc, _, _ = _run(["gh", "auth", "status"], repo)
        if rc != 0:
            return "gh CLI not authenticated (run: gh auth login)"
    return None


def _current_branch(repo: str) -> str:
    rc, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    return out if rc == 0 else ""


def _branch_exists(repo: str, branch: str) -> bool:
    rc, _, _ = _run(["git", "rev-parse", "--verify", "--quiet", branch], repo)
    return rc == 0


def _is_protected_branch(repo: str, branch: str) -> bool:
    """A branch the agent must never push to directly. Always covers main/master,
    plus the repo's configured default base. Feature work reaches the default
    branch only through a human-merged PR — never a direct push."""
    if branch in ("main", "master"):
        return True
    return branch == resolve_base(repo, None)


def _working_tree_dirty(repo: str) -> Optional[str]:
    """Return a short summary of any uncommitted or untracked files, or None if
    the working tree is clean. Used to block a push that would silently leave
    locally-created deliverables off the remote (the 'untracked files push leak')."""
    rc, out, _ = _run(["git", "status", "--porcelain"], repo)
    if rc != 0 or not out.strip():
        return None
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return f"{len(lines)} uncommitted/untracked file(s): " + ", ".join(
        ln[3:] for ln in lines[:8]) + ("…" if len(lines) > 8 else "")


# -- message drafting --

def build_readonly_dispatch(prompt: str, engine: str, repo: str) -> str:
    """Build a read-only dispatch command (drafting must not edit files)."""
    escaped = prompt.replace("'", "'\\''")
    model = resolve_claude_model()
    model_flag = f" --model {model}" if model else ""
    if engine == "claude-code":
        return (
            f"claude -p '{escaped}' "
            f"--allowedTools 'Read,Bash' "
            f"--max-turns 8 "
            f"--dangerously-skip-permissions{model_flag}"
        )
    elif engine == "antigravity":
        return (
            f"agy -p '{escaped}' "
            f"--dangerously-skip-permissions "
            f"--print-timeout 3m0s "
            f"--sandbox "
            f"--add-dir {repo}"
        )
    elif engine == "opencode":
        return (
            f"opencode run '{escaped}' "
            f"--dir {repo} "
            f"--dangerously-skip-permissions "
            f"-m google-vertex/gemini-3.5-flash"
        )
    return (
        f"claude -p '{escaped}' "
        f"--allowedTools 'Read,Bash' "
        f"--max-turns 8 "
        f"--dangerously-skip-permissions{model_flag}"
    )


def _extract_message(raw: str) -> str:
    """Strip code fences / surrounding noise from a drafted message."""
    t = raw.strip()
    t = re.sub(r'^```[a-zA-Z]*\n', '', t)
    t = re.sub(r'\n```\s*$', '', t)
    return t.strip()


def _strip_coauthor(msg: str) -> str:
    """Remove any Co-Authored-By trailer (SOUL.md rule: author is the repository owner only)."""
    kept = [
        ln for ln in msg.splitlines()
        if not re.match(r'(?i)^\s*co-authored-by:', ln)
    ]
    return "\n".join(kept).strip()


def _fallback_commit_message(repo: str) -> str:
    """Deterministic message when no harness/draft is available."""
    rc, stat, _ = _run(["git", "diff", "--staged", "--stat"], repo)
    rc2, files, _ = _run(["git", "diff", "--staged", "--name-only"], repo)
    names = [f for f in files.splitlines() if f.strip()]
    if len(names) == 1:
        subject = f"Update {names[0]}"
    elif names:
        subject = f"Update {len(names)} files"
    else:
        subject = "Update files"
    body = stat.strip()
    return f"{subject}\n\n{body}".strip() if body else subject


def _humanize_text(text: str, artifact_type: str, repo: str) -> str:
    """Run text through the humanizer; tolerate harness-down (rules-only)."""
    if humanize is None:
        return text
    try:
        filtered, _passes, _code = humanize(
            text=text, artifact_type=artifact_type, repo_dir=repo
        )
        return filtered if filtered.strip() else text
    except Exception:
        return text


def _draft_commit_message(repo: str, engine: str) -> str:
    rc, diff, _ = _run(["git", "diff", "--staged"], repo)
    if not diff.strip():
        return ""
    prompt = (
        "Write a git commit message for the following staged diff.\n"
        "Format: a concise one-line subject (max ~70 chars, imperative mood), "
        "then a blank line, then 1-3 short bullets explaining the why.\n"
        "Output ONLY the commit message text, nothing else.\n"
        "Do NOT include any Co-Authored-By trailer or attribution.\n\n"
        f"Diff (truncated):\n{diff[:DIFF_LIMIT]}"
    )
    out = _dispatch(build_readonly_dispatch(prompt, engine, repo), repo)
    return _extract_message(out)


def _draft_pr_body(repo: str, engine: str, base: str) -> str:
    rc, log, _ = _run(
        ["git", "log", f"{base}..HEAD", "--format=%s%n%b"], repo
    )
    rc2, stat, _ = _run(["git", "diff", "--stat", f"{base}...HEAD"], repo)
    context = (log + "\n\nChanged files:\n" + stat).strip()[:DIFF_LIMIT]
    if not context:
        return ""
    prompt = (
        "Write a GitHub pull request description for the following commits.\n"
        "Use two sections: '## Summary' (2-4 bullets on what and why) and "
        "'## Test plan' (a short checklist of how to verify).\n"
        "Output ONLY the PR body markdown, nothing else.\n\n"
        f"Commits and changes:\n{context}"
    )
    out = _dispatch(build_readonly_dispatch(prompt, engine, repo), repo)
    return _extract_message(out)


def _pr_title(repo: str, base: str) -> str:
    rc, out, _ = _run(["git", "log", "-1", "--format=%s"], repo)
    return out.strip() or "Update"


# Branch-name -> issue-number inference, conservative to avoid false positives
# (a branch like "add-oauth2-login" must NOT resolve to issue 2). Tried in order:
# explicit "issue-42" / "gh-42", then a numeric leading segment "42-..." or
# ".../42-...". A bare embedded digit is never matched.
_ISSUE_PATTERNS = (
    re.compile(r"(?:issue|gh)[-_/]?(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|/)(\d+)(?:[-_/]|$)"),
)


def _infer_issue_from_branch(branch: str) -> Optional[int]:
    if not branch:
        return None
    for pat in _ISSUE_PATTERNS:
        m = pat.search(branch)
        if m:
            return int(m.group(1))
    return None


def _resolve_issue_number(args, repo: str) -> Optional[int]:
    """Explicit --issue wins; otherwise infer from the current branch name."""
    explicit = getattr(args, "issue", None)
    if explicit is not None:
        return explicit if explicit > 0 else None
    return _infer_issue_from_branch(_current_branch(repo))


def _append_closing_keyword(body: str, issue: Optional[int]) -> str:
    """Append 'Closes #N' so GitHub auto-closes the issue when the PR merges.

    Added AFTER humanization so the keyword is never reworded/stripped. Skipped
    when the body already references closing that issue."""
    if not issue:
        return body
    if re.search(rf"\b(clos|fix|resolv)\w*\s+#{issue}\b", body, re.IGNORECASE):
        return body
    line = f"Closes #{issue}"
    return f"{body.rstrip()}\n\n{line}" if body.strip() else line


# -- CI helpers --

def _summarize_checks(rollup: list) -> str:
    """Reduce a statusCheckRollup to: pass / fail / running / none."""
    if not rollup:
        return "none"
    any_running = False
    any_fail = False
    for c in rollup:
        status = c.get("status")
        conclusion = c.get("conclusion")
        state = c.get("state")
        if status in ("QUEUED", "IN_PROGRESS", "PENDING", "WAITING") or state == "PENDING":
            any_running = True
        if conclusion in ("FAILURE", "TIMED_OUT", "CANCELLED",
                          "ACTION_REQUIRED", "STARTUP_FAILURE") or state in ("FAILURE", "ERROR"):
            any_fail = True
    if any_fail:
        return "fail"
    if any_running:
        return "running"
    return "pass"


def _pr_state(repo: str, branch: str) -> tuple:
    """Return (ok, summary, mergeable, url, error)."""
    ref = branch or _current_branch(repo)
    rc, out, err = _run(
        ["gh", "pr", "view", ref, "--json",
         "state,mergeable,statusCheckRollup,url"],
        repo, timeout=30,
    )
    if rc != 0:
        return False, "none", "UNKNOWN", "", (err or "no PR found for this branch")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return False, "none", "UNKNOWN", "", "could not parse gh output"
    summary = _summarize_checks(data.get("statusCheckRollup") or [])
    return True, summary, data.get("mergeable", "UNKNOWN"), data.get("url", ""), ""


# -- subcommand handlers --

# -- commit hygiene --
#
# A safety net run before every commit: catch secrets and build/dependency junk
# that should never be committed, flag a missing .gitignore, and scan staged file
# content for hardcoded absolute machine/home paths. Secrets BLOCK the commit
# (overridable with --skip-hygiene for the rare false positive); junk, a missing
# .gitignore, and non-portable machine paths only WARN (the commit proceeds).
# This is the gate that was missing when a fresh project's first commit went out
# with no hygiene check (it shipped a Makefile full of /Users/<name>/go/bin paths).

# High-confidence secret material -> block.
_SECRET_BASENAMES = {
    ".env", ".env.local", ".env.development", ".env.production", ".env.staging",
    "credentials.json", "service-account.json", "serviceaccount.json",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
# Never flag these even though they match a pattern above (templates / public keys).
_SECRET_ALLOW = (".env.example", ".env.sample", ".env.template", ".env.dist")

# Build output / dependency dirs / editor cruft -> warn.
_JUNK_DIR_SEGMENTS = {
    "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    ".venv", "venv", ".next", ".nuxt", "coverage", ".pytest_cache", ".mypy_cache",
}
_JUNK_BASENAMES = {".DS_Store", "Thumbs.db"}
_JUNK_SUFFIXES = (".pyc", ".pyo", ".class", ".log", ".tmp", ".swp")


def _classify_path(rel: str):
    """Return ('block'|'warn', reason, suggested_gitignore_line) or None."""
    parts = rel.split("/")
    base = parts[-1]
    low = rel.lower()

    if not any(low.endswith(a) for a in _SECRET_ALLOW):
        if base in _SECRET_BASENAMES:
            return "block", f"looks like a secret/credential file ({base})", base
        if base.endswith(_SECRET_SUFFIXES) and not base.endswith(".pub"):
            return "block", "looks like a private key/certificate", f"*{Path(base).suffix}"

    for seg in parts[:-1]:
        if seg in _JUNK_DIR_SEGMENTS:
            return "warn", f"build/dependency directory ({seg}/)", f"{seg}/"
    if base in _JUNK_BASENAMES:
        return "warn", "editor/OS cruft", base
    if base.endswith(_JUNK_SUFFIXES):
        return "warn", "build/temporary artifact", f"*{Path(base).suffix}"
    return None


# Hardcoded absolute machine/home paths baked into committed source are not
# portable (they break on any other machine and leak a username). They WARN: the
# commit proceeds, but the path should become ~, $HOME, or a tool-resolved path
# (e.g. $(go env GOPATH)/bin). Tilde and $HOME paths are portable and not flagged.
_MACHINE_PATH_RE = re.compile(
    r"/(?:Users|home)/[A-Za-z0-9._-]+/[^\s\"':]+"   # macOS / Linux home paths
    r"|[A-Za-z]:[\\/]Users[\\/][^\s\"'<>|]+"        # Windows C:\Users\name\...
)
# Generated/lock files often embed local cache paths legitimately — don't scan.
_LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum", "cargo.lock",
    "poetry.lock", "composer.lock", "gemfile.lock",
}
# Binary-ish extensions to skip outright (null-byte check catches the rest).
_CONTENT_SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wasm", ".so", ".dylib",
    ".class", ".jar", ".pyc",
)
_CONTENT_SCAN_MAX_BYTES = 512 * 1024


def _should_scan_content(rel: str) -> bool:
    parts = rel.split("/")
    base = parts[-1].lower()
    if base in _LOCKFILES or base.endswith(_CONTENT_SKIP_SUFFIXES):
        return False
    return not any(seg in _JUNK_DIR_SEGMENTS for seg in parts[:-1])


def _scan_content(repo: str, staged: list) -> list:
    """Scan staged text files for hardcoded absolute machine/home paths.

    Reads the working-tree copy (what's about to be committed); skips binary,
    oversized, generated/lock, and vendored files. Returns warn issues only."""
    issues = []
    seen = set()
    for rel in staged:
        if not _should_scan_content(rel):
            continue
        fpath = Path(repo) / rel
        if not fpath.is_file():
            continue
        try:
            if fpath.stat().st_size > _CONTENT_SCAN_MAX_BYTES:
                continue
            raw = fpath.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:                      # binary
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            m = _MACHINE_PATH_RE.search(line)
            if not m:
                continue
            snippet = m.group(0)
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            key = (rel, snippet)
            if key in seen:
                continue
            seen.add(key)
            issues.append({
                "severity": "warn",
                "path": f"{rel}:{lineno}",
                "reason": (f"hardcoded absolute machine path '{snippet}' — use ~, "
                           "$HOME, or a tool-resolved path so it works elsewhere"),
            })
    return issues


def _hygiene_check(repo: str, staged: list) -> dict:
    """Inspect staged paths for secrets/junk and a missing .gitignore.

    Returns {issues:[{severity,path,reason}], suggested_gitignore:[...],
    has_block:bool, gitignore_present:bool}."""
    issues = []
    suggestions = []
    for rel in staged:
        verdict = _classify_path(rel)
        if not verdict:
            continue
        sev, reason, ignore_line = verdict
        issues.append({"severity": sev, "path": rel, "reason": reason})
        if ignore_line and ignore_line not in suggestions:
            suggestions.append(ignore_line)

    issues.extend(_scan_content(repo, staged))

    gitignore_present = (Path(repo) / ".gitignore").is_file()
    if not gitignore_present:
        issues.append({"severity": "warn", "path": ".gitignore",
                       "reason": "no .gitignore in the repo — add one for this stack "
                                 "before committing"})
    return {
        "issues": issues,
        "suggested_gitignore": suggestions,
        "has_block": any(i["severity"] == "block" for i in issues),
        "gitignore_present": gitignore_present,
    }


def _staged_files(repo: str) -> list:
    rc, out, _ = _run(["git", "diff", "--staged", "--name-only"], repo)
    return [l for l in out.splitlines() if l.strip()] if rc == 0 else []


def cmd_commit(args, repo: str) -> tuple:
    err = _preflight(repo)
    if err:
        return ActionResult("failed", "commit", error=err), 3

    if args.branch:
        if _branch_exists(repo, args.branch):
            rc, _, e = _run(["git", "checkout", args.branch], repo)
        else:
            rc, _, e = _run(["git", "checkout", "-b", args.branch], repo)
        if rc != 0:
            return ActionResult("failed", "commit", error=f"branch switch failed: {e}"), 3

    if args.paths:
        rc, _, e = _run(["git", "add", "--"] + args.paths, repo)
    else:
        rc, _, e = _run(["git", "add", "-A"], repo)
    if rc != 0:
        return ActionResult("failed", "commit", error=f"git add failed: {e}"), 3

    rc, _, _ = _run(["git", "diff", "--staged", "--quiet"], repo)
    if rc == 0:
        return ActionResult("failed", "commit", error="nothing staged to commit"), 2

    # Hygiene gate: block secrets/junk before they're committed (and pushed).
    hygiene = _hygiene_check(repo, _staged_files(repo))
    if hygiene["has_block"] and not args.skip_hygiene:
        blockers = [i for i in hygiene["issues"] if i["severity"] == "block"]
        lines = "; ".join(f"{i['path']} ({i['reason']})" for i in blockers)
        suggest = (" Suggested .gitignore: " + ", ".join(hygiene["suggested_gitignore"])
                   if hygiene["suggested_gitignore"] else "")
        return ActionResult(
            "blocked", "commit",
            details=(f"Commit blocked — these staged files look like secrets/credentials "
                     f"and must not be committed: {lines}.{suggest} "
                     "Remove them (git rm --cached + add to .gitignore), or re-run with "
                     "--skip-hygiene if this is a deliberate false positive."),
            command_preview=[
                "python3 github_lifecycle.py commit ... --skip-hygiene  # override"],
            hygiene=hygiene,
        ), 1

    message = args.message or _draft_commit_message(repo, args.engine)
    if not message.strip():
        message = _fallback_commit_message(repo)
    message = _humanize_text(message, "commit", repo)
    message = _strip_coauthor(message)
    if not message.strip():
        message = _fallback_commit_message(repo)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(message)
        tmp.close()
        rc, _, e = _run(["git", "commit", "-F", tmp.name], repo, timeout=60)
    finally:
        os.unlink(tmp.name)

    if rc != 0:
        return ActionResult("failed", "commit", error=f"git commit failed: {e}"), 3

    _, sha, _ = _run(["git", "rev-parse", "--short", "HEAD"], repo)
    branch = _current_branch(repo)
    subject = message.splitlines()[0] if message else ""
    warns = [i for i in hygiene["issues"] if i["severity"] == "warn"]
    detail = f"committed {sha} on {branch}: {subject}"
    if warns:
        detail += " | hygiene warnings: " + "; ".join(
            f"{i['path']} ({i['reason']})" for i in warns)
    return ActionResult("done", "commit", details=detail, hygiene=hygiene), 0


def cmd_push(args, repo: str) -> tuple:
    err = _preflight(repo, need_remote=True)
    if err:
        return ActionResult("failed", "push", error=err), 3

    autonomy = resolve_autonomy(repo, args.autonomy)
    branch = _current_branch(repo)
    force_str = " --force-with-lease" if getattr(args, "force", False) else ""
    preview = [f"git push{force_str} -u origin {branch}"]

    # Protected-branch guard. Pushing the default branch directly bypasses code
    # review entirely; the only way it should advance is a human-merged PR. Hard-
    # block unless the user deliberately passes --allow-protected (which STILL has
    # to clear the autonomy gate below).
    if _is_protected_branch(repo, branch) and not getattr(args, "allow_protected", False):
        return ActionResult(
            "blocked", "push",
            error=(f"Refusing to push directly to protected branch '{branch}'. "
                   "Move this work onto a feature branch and open a PR; the default "
                   "branch should only advance via a human-merged PR. If you truly "
                   "intend a direct push, re-run with --allow-protected (it still "
                   "requires --confirm when autonomy is gated)."),
        ), 1

    # Full-commit guard. A push with a dirty tree silently leaves locally-created
    # files (deploy scripts, generated docs, config) off the remote. Commit first.
    dirty = _working_tree_dirty(repo)
    if dirty:
        return ActionResult(
            "blocked", "push",
            error=(f"Working tree is not clean — {dirty}. Commit (or stash) every "
                   "intended change before pushing so nothing is left off the remote."),
        ), 1

    if autonomy == "gated" and not args.confirm:
        return ActionResult(
            "awaiting_confirmation", "push",
            details="Project autonomy is 'gated'. Re-run with --confirm to push, "
                    "or set autonomy to push-draft/full for this project.",
            command_preview=preview,
        ), 1

    force_flag = ["--force-with-lease"] if getattr(args, "force", False) else []
    rc, out, e = _run(["git", "push"] + force_flag + ["-u", "origin", branch], repo, timeout=120)
    if rc != 0:
        return ActionResult("failed", "push", error=f"push failed: {e or out}"), 1
    return ActionResult("done", "push", details=f"pushed {branch} to origin"), 0


def _read_note(args) -> str:
    """Read the optional final-review note from --note or --note-file. The text is
    already humanized prose from the review agent, so it is appended verbatim."""
    note = (getattr(args, "note", None) or "").strip()
    if note:
        return note
    note_file = getattr(args, "note_file", None)
    if note_file:
        try:
            return Path(note_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def cmd_pr(args, repo: str) -> tuple:
    err = _preflight(repo, need_remote=True, need_gh=True)
    if err:
        return ActionResult("failed", "pr", error=err), 3

    autonomy = resolve_autonomy(repo, args.autonomy)
    base = resolve_base(repo, args.base)
    title = args.title or _pr_title(repo, base)
    body = _draft_pr_body(repo, args.engine, base)
    body = _humanize_text(body, "pr", repo) if body else ""
    # Append the final-review "what I fixed" note (already humanized by the review
    # agent) under its own heading, before the closing keyword.
    note = _read_note(args)
    if note:
        section = f"### Final review fixes\n\n{note}"
        body = f"{body.rstrip()}\n\n{section}" if body.strip() else section
    # Link the issue so GitHub closes it when the human merges (we never auto-merge).
    issue = _resolve_issue_number(args, repo)
    body = _append_closing_keyword(body, issue)

    # Draft unless autonomy is 'full' and --ready was requested.
    draft = not (autonomy == "full" and args.ready)
    preview_cmd = (
        f"gh pr create --base {base} --title '{title}'"
        f"{' --draft' if draft else ''} --body-file <generated>"
        f"{f' (body: Closes #{issue})' if issue else ''}"
        f"{' (+ final-review note)' if note else ''}"
    )

    if autonomy == "gated" and not args.confirm:
        return ActionResult(
            "awaiting_confirmation", "pr",
            details="Project autonomy is 'gated'. Re-run with --confirm to open the PR, "
                    "or set autonomy to push-draft/full for this project.",
            command_preview=[preview_cmd],
        ), 1

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(body or title)
        tmp.close()
        gh_args = [
            "gh", "pr", "create",
            "--base", base,
            "--title", title,
            "--body-file", tmp.name,
        ]
        if draft:
            gh_args.append("--draft")
        rc, out, e = _run(gh_args, repo, timeout=120)
    finally:
        os.unlink(tmp.name)

    if rc != 0:
        return ActionResult("failed", "pr", error=f"gh pr create failed: {e or out}"), 1
    url = out.splitlines()[-1] if out else ""
    kind = "draft PR" if draft else "PR"
    closes = f" (Closes #{issue} on merge)" if issue else ""
    return ActionResult("done", "pr", details=f"opened {kind}: {url}{closes}"), 0


def cmd_ci_status(args, repo: str) -> tuple:
    err = _preflight(repo, need_remote=True, need_gh=True)
    if err:
        return ActionResult("failed", "ci-status", error=err), 3

    ok, summary, mergeable, url, e = _pr_state(repo, args.branch)
    if not ok:
        return ActionResult("failed", "ci-status", error=e), 3

    if summary == "fail":
        return ActionResult("ci_fail", "ci-status",
                            details=f"CI failing ({url})"), 4
    if summary == "running":
        return ActionResult("ci_running", "ci-status",
                            details=f"CI in progress ({url})"), 5
    # pass or no checks
    note = "no checks configured" if summary == "none" else "CI passing"
    if mergeable == "MERGEABLE":
        return ActionResult("ready_for_merge", "ci-status",
                            details=f"{note}; PR is mergeable ({url})"), 0
    if mergeable == "CONFLICTING":
        return ActionResult("not_mergeable", "ci-status",
                            details=f"{note} but PR has conflicts ({url})"), 4
    return ActionResult("ci_pass", "ci-status",
                        details=f"{note}; mergeable status unknown ({url})"), 0


def cmd_ci_watch(args, repo: str) -> tuple:
    err = _preflight(repo, need_remote=True, need_gh=True)
    if err:
        return ActionResult("failed", "ci-watch", error=err), 3

    poll_default, watch_default = _ci_defaults()
    poll = args.poll_interval or poll_default
    deadline = time.monotonic() + (args.timeout or watch_default)

    last = None
    while True:
        ok, summary, mergeable, url, e = _pr_state(repo, args.branch)
        if not ok:
            return ActionResult("failed", "ci-watch", error=e), 3
        last = (summary, mergeable, url)

        if summary == "fail":
            return ActionResult("ci_fail", "ci-watch",
                                details=f"CI failed ({url})"), 4
        if summary in ("pass", "none"):
            note = "no checks configured" if summary == "none" else "CI passed"
            if mergeable == "MERGEABLE":
                return ActionResult("ready_for_merge", "ci-watch",
                                    details=f"{note}; PR is mergeable — ready for your review/merge ({url})"), 0
            if mergeable == "CONFLICTING":
                return ActionResult("not_mergeable", "ci-watch",
                                    details=f"{note} but PR has conflicts ({url})"), 4
            return ActionResult("ci_pass", "ci-watch",
                                details=f"{note}; mergeable status unknown ({url})"), 0

        if time.monotonic() >= deadline:
            url = last[2] if last else ""
            return ActionResult("ci_running", "ci-watch",
                                details=f"CI still running at watch timeout ({url})"), 5
        time.sleep(poll)


# -- output + CLI --

def _emit(result: ActionResult, as_json: bool):
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    line = f"{result.status.upper()}: {result.action}"
    if result.details:
        line += f" — {result.details}"
    print(line)
    if result.command_preview:
        print("Would run:")
        for c in result.command_preview:
            print(f"  {c}")
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)


HANDLERS = {
    "commit": cmd_commit,
    "push": cmd_push,
    "pr": cmd_pr,
    "ci-status": cmd_ci_status,
    "ci-watch": cmd_ci_watch,
}


def main():
    parser = argparse.ArgumentParser(description="GitHub PR & CI lifecycle tool")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, help="Project repository path")
    common.add_argument("--engine",
                        choices=["claude-code", "antigravity", "opencode"],
                        default="claude-code",
                        help="Active coding engine harness (for message drafting)")
    common.add_argument("--autonomy", choices=AUTONOMY_LEVELS, default=None,
                        help="Override the project's autonomy level")
    common.add_argument("--json", action="store_true", help="Output as JSON")

    p_commit = sub.add_parser("commit", parents=[common],
                              help="Branch, stage, draft+humanize message, commit (local)")
    p_commit.add_argument("--branch", help="Create/switch to this branch first")
    p_commit.add_argument("--paths", nargs="*", help="Stage only these paths (default: all)")
    p_commit.add_argument("--message", help="Use this message instead of drafting from diff")
    p_commit.add_argument("--skip-hygiene", action="store_true",
                          help="Bypass the secret/junk pre-commit hygiene gate (use only "
                               "for a deliberate false positive)")

    p_push = sub.add_parser("push", parents=[common], help="Push current branch (gated)")
    p_push.add_argument("--confirm", action="store_true",
                        help="Confirm the remote push when autonomy is gated")
    p_push.add_argument("--allow-protected", action="store_true",
                        help="Permit pushing the default/protected branch (main/master). "
                             "Off by default; still requires --confirm when autonomy is "
                             "gated. Use only after explicit user approval.")
    p_push.add_argument("--force", action="store_true",
                        help="Force push with lease (for rebased feature branches)")

    p_pr = sub.add_parser("pr", parents=[common], help="Open a (draft) PR (gated)")
    p_pr.add_argument("--base", help="Base branch (default: project/main)")
    p_pr.add_argument("--title", help="PR title (default: latest commit subject)")
    p_pr.add_argument("--confirm", action="store_true",
                      help="Confirm PR creation when autonomy is gated")
    p_pr.add_argument("--ready", action="store_true",
                      help="Open as ready-for-review (only honored at autonomy=full)")
    p_pr.add_argument("--note", default=None,
                      help="Final-review fixes note appended to the PR body under a "
                           "'### Final review fixes' heading (already-humanized prose)")
    p_pr.add_argument("--note-file", default=None,
                      help="Path to a file whose contents are used as --note")
    p_pr.add_argument("--issue", type=int, default=None,
                      help="Issue number this PR resolves; adds 'Closes #N' to the body so "
                           "GitHub closes it on merge (default: inferred from branch name)")

    p_cs = sub.add_parser("ci-status", parents=[common], help="One-shot CI status")
    p_cs.add_argument("--branch", help="Branch/PR to check (default: current)")

    p_cw = sub.add_parser("ci-watch", parents=[common],
                          help="Block until CI finishes or timeout")
    p_cw.add_argument("--branch", help="Branch/PR to watch (default: current)")
    p_cw.add_argument("--poll-interval", type=int, default=None,
                      help="Seconds between polls")
    p_cw.add_argument("--timeout", type=int, default=None,
                      help="Max seconds to watch")

    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"Error: repository path does not exist: {repo}", file=sys.stderr)
        sys.exit(2)

    result, code = HANDLERS[args.command](args, repo)
    _emit(result, args.json)
    sys.exit(code)


if __name__ == "__main__":
    main()
