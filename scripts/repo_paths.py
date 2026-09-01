#!/usr/bin/env python3
"""Shared, defensive resolution of a `--repo` filesystem path.

The coordinator sometimes conflates two `--repo` conventions: the `gh` CLI's
`--repo <owner>/<repo>` slug vs. our scripts' `--repo <filesystem-path>`. When
it does, it concatenates them and passes a doubled path such as

    /Users/.../myrepo/owner/myrepo

(the real worktree root with an `<owner>/<repo>` slug wrongly appended). The
old `os.path.abspath()` + `os.path.isdir()` check then hard-fails and the
review/delivery gate is skipped entirely.

`resolve_repo_path()` recovers the real worktree: it peels bogus trailing
segments off a non-existent path (bounded, so a wholly-wrong path still fails
loudly) and normalizes any subdir to the git toplevel. The recovery is logged
to stderr so the coordinator's malformed invocations stay diagnosable.
"""

import os
import subprocess
import sys
from typing import Optional

# Max trailing segments to peel before giving up. The doubled-path case needs 2
# (`<owner>/<repo>`); 3 leaves headroom without resolving a wholly-wrong path to
# a distant ancestor.
_MAX_STRIPS = 3


def resolve_repo_path(raw: Optional[str], *, warn: bool = True) -> Optional[str]:
    """Return a valid repo directory for `raw`, or None if unrecoverable.

    Steps: expand/abspath -> peel non-existent trailing segments (<= _MAX_STRIPS)
    -> normalize to the git worktree root. Best-effort git step: a valid
    non-git directory is returned as-is.
    """
    if not raw or not str(raw).strip():
        return None

    p = os.path.abspath(os.path.expanduser(str(raw)))
    original = p

    # Peel trailing components that don't exist on disk (recovers the doubled
    # `<root>/<owner>/<repo>` path back to `<root>`).
    strips = 0
    while not os.path.isdir(p) and strips < _MAX_STRIPS:
        parent = os.path.dirname(p)
        if parent == p:  # reached the filesystem root
            break
        p = parent
        strips += 1

    if not os.path.isdir(p):
        return None

    # Normalize a subdir to the git worktree root (best-effort).
    try:
        top = subprocess.run(
            ["git", "-C", p, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if top.returncode == 0 and top.stdout.strip():
            p = os.path.abspath(top.stdout.strip())
    except Exception:
        pass

    if warn and p != original:
        print(f"[repo_paths] recovered repo path: {original!r} -> {p!r}",
              file=sys.stderr)
    return p
