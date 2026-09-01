#!/usr/bin/env python3
"""Shared review-receipt store — the final-review -> push chokepoint.

`final_review.py` records a receipt on a pass/fixed verdict; `github_lifecycle.py`
push refuses unless a fresh receipt authorizes the current HEAD. This turns the
SOUL "always run the final-review gate before push" instruction into a mechanical
block: a coordinator that skips review, or tries to push past a `blocked` verdict,
cannot push through the github-lifecycle tool.

Acceptance (push HEAD authorized) when a pass/fixed receipt either:
  1. matches the current HEAD sha exactly (no fixes after review), OR
  2. was written < 30 min ago with its reviewed HEAD an ancestor of the current
     HEAD *and at most MAX_UNREVIEWED_COMMITS commit(s) ahead* (the
     fix-pass-then-commit path: review edits the tree, the coordinator commits,
     HEAD advances by the single fix commit). The commit-count bound stops the
     grace window from authorizing arbitrary unreviewed commits stacked on a
     reviewed base within 30 minutes — those need their own review.

Instance-local, stdlib-only. Receipts live in state/review-receipts/<sha>.json.
Threat model: a confused/forgetful coordinator skipping the gate — not an
adversary forging receipts (an agent with shell could delete/forge files). This
is a guardrail, not a cryptographic control.
"""

import json
import subprocess
import time
from pathlib import Path

HERMES_HOME = Path(__file__).resolve().parent.parent
RECEIPTS_DIR = HERMES_HOME / "state" / "review-receipts"
FRESH_WINDOW_SECS = 30 * 60          # grace for fix-then-commit
PRUNE_AFTER_SECS = 7 * 86400
OK_VERDICTS = ("pass", "fixed")
MAX_UNREVIEWED_COMMITS = 1           # fix-then-commit adds exactly one commit


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _abs(repo):
    try:
        return str(Path(repo).resolve())
    except OSError:
        return str(repo)


def head_sha(repo):
    return _git(repo, "rev-parse", "HEAD")


def _branch(repo):
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _is_ancestor(repo, a, b):
    if not a or not b:
        return False
    try:
        r = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _commits_between(repo, a, b):
    """Count commits in a..b (reachable from b but not a). -1 on error."""
    if not a or not b:
        return -1
    out = _git(repo, "rev-list", "--count", f"{a}..{b}")
    try:
        return int(out)
    except (TypeError, ValueError):
        return -1


def _prune(now):
    if not RECEIPTS_DIR.is_dir():
        return
    for f in RECEIPTS_DIR.glob("*.json"):
        try:
            if now - f.stat().st_mtime > PRUNE_AFTER_SECS:
                f.unlink()
        except OSError:
            pass


def record(repo, verdict, depth=""):
    """Called by final_review on a pass/fixed verdict. Best-effort."""
    if verdict not in OK_VERDICTS:
        return None
    sha = head_sha(repo)
    if not sha:
        return None
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rec = {"repo": _abs(repo), "branch": _branch(repo), "reviewed_head": sha,
           "verdict": verdict, "depth": depth, "ts": now}
    try:
        (RECEIPTS_DIR / f"{sha}.json").write_text(json.dumps(rec))
    except OSError:
        return None
    _prune(now)
    return rec


def latest_verdict(repo, window_secs=6 * 3600):
    """Most recent pass/fixed verdict for repo's current branch, or "".

    Lets a downstream gate condition on HOW the pre-push review went: a `pass`
    means five premium lenses found nothing, so a second full review's novel
    findings are the ~17%-real case; a `fixed` means defects were found and the
    tree was edited, which is a materially higher-risk change.
    """
    repo_abs = _abs(repo)
    br = _branch(repo)
    now = time.time()
    best = None
    if RECEIPTS_DIR.is_dir():
        for f in RECEIPTS_DIR.glob("*.json"):
            try:
                r = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if r.get("repo") != repo_abs or r.get("verdict") not in OK_VERDICTS:
                continue
            if br and r.get("branch") != br:
                continue
            if now - r.get("ts", 0) > window_secs:
                continue
            if not best or r["ts"] > best["ts"]:
                best = r
    return (best or {}).get("verdict", "")


def recent_ok_count(repo, window_secs=6 * 3600):
    """Count pass/fixed receipts for repo's current branch within window_secs.

    Convergence signal for final_review's churn cap: N ok-verdicts on the same
    branch in a few hours means the gate keeps authorizing delivery and the
    coordinator keeps reviewing instead of delivering (2026-07-15 Epic D
    incident: 10 full-depth rounds in one day, no PR opened).
    """
    repo_abs = _abs(repo)
    br = _branch(repo)
    now = time.time()
    n = 0
    if RECEIPTS_DIR.is_dir():
        for f in RECEIPTS_DIR.glob("*.json"):
            try:
                r = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if r.get("repo") != repo_abs or r.get("verdict") not in OK_VERDICTS:
                continue
            if br and r.get("branch") != br:
                continue
            if now - r.get("ts", 0) <= window_secs:
                n += 1
    return n


def verify(repo):
    """Return (ok: bool, detail: str) for pushing repo's current HEAD."""
    sha = head_sha(repo)
    if not sha:
        return (False, "could not resolve HEAD")
    repo_abs = _abs(repo)

    exact = RECEIPTS_DIR / f"{sha}.json"
    if exact.is_file():
        try:
            r = json.loads(exact.read_text())
            if r.get("repo") == repo_abs and r.get("verdict") in OK_VERDICTS:
                return (True, f"final-review {r['verdict']} for HEAD {sha[:8]}")
        except (OSError, ValueError):
            pass

    now = time.time()
    best = None
    if RECEIPTS_DIR.is_dir():
        for f in RECEIPTS_DIR.glob("*.json"):
            try:
                r = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if r.get("repo") != repo_abs or r.get("verdict") not in OK_VERDICTS:
                continue
            if now - r.get("ts", 0) > FRESH_WINDOW_SECS:
                continue
            reviewed = r.get("reviewed_head", "")
            if _is_ancestor(repo, reviewed, sha):
                # Bound how far HEAD may have advanced past the reviewed commit,
                # so the grace window can't wave through unreviewed commits piled
                # on top of a reviewed base.
                ahead = _commits_between(repo, reviewed, sha)
                if ahead < 0 or ahead > MAX_UNREVIEWED_COMMITS:
                    continue
                if not best or r["ts"] > best["ts"]:
                    best = r
    if best:
        mins = int((now - best["ts"]) // 60)
        return (True, f"final-review {best['verdict']} {mins}m ago "
                      f"(reviewed {best['reviewed_head'][:8]}, ancestor of HEAD {sha[:8]})")
    return (False, f"no fresh final-review receipt for HEAD {sha[:8]} on this repo")
